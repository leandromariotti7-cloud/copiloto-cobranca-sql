"""Camada de modelo: Claude (online) ou stub determinístico (offline).

O grafo (graph.py) sempre consome dois *Runnables* do LangChain:
  - `cadeia_sql`    : pergunta → SQLDraft(sql, explicacao)
  - `cadeia_resumo` : (pergunta, linhas) → texto em pt-BR

Online, esses Runnables são `ChatPromptTemplate | ChatAnthropic(...)` — ou
seja, Claude de verdade via langchain-anthropic. Offline (sem credencial, ou
`COPILOTO_OFFLINE=1`), são `RunnableLambda`s baseados em regras, para o
projeto rodar e ser testado sem rede. A INTERFACE é a mesma nos dois casos —
é isso que mantém o grafo agnóstico ao backend.
"""
from __future__ import annotations

import os
import re

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel, Field

from .schema import DESCRICAO_SCHEMA

# Modelo default = o mais capaz; troque por claude-sonnet-5 para baratear.
MODELO_PADRAO = os.environ.get("COPILOTO_MODEL", "claude-opus-5")


class SQLDraft(BaseModel):
    """Saída estruturada do passo de geração de SQL."""
    sql: str = Field(description="UMA consulta SELECT em dialeto SQLite.")
    explicacao: str = Field(
        description="Uma frase em pt-BR explicando o que a consulta faz."
    )


# --------------------------------------------------------------------------
# Detecção de modo
# --------------------------------------------------------------------------
def online_disponivel() -> bool:
    """True se devemos usar Claude de verdade."""
    if os.environ.get("COPILOTO_OFFLINE") == "1":
        return False
    return bool(
        os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    )


def _chat_anthropic():
    """Instancia o ChatAnthropic. Importado tardiamente para o modo offline
    não exigir credencial nem tocar a rede."""
    from langchain_anthropic import ChatAnthropic

    # NÃO passamos `temperature`: os modelos Opus 5 / 4.x rejeitam o parâmetro
    # (400). max_tokens enxuto — a saída é um SQL curto / um resumo curto.
    return ChatAnthropic(model=MODELO_PADRAO, max_tokens=2000)


# --------------------------------------------------------------------------
# Cadeia de geração de SQL
# --------------------------------------------------------------------------
_SISTEMA_SQL = (
    "Você é um especialista em SQL (dialeto SQLite) que traduz perguntas de "
    "negócio sobre cobrança/recuperação de crédito em UMA única consulta "
    "SELECT.\n"
    "Regras rígidas:\n"
    "- Gere SOMENTE uma instrução SELECT (ou CTE com WITH). Nunca "
    "INSERT/UPDATE/DELETE/DDL.\n"
    "- Use apenas as tabelas e colunas do schema abaixo; não invente colunas.\n"
    "- Datas são TEXT 'YYYY-MM-DD'; use date()/strftime do SQLite.\n"
    "- Prefira apelidos legíveis (AS) e ORDER BY quando fizer sentido.\n"
    "- Se um erro da tentativa anterior for informado, corrija-o.\n\n"
    "SCHEMA:\n{schema}"
)
_HUMANO_SQL = (
    "Pergunta: {pergunta}\n"
    "{dica_erro}"
    "Responda com o SQL e uma breve explicação."
)


def cadeia_sql(online: bool | None = None) -> Runnable:
    """Runnable: dict(pergunta, dica_erro) -> SQLDraft."""
    if online is None:
        online = online_disponivel()
    if online:
        prompt = ChatPromptTemplate.from_messages(
            [("system", _SISTEMA_SQL), ("human", _HUMANO_SQL)]
        ).partial(schema=DESCRICAO_SCHEMA)
        return prompt | _chat_anthropic().with_structured_output(SQLDraft)
    return RunnableLambda(_sql_offline)


def cadeia_resumo(online: bool | None = None) -> Runnable:
    """Runnable: dict(pergunta, sql, linhas) -> str (resposta em pt-BR)."""
    if online is None:
        online = online_disponivel()
    if online:
        from langchain_core.output_parsers import StrOutputParser

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system",
                 "Você resume, em português claro e objetivo, o resultado de "
                 "uma consulta de cobrança para um gestor. 1 a 3 frases, cite "
                 "números concretos. Não invente dados além das linhas dadas."),
                ("human",
                 "Pergunta: {pergunta}\nSQL: {sql}\n"
                 "Linhas (JSON): {linhas}\n\nResuma a resposta."),
            ]
        )
        return prompt | _chat_anthropic() | StrOutputParser()
    return RunnableLambda(_resumo_offline)


# --------------------------------------------------------------------------
# Stubs offline (determinísticos, baseados em regras)
# --------------------------------------------------------------------------
def _sql_offline(payload: dict) -> SQLDraft:
    """Mapeia perguntas conhecidas para SQL. Suficiente para a demo/testes."""
    q = _normalizar(payload.get("pergunta", ""))

    regras: list[tuple[list[str], SQLDraft]] = [
        (["recuperad", "escritorio"], SQLDraft(
            sql=(
                "SELECT e.nome AS escritorio, "
                "ROUND(SUM(p.valor_pago), 2) AS total_recuperado\n"
                "FROM pagamentos p\n"
                "JOIN acordos a   ON a.acordo_id = p.acordo_id\n"
                "JOIN contratos c ON c.contrato_id = a.contrato_id\n"
                "JOIN escritorios e ON e.escritorio_id = c.escritorio_id\n"
                "GROUP BY e.nome\nORDER BY total_recuperado DESC"),
            explicacao="Soma os pagamentos recebidos por escritório.")),
        (["quebrad"], SQLDraft(
            sql=(
                "SELECT e.nome AS escritorio, "
                "COUNT(*) AS acordos_quebrados\n"
                "FROM acordos a\n"
                "JOIN contratos c ON c.contrato_id = a.contrato_id\n"
                "JOIN escritorios e ON e.escritorio_id = c.escritorio_id\n"
                "WHERE a.status = 'Quebrado'\n"
                "GROUP BY e.nome\nORDER BY acordos_quebrados DESC"),
            explicacao="Conta acordos quebrados por escritório.")),
        (["atraso", "90"], SQLDraft(
            sql=(
                "SELECT COUNT(*) AS contratos_atraso_90mais\n"
                "FROM contratos\n"
                "WHERE dias_atraso > 90 AND status <> 'Quitado'"),
            explicacao="Conta contratos com mais de 90 dias de atraso.")),
        (["aberto", "produto"], SQLDraft(
            sql=(
                "SELECT produto, ROUND(SUM(valor_divida), 2) AS total_aberto\n"
                "FROM contratos\nWHERE status = 'Em aberto'\n"
                "GROUP BY produto\nORDER BY total_aberto DESC"),
            explicacao="Soma o saldo devedor em aberto por produto.")),
        (["cliente", "recuperad"], SQLDraft(
            sql=(
                "SELECT cl.nome AS cliente, "
                "ROUND(SUM(p.valor_pago), 2) AS recuperado\n"
                "FROM pagamentos p\n"
                "JOIN acordos a   ON a.acordo_id = p.acordo_id\n"
                "JOIN contratos c ON c.contrato_id = a.contrato_id\n"
                "JOIN clientes cl ON cl.cliente_id = c.cliente_id\n"
                "GROUP BY cl.cliente_id\nORDER BY recuperado DESC\nLIMIT 5"),
            explicacao="Top 5 clientes por valor recuperado.")),
    ]

    for chaves, draft in regras:
        if all(k in q for k in chaves):
            return draft

    # fallback seguro
    return SQLDraft(
        sql="SELECT COUNT(*) AS total_contratos FROM contratos",
        explicacao=("Modo offline: pergunta não reconhecida pelas regras. "
                    "Defina ANTHROPIC_API_KEY para usar o Claude e cobrir "
                    "qualquer pergunta."))


def _resumo_offline(payload: dict) -> str:
    linhas = payload.get("linhas") or []
    if isinstance(linhas, str):  # o nó `resumir` serializa como JSON
        import json
        linhas = json.loads(linhas) if linhas.strip() else []
    pergunta = payload.get("pergunta", "")
    if not linhas:
        return "Nenhum resultado para a consulta."
    if len(linhas) == 1 and len(linhas[0]) == 1:
        (chave, valor), = linhas[0].items()
        return f"Resposta: {chave} = {valor}."
    topo = linhas[0]
    partes = ", ".join(f"{k}={v}" for k, v in topo.items())
    return (f"[modo offline] {len(linhas)} linha(s). "
            f"Primeira: {partes}. (Resumo em linguagem natural requer o "
            f"Claude — defina ANTHROPIC_API_KEY.)")


def _normalizar(texto: str) -> str:
    texto = texto.lower()
    # remove acentos simples para casar 'escritório' ~ 'escritorio'
    for a, b in [("á", "a"), ("ã", "a"), ("â", "a"), ("é", "e"), ("ê", "e"),
                 ("í", "i"), ("ó", "o"), ("ô", "o"), ("õ", "o"), ("ú", "u"),
                 ("ç", "c")]:
        texto = texto.replace(a, b)
    return re.sub(r"\s+", " ", texto)

"""O grafo LangGraph do copiloto text-to-SQL.

Fluxo:

        ┌─────────┐
        │ START   │
        └────┬────┘
             ▼
     ┌───────────────┐   erro de validação/execução e ainda há tentativa
     │  gerar_sql    │◄──────────────────────────────────────────────┐
     └──────┬────────┘                                                │
            ▼                                                         │
     ┌───────────────┐   SQL inválido ──────────────────────────────▶┤
     │   validar     │                                                │
     └──────┬────────┘                                                │
            ▼ ok                                                      │
     ┌───────────────┐   erro de execução ─────────────────────────▶─┘
     │   executar    │
     └──────┬────────┘
            ▼ ok
     ┌───────────────┐
     │   resumir     │
     └──────┬────────┘
            ▼
          END

As arestas condicionais fazem o copiloto se auto-corrigir: quando o SQL é
recusado pelos guardrails ou quebra na execução, o erro volta como contexto
para `gerar_sql` tentar de novo (até MAX_TENTATIVAS).
"""
from __future__ import annotations

import json
import sqlite3
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from . import db, guardrails, llm

MAX_TENTATIVAS = 3


class EstadoCopiloto(TypedDict, total=False):
    pergunta: str       # entrada do usuário
    tentativas: int     # quantas vezes já geramos SQL
    sql: str            # SQL atual (validado após o nó `validar`)
    explicacao: str     # explicação do LLM para o SQL
    erro: str | None    # último erro (validação ou execução), se houver
    colunas: list[str]
    linhas: list[dict]
    truncado: bool
    resposta: str       # resumo final em pt-BR


def construir_grafo(online: bool | None = None,
                    caminho_db=db.CAMINHO_PADRAO):
    """Compila e devolve o grafo. As cadeias de LLM são criadas uma vez."""
    cadeia_sql = llm.cadeia_sql(online)
    cadeia_resumo = llm.cadeia_resumo(online)

    def gerar_sql(estado: EstadoCopiloto) -> dict:
        dica = ""
        if estado.get("erro"):
            dica = (f"A tentativa anterior falhou com o erro: "
                    f"{estado['erro']}\nCorrija o SQL.\n")
        draft = cadeia_sql.invoke(
            {"pergunta": estado["pergunta"], "dica_erro": dica}
        )
        return {
            "sql": draft.sql,
            "explicacao": draft.explicacao,
            "tentativas": estado.get("tentativas", 0) + 1,
            "erro": None,
        }

    def validar(estado: EstadoCopiloto) -> dict:
        try:
            validado = guardrails.validar(estado["sql"])
            return {"sql": validado.sql, "erro": None}
        except guardrails.SQLInvalido as e:
            return {"erro": f"SQL recusado pelos guardrails: {e}"}

    def executar(estado: EstadoCopiloto) -> dict:
        try:
            res = db.executar(estado["sql"], caminho=caminho_db)
            return {
                "colunas": res.colunas,
                "linhas": res.linhas,
                "truncado": res.truncado,
                "erro": None,
            }
        except sqlite3.Error as e:
            return {"erro": f"Erro ao executar o SQL: {e}"}

    def resumir(estado: EstadoCopiloto) -> dict:
        resposta = cadeia_resumo.invoke({
            "pergunta": estado["pergunta"],
            "sql": estado.get("sql", ""),
            "linhas": json.dumps(estado.get("linhas", []), ensure_ascii=False),
        })
        return {"resposta": resposta}

    def _rota_pos_validar(estado: EstadoCopiloto) -> str:
        if not estado.get("erro"):
            return "executar"
        if estado.get("tentativas", 0) < MAX_TENTATIVAS:
            return "gerar_sql"
        return END

    def _rota_pos_executar(estado: EstadoCopiloto) -> str:
        if not estado.get("erro"):
            return "resumir"
        if estado.get("tentativas", 0) < MAX_TENTATIVAS:
            return "gerar_sql"
        return END

    g = StateGraph(EstadoCopiloto)
    g.add_node("gerar_sql", gerar_sql)
    g.add_node("validar", validar)
    g.add_node("executar", executar)
    g.add_node("resumir", resumir)

    g.add_edge(START, "gerar_sql")
    g.add_edge("gerar_sql", "validar")
    g.add_conditional_edges("validar", _rota_pos_validar,
                            {"executar": "executar",
                             "gerar_sql": "gerar_sql", END: END})
    g.add_conditional_edges("executar", _rota_pos_executar,
                            {"resumir": "resumir",
                             "gerar_sql": "gerar_sql", END: END})
    g.add_edge("resumir", END)
    return g.compile()


def perguntar(pergunta: str, online: bool | None = None,
              caminho_db=db.CAMINHO_PADRAO) -> EstadoCopiloto:
    """Atalho: constrói o grafo, roda uma pergunta e devolve o estado final."""
    grafo = construir_grafo(online=online, caminho_db=caminho_db)
    estado_inicial: EstadoCopiloto = {"pergunta": pergunta, "tentativas": 0}
    return grafo.invoke(estado_inicial)

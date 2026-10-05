"""Guardrails do SQL gerado pelo LLM — defesa em profundidade.

Checagens *em cima do texto* do SQL, antes de qualquer execução:
  1. há exatamente UMA instrução (bloqueia `;` encadeado / injeção);
  2. a instrução começa com SELECT ou WITH (nada de DDL/DML);
  3. nenhuma palavra-chave perigosa (INSERT/UPDATE/DELETE/DROP/ATTACH/PRAGMA...);
  4. todas as tabelas referenciadas estão na allowlist do schema;
  5. um LIMIT é garantido (injeta `LIMIT N` se não houver).

Isto se SOMA à conexão somente-leitura do `db.py` (authorizer do SQLite):
se um ataque passar pelo texto, o banco ainda recusa a escrita.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .schema import TABELAS_PERMITIDAS

LIMITE_PADRAO = 200

# Palavras que nunca devem aparecer num SELECT de leitura.
PALAVRAS_PROIBIDAS = {
    "insert", "update", "delete", "drop", "alter", "create", "replace",
    "truncate", "attach", "detach", "pragma", "vacuum", "reindex", "grant",
    "revoke", "exec", "execute",
}


class SQLInvalido(ValueError):
    """SQL rejeitado pelos guardrails."""


@dataclass
class SQLValidado:
    sql: str          # SQL final (com LIMIT garantido)
    tabelas: set[str]  # tabelas referenciadas


def _remover_comentarios_e_strings(sql: str) -> str:
    """Remove literais de string e comentários para a análise de tokens.

    Evita falso-positivo (ex.: a palavra 'delete' dentro de um nome) e
    falso-negativo em comentários. A versão original é a executada; esta
    cópia higienizada serve só para inspeção.
    """
    sql = re.sub(r"--[^\n]*", " ", sql)          # comentários de linha
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)  # comentários de bloco
    sql = re.sub(r"'(?:[^']|'')*'", " '' ", sql)  # strings 'entre aspas'
    sql = re.sub(r'"(?:[^"]|"")*"', ' "" ', sql)  # identificadores "aspas"
    return sql


def _instrucoes(sql_limpo: str) -> list[str]:
    """Divide por ';' e descarta instruções vazias/brancas."""
    return [s for s in (p.strip() for p in sql_limpo.split(";")) if s]


def _nomes_cte(sql_limpo: str) -> set[str]:
    """Nomes definidos por CTE (`WITH nome AS (...)`) — não são tabelas reais."""
    return {m.group(1).lower() for m in
            re.finditer(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s+as\s*\(",
                        sql_limpo, flags=re.I)}


def _tabelas_referenciadas(sql_limpo: str) -> set[str]:
    """Extrai nomes após FROM/JOIN, excluindo aliases de CTE."""
    nomes = set()
    for m in re.finditer(r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)",
                         sql_limpo, flags=re.I):
        nomes.add(m.group(1).lower())
    return nomes - _nomes_cte(sql_limpo)


def _tem_limit(sql_limpo: str) -> bool:
    return re.search(r"\blimit\b", sql_limpo, flags=re.I) is not None


def validar(sql: str, limite: int = LIMITE_PADRAO) -> SQLValidado:
    """Valida e normaliza o SQL. Levanta `SQLInvalido` se recusado."""
    if not sql or not sql.strip():
        raise SQLInvalido("SQL vazio.")

    bruto = sql.strip().rstrip(";").strip()
    limpo = _remover_comentarios_e_strings(bruto)

    instr = _instrucoes(limpo)
    if len(instr) != 1:
        raise SQLInvalido(
            f"Esperava 1 instrução, encontrei {len(instr)} "
            "(múltiplas instruções não são permitidas)."
        )

    tokens = set(re.findall(r"[a-zA-Z_]+", limpo.lower()))
    proibidas = tokens & PALAVRAS_PROIBIDAS
    if proibidas:
        raise SQLInvalido(
            "Comando não permitido (apenas leitura): "
            + ", ".join(sorted(proibidas))
        )

    primeira = re.match(r"\s*([a-zA-Z]+)", limpo)
    if not primeira or primeira.group(1).lower() not in ("select", "with"):
        raise SQLInvalido("Só são permitidas consultas SELECT (ou CTE WITH).")

    tabelas = _tabelas_referenciadas(limpo)
    fora = tabelas - TABELAS_PERMITIDAS
    if fora:
        raise SQLInvalido(
            "Tabela(s) fora do schema permitido: " + ", ".join(sorted(fora))
        )

    final = bruto if _tem_limit(limpo) else f"{bruto}\nLIMIT {limite}"
    return SQLValidado(sql=final, tabelas=tabelas)

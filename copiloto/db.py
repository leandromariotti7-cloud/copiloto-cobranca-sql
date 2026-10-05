"""Camada de banco: construção, persistência e execução SOMENTE-LEITURA.

A segunda linha de defesa (depois dos guardrails de texto): a conexão de
consulta é aberta em modo `ro` e com um *authorizer* do SQLite que recusa
qualquer operação que não seja leitura — mesmo que um SQL malicioso passasse
pela validação textual.
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from . import seed

CAMINHO_PADRAO = Path(__file__).resolve().parent.parent / "data" / "cobranca.db"
MAX_LINHAS = 200
TIMEOUT_S = 5.0


@dataclass
class Resultado:
    colunas: list[str]
    linhas: list[dict]
    truncado: bool


def garantir_banco(caminho: Path | str = CAMINHO_PADRAO) -> Path:
    """Cria o arquivo de banco na primeira vez; idempotente depois."""
    caminho = Path(caminho)
    if caminho.exists() and caminho.stat().st_size > 0:
        return caminho
    caminho.parent.mkdir(parents=True, exist_ok=True)
    # cria em arquivo temporário e renomeia (evita banco meio-escrito)
    tmp = caminho.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    conn = seed.criar_banco(str(tmp))
    conn.close()
    os.replace(tmp, caminho)
    return caminho


def _authorizer(acao, _a1, _a2, _a3, _a4):
    """Permite apenas SELECT/READ e navegação; nega escrita/esquema."""
    permitidas = {
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_FUNCTION,
    }
    return sqlite3.SQLITE_OK if acao in permitidas else sqlite3.SQLITE_DENY


def conectar_ro(caminho: Path | str = CAMINHO_PADRAO) -> sqlite3.Connection:
    """Abre conexão somente-leitura (URI mode=ro) + authorizer restritivo."""
    caminho = Path(caminho)
    uri = f"file:{caminho}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=TIMEOUT_S)
    conn.row_factory = sqlite3.Row
    conn.set_authorizer(_authorizer)
    return conn


def executar(sql: str, caminho: Path | str = CAMINHO_PADRAO,
             max_linhas: int = MAX_LINHAS) -> Resultado:
    """Executa um SELECT já validado e devolve linhas como dicts.

    Levanta `sqlite3.Error` em falha de execução (quem chama trata o retry).
    """
    garantir_banco(caminho)
    conn = conectar_ro(caminho)
    try:
        cur = conn.execute(sql)
        colunas = [d[0] for d in cur.description] if cur.description else []
        brutas = cur.fetchmany(max_linhas + 1)
        truncado = len(brutas) > max_linhas
        linhas = [dict(r) for r in brutas[:max_linhas]]
        return Resultado(colunas=colunas, linhas=linhas, truncado=truncado)
    finally:
        conn.close()

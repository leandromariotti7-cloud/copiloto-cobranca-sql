"""Testes dos guardrails de SQL — a camada de segurança textual."""
import pytest

from copiloto import guardrails as gr


def test_select_simples_recebe_limit():
    v = gr.validar("SELECT * FROM contratos")
    assert "LIMIT" in v.sql.upper()
    assert v.tabelas == {"contratos"}


def test_limit_existente_e_preservado():
    v = gr.validar("SELECT * FROM clientes LIMIT 10")
    assert v.sql.upper().count("LIMIT") == 1
    assert v.sql.strip().upper().endswith("LIMIT 10")


def test_with_cte_permitido():
    sql = ("WITH x AS (SELECT escritorio_id FROM contratos) "
           "SELECT COUNT(*) FROM x JOIN escritorios "
           "ON escritorios.escritorio_id = x.escritorio_id")
    v = gr.validar(sql)
    assert "escritorios" in v.tabelas


@pytest.mark.parametrize("sql", [
    "DELETE FROM contratos",
    "UPDATE contratos SET valor_divida = 0",
    "INSERT INTO clientes VALUES (1,'x','SP','Varejo')",
    "DROP TABLE acordos",
    "SELECT 1; DROP TABLE acordos",          # múltiplas instruções
    "SELECT * FROM contratos; DELETE FROM contratos",
    "PRAGMA table_info(contratos)",
    "ATTACH DATABASE 'x.db' AS y",
])
def test_comandos_perigosos_sao_recusados(sql):
    with pytest.raises(gr.SQLInvalido):
        gr.validar(sql)


def test_tabela_fora_do_schema_recusada():
    with pytest.raises(gr.SQLInvalido):
        gr.validar("SELECT * FROM sqlite_master")


def test_sql_vazio_recusado():
    with pytest.raises(gr.SQLInvalido):
        gr.validar("   ")


def test_delete_dentro_de_string_nao_e_falso_positivo():
    # 'delete' aqui é um literal, não um comando
    v = gr.validar("SELECT nome FROM clientes WHERE nome = 'delete me'")
    assert v.tabelas == {"clientes"}

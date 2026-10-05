"""Testes da camada de banco: povoamento e somente-leitura."""
import sqlite3

import pytest

from copiloto import db, schema, seed


@pytest.fixture()
def banco(tmp_path):
    caminho = tmp_path / "t.db"
    db.garantir_banco(caminho)
    return caminho


def test_povoamento_tem_todas_as_tabelas():
    conn = seed.criar_banco(":memory:")
    resumo = seed.resumo_povoamento(conn)
    assert set(resumo) == schema.TABELAS_PERMITIDAS
    assert resumo["clientes"] == seed.N_CLIENTES
    assert resumo["contratos"] == seed.N_CONTRATOS
    assert resumo["escritorios"] == len(seed.ESCRITORIOS)
    # tem que haver acordos e pagamentos gerados
    assert resumo["acordos"] > 0
    assert resumo["pagamentos"] > 0
    conn.close()


def test_determinismo_mesmo_banco_duas_vezes():
    a = seed.resumo_povoamento(seed.criar_banco(":memory:"))
    b = seed.resumo_povoamento(seed.criar_banco(":memory:"))
    assert a == b


def test_select_funciona(banco):
    res = db.executar("SELECT COUNT(*) AS n FROM contratos", caminho=banco)
    assert res.colunas == ["n"]
    assert res.linhas[0]["n"] == seed.N_CONTRATOS


def test_conexao_e_somente_leitura(banco):
    # tentativa de escrita deve falhar na conexão ro + authorizer
    with pytest.raises(sqlite3.Error):
        db.executar("DELETE FROM contratos", caminho=banco)


def test_limite_de_linhas_trunca(banco):
    res = db.executar("SELECT * FROM contratos", caminho=banco, max_linhas=5)
    assert len(res.linhas) == 5
    assert res.truncado is True

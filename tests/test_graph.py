"""Testes end-to-end do grafo LangGraph em modo OFFLINE (sem rede).

Exercitam o fluxo inteiro: gerar_sql → validar → executar → resumir,
além da aresta de auto-correção quando o SQL inicial é inválido.
"""
import pytest

from copiloto import graph, llm


@pytest.fixture()
def banco(tmp_path):
    from copiloto import db
    caminho = tmp_path / "g.db"
    db.garantir_banco(caminho)
    return caminho


def test_recuperado_por_escritorio(banco):
    est = graph.perguntar("Quanto foi recuperado por escritório?",
                          online=False, caminho_db=banco)
    assert est.get("erro") is None
    assert "escritorio" in est["colunas"]
    assert "total_recuperado" in est["colunas"]
    assert len(est["linhas"]) > 0
    # soma recuperada deve ser positiva
    assert est["linhas"][0]["total_recuperado"] > 0
    assert est["resposta"]  # resumo preenchido


def test_contratos_em_atraso_90(banco):
    est = graph.perguntar("Quantos contratos estão em atraso há mais de 90 dias?",
                          online=False, caminho_db=banco)
    assert est.get("erro") is None
    assert est["linhas"][0]["contratos_atraso_90mais"] >= 0


def test_sql_limit_e_injetado_pelos_guardrails(banco):
    # a regra offline de "top 5" já traz LIMIT; a de atraso não traz —
    # validamos que o SQL final sempre executa sem erro
    est = graph.perguntar("Qual o valor total em aberto por produto?",
                          online=False, caminho_db=banco)
    assert est.get("erro") is None
    assert "LIMIT" in est["sql"].upper()


def test_auto_correcao_quando_sql_invalido(banco, monkeypatch):
    """Se o 1º SQL for inválido, o grafo deve re-gerar e, no fim, acertar."""
    from copiloto.llm import SQLDraft

    chamadas = {"n": 0}
    bom = SQLDraft(
        sql="SELECT COUNT(*) AS n FROM contratos",
        explicacao="conta contratos")

    def fake_sql(online=None):
        from langchain_core.runnables import RunnableLambda

        def _gen(payload):
            chamadas["n"] += 1
            if chamadas["n"] == 1:
                # 1ª tentativa: tabela proibida -> guardrails recusam
                return SQLDraft(sql="SELECT * FROM sqlite_master",
                                explicacao="inválida de propósito")
            return bom
        return RunnableLambda(_gen)

    monkeypatch.setattr(llm, "cadeia_sql", fake_sql)

    est = graph.perguntar("qualquer", online=False, caminho_db=banco)
    assert chamadas["n"] >= 2          # re-gerou pelo menos uma vez
    assert est.get("erro") is None     # terminou bem
    assert est["linhas"][0]["n"] > 0

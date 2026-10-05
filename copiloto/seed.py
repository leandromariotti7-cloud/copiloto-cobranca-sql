"""Gerador de dados sintéticos determinístico (tema: recuperação de crédito).

Determinístico de propósito (`random.seed(SEED)`): o mesmo banco é
reconstruído toda vez, então os testes e a demo têm números estáveis.
Nada aqui depende de rede nem de dados reais do Itaú.
"""
from __future__ import annotations

import datetime as dt
import random
import sqlite3

from . import schema

SEED = 42

ESCRITORIOS = [
    ("BELLINATI", "Sudeste"),
    ("GRB", "Sul"),
    ("PASCHOALOTTO", "Sudeste"),
    ("REDE BRASIL", "Nordeste"),
    ("SISCOM", "Centro-Oeste"),
    ("TSP", "Sudeste"),
    ("AVAL", "Sul"),
]
UFS = ["SP", "RJ", "MG", "RS", "PR", "BA", "PE", "GO", "SC", "CE"]
SEGMENTOS = ["Varejo", "Uniclass", "Personnalite"]
PRODUTOS = ["Cartao", "Credito Pessoal", "Financiamento", "Cheque Especial"]
CANAIS = ["Boleto", "PIX", "Debito", "Portal"]
PRIMEIROS = ["Ana", "Bruno", "Carla", "Diego", "Elaine", "Fabio", "Gisele",
             "Hugo", "Igor", "Juliana", "Katia", "Lucas", "Marina", "Nelson",
             "Olivia", "Paulo", "Renata", "Sergio", "Tatiana", "Vitor"]
SOBRENOMES = ["Silva", "Souza", "Oliveira", "Santos", "Pereira", "Costa",
              "Rodrigues", "Almeida", "Nascimento", "Lima", "Araujo", "Ferreira"]

N_CLIENTES = 400
N_CONTRATOS = 650
DATA_BASE = dt.date(2026, 9, 30)  # "hoje" sintético


def _data_str(d: dt.date) -> str:
    return d.isoformat()


def criar_banco(destino: str = ":memory:") -> sqlite3.Connection:
    """Cria o banco, aplica o DDL e popula com dados sintéticos.

    Retorna uma conexão aberta (gravável) para o banco em `destino`.
    Use ':memory:' para testes ou um caminho de arquivo para persistir.
    """
    rng = random.Random(SEED)
    conn = sqlite3.connect(destino)
    conn.executescript(schema.DDL)

    # --- escritórios ---
    escritorios = []
    for i, (nome, regiao) in enumerate(ESCRITORIOS, start=1):
        escritorios.append((i, nome, regiao))
    conn.executemany(
        "INSERT INTO escritorios VALUES (?,?,?)", escritorios
    )

    # --- clientes ---
    clientes = []
    for cid in range(1, N_CLIENTES + 1):
        nome = f"{rng.choice(PRIMEIROS)} {rng.choice(SOBRENOMES)}"
        clientes.append((cid, nome, rng.choice(UFS), rng.choice(SEGMENTOS)))
    conn.executemany("INSERT INTO clientes VALUES (?,?,?,?)", clientes)

    # --- contratos ---
    contratos = []
    for ctid in range(1, N_CONTRATOS + 1):
        cliente_id = rng.randint(1, N_CLIENTES)
        escritorio_id = rng.randint(1, len(ESCRITORIOS))
        produto = rng.choice(PRODUTOS)
        valor = round(rng.uniform(500, 60000), 2)
        dias_atraso = rng.choice([0, 0, 15, 30, 60, 90, 120, 180, 360])
        venc = DATA_BASE - dt.timedelta(days=dias_atraso + rng.randint(0, 30))
        # status correlacionado com atraso para dados plausíveis
        if dias_atraso == 0:
            status = rng.choice(["Em aberto", "Quitado"])
        elif dias_atraso <= 60:
            status = rng.choice(["Em aberto", "Em acordo", "Em acordo"])
        else:
            status = rng.choice(["Em acordo", "Em aberto", "Baixado"])
        contratos.append((ctid, cliente_id, escritorio_id, produto, valor,
                          dias_atraso, _data_str(venc), status))
    conn.executemany(
        "INSERT INTO contratos VALUES (?,?,?,?,?,?,?,?)", contratos
    )

    # --- acordos (só para contratos "Em acordo"/"Quitado") ---
    acordos = []
    pagamentos = []
    acordo_id = 0
    pagamento_id = 0
    for (ctid, _cli, _esc, _prod, valor, dias, _venc, status) in contratos:
        if status not in ("Em acordo", "Quitado"):
            continue
        acordo_id += 1
        valor_acordado = round(valor * rng.uniform(0.55, 1.0), 2)
        num_parcelas = rng.choice([1, 3, 6, 10, 12, 18, 24])
        data_acordo = DATA_BASE - dt.timedelta(days=rng.randint(5, 200))
        # desfecho do acordo
        if status == "Quitado":
            ac_status = "Quitado"
            pagas = num_parcelas
        else:
            ac_status = rng.choices(
                ["Ativo", "Quitado", "Quebrado"], weights=[5, 2, 3]
            )[0]
            if ac_status == "Quitado":
                pagas = num_parcelas
            elif ac_status == "Quebrado":
                pagas = rng.randint(0, max(0, num_parcelas // 2))
            else:  # Ativo
                pagas = rng.randint(1, max(1, num_parcelas - 1))
        acordos.append((acordo_id, ctid, _data_str(data_acordo),
                        valor_acordado, num_parcelas, ac_status))

        # pagamentos (uma parcela por mês a partir do acordo)
        valor_parcela = round(valor_acordado / num_parcelas, 2)
        for p in range(pagas):
            pagamento_id += 1
            dpag = data_acordo + dt.timedelta(days=30 * (p + 1))
            if dpag > DATA_BASE:
                break
            pagamentos.append((pagamento_id, acordo_id, _data_str(dpag),
                               valor_parcela, rng.choice(CANAIS)))

    conn.executemany("INSERT INTO acordos VALUES (?,?,?,?,?,?)", acordos)
    conn.executemany("INSERT INTO pagamentos VALUES (?,?,?,?,?)", pagamentos)
    conn.commit()
    return conn


def resumo_povoamento(conn: sqlite3.Connection) -> dict[str, int]:
    """Contagem de linhas por tabela — usada em logs/testes."""
    out = {}
    for t in sorted(schema.TABELAS_PERMITIDAS):
        out[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    return out

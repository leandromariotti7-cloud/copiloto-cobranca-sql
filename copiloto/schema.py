"""Schema do banco de cobrança/recuperação de crédito.

Mantém num só lugar: (1) o DDL para criar o banco, (2) a lista de tabelas
permitidas (consumida pelos guardrails) e (3) uma descrição legível que é
injetada no prompt do LLM. Manter os três sincronizados aqui evita que o
modelo "alucine" colunas que não existem.
"""

# Tabelas que o copiloto pode consultar. Qualquer SQL que toque algo fora
# desta lista é rejeitado pelos guardrails.
TABELAS_PERMITIDAS = frozenset(
    {"escritorios", "clientes", "contratos", "acordos", "pagamentos"}
)

DDL = """
CREATE TABLE escritorios (
    escritorio_id INTEGER PRIMARY KEY,
    nome          TEXT    NOT NULL,   -- ex.: BELLINATI, GRB, PASCHOALOTTO
    regiao        TEXT    NOT NULL    -- Sudeste, Sul, Nordeste, ...
);

CREATE TABLE clientes (
    cliente_id    INTEGER PRIMARY KEY,
    nome          TEXT    NOT NULL,
    uf            TEXT    NOT NULL,   -- SP, RJ, MG, ...
    segmento      TEXT    NOT NULL    -- Varejo, Uniclass, Personnalite
);

CREATE TABLE contratos (
    contrato_id    INTEGER PRIMARY KEY,
    cliente_id     INTEGER NOT NULL REFERENCES clientes(cliente_id),
    escritorio_id  INTEGER NOT NULL REFERENCES escritorios(escritorio_id),
    produto        TEXT    NOT NULL,  -- Cartao, Credito Pessoal, Financiamento, Cheque Especial
    valor_divida   REAL    NOT NULL,  -- saldo devedor em R$
    dias_atraso    INTEGER NOT NULL,  -- dias desde o vencimento
    data_vencimento TEXT   NOT NULL,  -- 'YYYY-MM-DD'
    status         TEXT    NOT NULL   -- Em aberto, Em acordo, Quitado, Baixado
);

CREATE TABLE acordos (
    acordo_id      INTEGER PRIMARY KEY,
    contrato_id    INTEGER NOT NULL REFERENCES contratos(contrato_id),
    data_acordo    TEXT    NOT NULL,  -- 'YYYY-MM-DD'
    valor_acordado REAL    NOT NULL,  -- valor negociado (<= valor_divida)
    num_parcelas   INTEGER NOT NULL,
    status         TEXT    NOT NULL   -- Ativo, Quitado, Quebrado
);

CREATE TABLE pagamentos (
    pagamento_id   INTEGER PRIMARY KEY,
    acordo_id      INTEGER NOT NULL REFERENCES acordos(acordo_id),
    data_pagamento TEXT    NOT NULL,  -- 'YYYY-MM-DD'
    valor_pago     REAL    NOT NULL,
    canal          TEXT    NOT NULL   -- Boleto, PIX, Debito, Portal
);
"""

# Descrição injetada no prompt do LLM — texto curto e factual.
DESCRICAO_SCHEMA = """\
Banco SQLite de cobrança/recuperação de crédito (dados em Reais, pt-BR).
Datas são TEXT no formato 'YYYY-MM-DD' — use strftime/date() do SQLite.

TABELAS E COLUNAS:

escritorios(escritorio_id, nome, regiao)
  - escritórios de cobrança terceirizados. nome ∈ {BELLINATI, GRB, PASCHOALOTTO,
    REDE BRASIL, SISCOM, TSP, AVAL}.

clientes(cliente_id, nome, uf, segmento)
  - segmento ∈ {Varejo, Uniclass, Personnalite}.

contratos(contrato_id, cliente_id, escritorio_id, produto, valor_divida,
          dias_atraso, data_vencimento, status)
  - uma dívida de um cliente, alocada a um escritório.
  - produto ∈ {Cartao, Credito Pessoal, Financiamento, Cheque Especial}.
  - status ∈ {Em aberto, Em acordo, Quitado, Baixado}.
  - valor_divida é o saldo devedor; dias_atraso é inteiro.

acordos(acordo_id, contrato_id, data_acordo, valor_acordado, num_parcelas, status)
  - negociação feita sobre um contrato. status ∈ {Ativo, Quitado, Quebrado}.
  - "Quebrado" = acordo não cumprido (quebra de acordo).

pagamentos(pagamento_id, acordo_id, data_pagamento, valor_pago, canal)
  - parcelas pagas de um acordo. canal ∈ {Boleto, PIX, Debito, Portal}.

RELACIONAMENTOS:
  contratos.cliente_id      -> clientes.cliente_id
  contratos.escritorio_id   -> escritorios.escritorio_id
  acordos.contrato_id       -> contratos.contrato_id
  pagamentos.acordo_id      -> acordos.acordo_id

NOÇÕES DE NEGÓCIO:
  - "recuperado" / "valor recuperado" = SUM(pagamentos.valor_pago).
  - "em atraso" = contratos com dias_atraso > 0 e status não quitado.
  - "quebra de acordo" = acordos.status = 'Quebrado'.
"""

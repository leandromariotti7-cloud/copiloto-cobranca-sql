"""Copiloto de Cobrança — text-to-SQL com LangGraph + Claude.

Pacote que expõe:
- `schema`     : DDL e descrição legível do banco (contexto para o LLM)
- `seed`       : gerador de dados sintéticos determinístico
- `db`         : conexão SQLite somente-leitura e execução segura
- `guardrails` : validação do SQL gerado (defesa em profundidade)
- `llm`        : fábrica do modelo (ChatAnthropic online / stub offline)
- `graph`      : o grafo LangGraph (gerar → validar → executar → resumir)
"""

__version__ = "1.0.0"
__all__ = ["schema", "seed", "db", "guardrails", "llm", "graph"]

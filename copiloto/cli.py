"""CLI do copiloto: pergunte em português, receba SQL + tabela + resumo.

Exemplos:
    python -m copiloto.cli "Quanto foi recuperado por escritório?"
    python -m copiloto.cli --demo
    COPILOTO_OFFLINE=1 python -m copiloto.cli "acordos quebrados por escritório"
"""
from __future__ import annotations

import argparse
import sys

from . import db, graph, llm

PERGUNTAS_DEMO = [
    "Quanto foi recuperado por escritório?",
    "Qual escritório tem mais acordos quebrados?",
    "Quantos contratos estão em atraso há mais de 90 dias?",
    "Qual o valor total em aberto por produto?",
    "Top 5 clientes por valor recuperado",
]


def _tabela(colunas: list[str], linhas: list[dict], max_linhas: int = 15) -> str:
    if not colunas:
        return "(sem colunas)"
    larguras = {c: len(str(c)) for c in colunas}
    amostra = linhas[:max_linhas]
    for r in amostra:
        for c in colunas:
            larguras[c] = max(larguras[c], len(str(r.get(c, ""))))
    sep = " | "
    cab = sep.join(str(c).ljust(larguras[c]) for c in colunas)
    reg = ["-" * len(cab)]
    for r in amostra:
        reg.append(sep.join(str(r.get(c, "")).ljust(larguras[c]) for c in colunas))
    extra = ""
    if len(linhas) > max_linhas:
        extra = f"\n... (+{len(linhas) - max_linhas} linha(s))"
    return cab + "\n" + "\n".join(reg) + extra


def _responder(pergunta: str, online: bool | None) -> int:
    estado = graph.perguntar(pergunta, online=online)
    print(f"\n❓ {pergunta}")
    if estado.get("sql"):
        print("\n🧮 SQL gerado:")
        print(estado["sql"])
    if estado.get("explicacao"):
        print(f"\n📝 {estado['explicacao']}")
    if estado.get("erro"):
        print(f"\n⛔ Não consegui responder: {estado['erro']}")
        return 1
    print("\n📊 Resultado:")
    print(_tabela(estado.get("colunas", []), estado.get("linhas", [])))
    if estado.get("truncado"):
        print("(resultado truncado pelo limite de linhas)")
    if estado.get("resposta"):
        print(f"\n💬 {estado['resposta']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Copiloto text-to-SQL de cobrança (LangGraph + Claude)."
    )
    p.add_argument("pergunta", nargs="*", help="pergunta em linguagem natural")
    p.add_argument("--demo", action="store_true",
                   help="roda um conjunto de perguntas de exemplo")
    modo = p.add_mutually_exclusive_group()
    modo.add_argument("--online", action="store_true",
                      help="força o uso do Claude (exige ANTHROPIC_API_KEY)")
    modo.add_argument("--offline", action="store_true",
                      help="força o modo offline (regras determinísticas)")
    args = p.parse_args(argv)

    online = True if args.online else (False if args.offline else None)
    efetivo = llm.online_disponivel() if online is None else online
    db.garantir_banco()
    print(f"🔌 Modo: {'ONLINE (Claude ' + llm.MODELO_PADRAO + ')' if efetivo else 'OFFLINE (regras)'}")

    if args.demo:
        rc = 0
        for q in PERGUNTAS_DEMO:
            rc |= _responder(q, online)
            print("\n" + "═" * 60)
        return rc

    if not args.pergunta:
        p.error("informe uma pergunta ou use --demo")
    return _responder(" ".join(args.pergunta), online)


if __name__ == "__main__":
    sys.exit(main())

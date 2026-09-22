from __future__ import annotations

import os
import sys

from sentinel import settings


def is_interactive() -> bool:
    """True quando ha um tty real pra receber input do usuario.

    Duas condicoes de bloqueio: stdin sem tty (pipe/agente) E a variavel
    de ambiente SENTINEL_NONINTERACTIVE definida (forca modo agente mesmo
    num terminal). Usado por `confirm` e pelo ciclo do tutor pra nunca
    deixar o Sentinel travado esperando uma tecla que nao vai chegar.
    """
    if os.environ.get(settings.NONINTERACTIVE_ENV_VAR):
        return False

    return sys.stdin.isatty()


def confirm(
    question: str,
    *,
    default: bool = False,
) -> bool:
    """
    Pergunta y/n ao usuario. Em sessao nao interativa (stdin sem tty ou
    SENTINEL_NONINTERACTIVE definido — ex.: agente de IA rodando o
    script), retorna `default` sem bloquear esperando input.

    Aceita "s"/"sim" alem de "y"/"yes" porque todo o resto do Sentinel
    conversa em portugues.
    """
    if not is_interactive():
        return default

    suffix = "[Y/n]" if default else "[y/N]"

    try:
        answer = input(f"{question} {suffix}: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return default

    if not answer:
        return default

    return answer in ("y", "yes", "s", "sim")


def ask_free(question: str) -> str:
    """Le uma linha livre do usuario (nota opcional na resolucao). Em
    sessao nao interativa retorna "" em vez de bloquear."""
    if not is_interactive():
        return ""

    try:
        return input(question).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""

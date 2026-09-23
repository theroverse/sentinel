#!/usr/bin/env python3

from __future__ import annotations

import sys
from pathlib import Path

# Garante que a saida fique na ordem certa mesmo quando redirecionada
# (pipe/arquivo), intercalada com output de subprocessos como "wevtutil"
# chamados sem capture.
#
# O `encoding` nao e enfeite: num console Windows em cp1252, um unico caractere
# fora daquela pagina (um BOM que veio de um arquivo, um travessao) derrubava o
# `print` do --json no meio da resposta — e a GUI ficava muda. A saida de
# maquina e UTF-8 por definicao; o console que se ajuste.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True, encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

_ENTRY_PATH = Path(__file__).resolve()
_SRC_DIR = _ENTRY_PATH.parent / "src"

if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from sentinel.cli import main

if __name__ == "__main__":
    main(_ENTRY_PATH)

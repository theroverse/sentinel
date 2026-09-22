from __future__ import annotations

import datetime
import os
import shutil
import subprocess


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def timestamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def run_command(
    command: list[str],
    *,
    cwd=None,
    capture: bool = True,
    text: bool = True,
    input_text: str | None = None,
) -> subprocess.CompletedProcess:
    """
    Execute a command reliably on Windows and Unix-like systems.

    Copiado do padrao de zeus/system/process.py: no Windows um launcher
    pode estar instalado como .cmd (shim npm) ou .exe, e subprocess com
    shell=False so acha o certo se for resolvido via shutil.which (que
    honra PATH + PATHEXT). Sem `encoding` explicito o Windows decodifica
    stdout pela codepage do console e corrompe UTF-8.
    """
    if not command:
        raise ValueError("Command cannot be empty.")

    executable = command[0]

    if os.name == "nt":
        resolved = shutil.which(executable)

        if resolved is not None:
            executable = resolved

        command = [executable, *command[1:]]

    return subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        capture_output=capture,
        text=text,
        encoding="utf-8" if text else None,
        input=input_text,
        shell=False,
    )

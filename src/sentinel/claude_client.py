from __future__ import annotations

import json
import re

from sentinel.system.process import command_exists, run_command


def call_claude(prompt: str, *, cwd=None) -> str | None:
    """Manda `prompt` ao Claude Code via stdin ('claude -p') e devolve o
    texto, ou None em qualquer falha.

    Clone do bridge do Zeus (mesma convencao Theroverse): unica saida de
    rede do Sentinel, disparada so quando o usuario roda `sentinel fix`.
    O daemon nunca chama isto.
    """
    if not command_exists("claude"):
        print("[ERROR] Claude Code executable was not found.")
        return None

    result = run_command(
        ["claude", "-p"],
        capture=True,
        cwd=cwd,
        input_text=prompt,
    )

    if result.returncode != 0:
        print("[ERROR] Claude returned an error.")
        if result.stderr:
            print(result.stderr)
        return None

    output = (result.stdout or "").strip()
    if not output:
        print("[ERROR] Claude returned empty output.")
        return None

    return output


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_options(text: str, *, max_options: int) -> list[dict] | None:
    """Converte a resposta do modelo em lista de opcoes. Tolera cerca de
    codigo e prosa ao redor: isola o primeiro array JSON [ ... ]. Devolve
    None se nada utilizavel sair — ai o tutor cai no fallback do kb.

    O contrato assertivo (title/why/steps/proof/risk/reversible) e validado
    com tolerancia de proposito: `title`+`steps` sao inegociaveis, e um
    modelo que respondeu um tutorial bom sem o campo `why` merece ser
    ouvido — nao descartado por formatacao. Quem escreve na base guarda o
    que veio vazio como vazio, e o `origin` diz que aquilo nao e curado.

    Opcoes malformadas sao descartadas uma a uma, sem derrubar o lote.
    Trunca em max_options.
    """
    if not text:
        return None

    candidate = text

    fenced = _FENCE.search(text)
    if fenced:
        candidate = fenced.group(1)

    start = candidate.find("[")
    end = candidate.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None

    blob = candidate[start : end + 1]

    try:
        data = json.loads(blob)
    except ValueError:
        return None

    if not isinstance(data, list):
        return None

    options: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        title = item.get("title")
        steps = item.get("steps")
        if not isinstance(title, str) or not isinstance(steps, list):
            continue
        steps = [str(s) for s in steps if str(s).strip()]
        if not steps:
            continue
        option = {"title": title.strip(), "steps": steps}
        for field in ("why", "proof", "risk"):
            value = item.get(field)
            if isinstance(value, str) and value.strip():
                option[field] = value.strip()
        if "reversible" in item:
            option["reversible"] = bool(item["reversible"])
        action = item.get("action")
        if isinstance(action, dict) and isinstance(action.get("type"), str):
            option["action"] = action
        options.append(option)

    if not options:
        return None

    return options[:max_options]

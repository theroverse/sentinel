from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from sentinel import settings


# ---------------------------------------------------------------------------
# O que o usuario autorizou, e o que nao
# ---------------------------------------------------------------------------
# `.sentinel/orders.json` e onde mora o consentimento do caminho autonomo.
# Ele nao e config de limiar (`config.json`): limiar sem arquivo continua
# valendo, ordem sem arquivo significa "nada autorizado", entao os dois tem
# que poder quebrar separados.
#
# Hoje so existe uma chave: o modo sombra (spec 5). As ordens permanentes por
# app dos degraus 2 e 3 vao morar aqui na fase E, depois da revisao das
# guardas -- nao antes, porque "existe um lugar pra guardar" nao significa
# que alguem autorizou.
#
# Modo sombra: os degraus sao calculados, decididos e gravados como decisao
# nao aplicada (`shadow: true`, `applied: false`, verbo `SERIA` no label), sem
# tocar em processo nenhum. Nao e o padrao -- o degrau 1 age
# desde o primeiro dia -- mas e a unica forma de ver o que o Sentinel faria
# antes de confiar nele.
@dataclass
class Orders:
    shadow: bool = False

    def to_dict(self) -> dict:
        return {"schema": 1, "shadow": bool(self.shadow)}


def load(paths: settings.Paths) -> Orders:
    """Le as ordens. Arquivo ausente ou ilegivel e o estado padrao: nada
    autorizado, degrau 1 agindo.

    Um JSON corrompido aqui NAO pode virar "modo sombra ligado" nem "desligado
    por engano" -- o conservador e devolver o padrao e deixar o arquivo no
    lugar pra quem olhar. Silencio nesse caso e o preco de um arquivo escrito
    a mao no Notepad.
    """
    if not paths.orders.is_file():
        return Orders()
    try:
        data = json.loads(paths.orders.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return Orders()
    if not isinstance(data, dict):
        return Orders()
    return Orders(shadow=bool(data.get("shadow", False)))


def save(paths: settings.Paths, orders: Orders) -> Path:
    """Grava atomico (tmp + replace): o daemon le este arquivo no meio de um
    ciclo, e uma escrita pela metade leria ordem nenhuma."""
    paths.ensure_output_dir()
    target = paths.orders
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".orders.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(orders.to_dict(), ensure_ascii=False) + "\n")
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return target

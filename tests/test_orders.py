from __future__ import annotations

# `.sentinel/orders.json` e onde mora o consentimento do caminho autonomo. As
# regras de leitura abaixo sao todas do mesmo tipo: ausencia e o estado
# padrao, e um arquivo ilegivel nunca pode virar autorizacao (nem interdicto)
# que ninguem deu.

import json

from sentinel import orders as orders_mod
from sentinel import settings


def paths_of(tmp_path) -> settings.Paths:
    return settings.paths_for(tmp_path)


def test_missing_file_authorizes_nothing(tmp_path):
    """Ordem sem arquivo e "nada autorizado", ao contrario do limiar, que sem
    arquivo continua valendo o padrao — os dois tem de poder quebrar
    separados."""
    state = orders_mod.load(paths_of(tmp_path))

    assert state.shadow is False
    assert not paths_of(tmp_path).orders.exists()


def test_save_and_load_round_trip(tmp_path):
    orders_mod.save(paths_of(tmp_path), orders_mod.Orders(shadow=True))

    assert orders_mod.load(paths_of(tmp_path)).shadow is True


def test_save_creates_the_territory(tmp_path):
    """`orders shadow --on` antes de qualquer `start` nao pode estourar por
    falta de pasta."""
    path = orders_mod.save(paths_of(tmp_path), orders_mod.Orders(shadow=True))

    assert path.is_file()
    assert path == paths_of(tmp_path).orders


def test_saved_shape_is_the_documented_one(tmp_path):
    orders_mod.save(paths_of(tmp_path), orders_mod.Orders(shadow=True))

    data = json.loads(paths_of(tmp_path).orders.read_text(encoding="utf-8"))

    assert data == {"schema": 1, "shadow": True}


def test_bom_is_tolerated(tmp_path):
    """Notepad e `Set-Content -Encoding utf8` gravam BOM: sem tolerar, o modo
    sombra voltaria ao padrao silenciosamente e ninguem entenderia por que."""
    paths_of(tmp_path).ensure_output_dir()
    paths_of(tmp_path).orders.write_text(
        "﻿" + json.dumps({"schema": 1, "shadow": True}), encoding="utf-8"
    )

    assert orders_mod.load(paths_of(tmp_path)).shadow is True


def test_broken_json_falls_back_to_the_default(tmp_path):
    """Um JSON corrompido aqui NAO pode virar "sombra ligada" nem "desligada
    por engano": o conservador e devolver o padrao e deixar o arquivo no
    lugar pra quem olhar."""
    paths = paths_of(tmp_path)
    paths.ensure_output_dir()
    paths.orders.write_text("{ shadow: sim", encoding="utf-8")

    assert orders_mod.load(paths).shadow is False
    assert paths.orders.is_file()


def test_a_list_is_not_orders(tmp_path):
    paths = paths_of(tmp_path)
    paths.ensure_output_dir()
    paths.orders.write_text("[1, 2, 3]", encoding="utf-8")

    assert orders_mod.load(paths) == orders_mod.Orders()


def test_unknown_keys_are_ignored(tmp_path):
    """Uma chave que esta versao nao le nao pode quebrar a leitura das que
    estao: o arquivo e do usuario, e ele edita na mao."""
    paths = paths_of(tmp_path)
    paths.ensure_output_dir()
    paths.orders.write_text(
        json.dumps({"schema": 1, "shadow": False, "qualquer_coisa": 1}),
        encoding="utf-8",
    )

    assert orders_mod.load(paths).shadow is False


def test_save_leaves_no_temp_file(tmp_path):
    orders_mod.save(paths_of(tmp_path), orders_mod.Orders(shadow=True))

    leftovers = [p.name for p in paths_of(tmp_path).output_dir.glob(".*")]

    assert leftovers == []


def test_to_dict_is_what_the_wizard_reads(tmp_path):
    """A GUI le o arquivo cru (`mock.js` espelha o formato): o dicionario
    publico tem de continuar dizendo `shadow`."""
    assert orders_mod.Orders(shadow=True).to_dict() == {"schema": 1, "shadow": True}

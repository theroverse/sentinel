from __future__ import annotations

from sentinel import kb, settings
from sentinel.detector import METRIC_CPU, METRIC_DISK, METRIC_IO, METRIC_RAM
from sentinel.incidents import METRIC_APP_FAILURE, METRIC_ORPHAN_TREE


def test_incident_metrics_have_templates():
    # Uma anomalia sem template morre descartada no `fix`: os dois tipos
    # novos de incidente precisam de resposta offline desde o dia zero.
    for metric in (METRIC_APP_FAILURE, METRIC_ORPHAN_TREE):
        options = kb.options_for(metric)
        assert options, f"sem template offline pra {metric}"
        assert len(options) <= settings.MAX_FIX_OPTIONS
        # O evento de incidente nao carrega top_processes: oferecer kill
        # automatico seria prometer um alvo que nao existe na linha.
        for opt in options:
            assert opt.get("action") is None
            assert opt["steps"]


def test_every_core_metric_has_templates():
    for metric in (METRIC_CPU, METRIC_RAM, METRIC_DISK, METRIC_IO):
        options = kb.options_for(metric)
        assert options, f"sem template offline pra {metric}"
        assert len(options) <= settings.MAX_FIX_OPTIONS


def test_options_shape():
    options = kb.options_for(METRIC_CPU)
    for opt in options:
        assert isinstance(opt["title"], str) and opt["title"]
        assert isinstance(opt["steps"], list) and opt["steps"]
        for step in opt["steps"]:
            assert isinstance(step, str)


def test_disk_never_offers_kill():
    # Disco cheio nao se resolve matando processo: nenhuma opcao de disk
    # deve carregar acao kill_top_process.
    for opt in kb.options_for(METRIC_DISK):
        assert opt.get("action", {}).get("type") != "kill_top_process"


def test_unknown_metric_returns_empty():
    assert kb.options_for("gpu") == []


def test_returns_copy_not_shared_state():
    first = kb.options_for(METRIC_RAM)
    first[0]["title"] = "MUTADO"
    again = kb.options_for(METRIC_RAM)
    assert again[0]["title"] != "MUTADO"

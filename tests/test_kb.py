from __future__ import annotations

from sentinel import kb, settings
from sentinel.detector import METRIC_CPU, METRIC_DISK, METRIC_IO, METRIC_RAM
from sentinel.incidents import METRIC_APP_FAILURE, METRIC_ORPHAN_TREE
from sentinel.stall import (
    METRIC_STALL,
    SIGNAL_DISK_SATURATED,
    SIGNAL_STARVED,
    SIGNAL_THRASHING,
)


def _stall_event(signals=(), measured=None, culprit="chrome"):
    """A linha de incidente como o `events.jsonl` a guarda: schema 2, com o
    mapa `detail` que o `StallMonitor` produz."""
    return {
        "schema": 2,
        "kind": "anomaly",
        "metric": METRIC_STALL,
        "severity": "critical",
        "label": "estagnacao",
        "detail": {
            "signals": list(signals),
            "culprit": None if culprit is None else {
                "name": culprit,
                "pid": 4321,
                "metric": "ram",
            },
            "measured": measured or {},
        },
        "status": "open",
        "fingerprint": f"stall:critical:{culprit}",
        "occurrences": 1,
    }


def _text(option):
    return " ".join([option["title"], option["why"], option["proof"],
                     option["risk"], *option["steps"]])


def test_incident_metrics_have_templates():
    # Uma anomalia sem template morre descartada no `fix`: os tipos novos de
    # incidente precisam de resposta offline desde o dia zero.
    for metric in (METRIC_APP_FAILURE, METRIC_ORPHAN_TREE, METRIC_STALL):
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


# ---------------------------------------------------------------------------
# Estagnacao: a prova citada e a que o indice mediu, nao uma generica
# ---------------------------------------------------------------------------


def test_stall_names_the_culprit_and_its_pid():
    event = _stall_event([SIGNAL_STARVED], {"sleep_s": 5.0, "interval_s": 2.0})
    options = kb.options_for(METRIC_STALL, event=event)
    assert "chrome" in options[0]["title"]
    assert "4321" in options[0]["steps"][0]


def test_starved_episode_cites_the_sleep_that_overshot():
    """A promessa do tutorial cirurgico: 'o sleep de 2 s levou 5 s'.

    Um numero que so existe no momento medido — e que nenhuma pagina de
    suporte conseguiria dizer.
    """
    event = _stall_event([SIGNAL_STARVED], {"sleep_s": 5.0, "interval_s": 2.0})
    text = " ".join(_text(opt) for opt in kb.options_for(METRIC_STALL, event=event))
    assert "o sleep de 2 s do daemon levou 5 s" in text


def test_zero_rate_is_never_cited_as_proof():
    """No Windows o psutil devolve `sin`/`sout` zerados: um tutorial que
    afirmasse a taxa estaria dizendo "0" como evidencia de gargalo. O sinal
    entao e carregado pela carga de commit, que la existe."""
    event = _stall_event(
        [SIGNAL_THRASHING],
        {"sleep_s": None, "interval_s": None, "swap_percent": 93.0,
         "swap_activity_ps": 0.0, "io_busy_percent": 0.0},
    )
    text = " ".join(_text(opt) for opt in kb.options_for(METRIC_STALL, event=event))
    assert "a carga de paginacao esta em 93%" in text
    assert "por segundo" not in text


def test_disk_only_episode_cites_the_disk_and_nothing_else():
    event = _stall_event(
        [SIGNAL_DISK_SATURATED],
        {"sleep_s": None, "interval_s": None, "swap_percent": 0.0,
         "swap_activity_ps": 0.0, "io_busy_percent": 97.5},
    )
    text = " ".join(_text(opt) for opt in kb.options_for(METRIC_STALL, event=event))
    assert "o disco passou 97.5% do tempo em I/O" in text
    assert "carga de paginacao" not in text


def test_evidence_falls_back_to_the_sustained_culprit():
    """Um episodio so existe com candidato sustentado: sem numero aproveitavel
    na linha, a frase ainda aponta o que foi medido, e nao fica com buraco."""
    event = _stall_event([SIGNAL_THRASHING], {"swap_percent": 0.0})
    text = _text(kb.options_for(METRIC_STALL, event=event)[0])
    assert "chrome ficou em critico sustentado" in text
    assert "{evidence}" not in text

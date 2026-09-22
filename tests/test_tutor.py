from __future__ import annotations

import contextlib
import json
from unittest.mock import patch

from conftest import make_sample, proc

from sentinel import kb, kbstore, tutor
from sentinel.detector import METRIC_CPU, METRIC_RAM, SEV_WARNING, Finding
from sentinel.incidents import METRIC_APP_FAILURE, METRIC_ORPHAN_TREE
from sentinel.events import (
    OUTCOME_DISMISSED,
    OUTCOME_FIXED,
    OUTCOME_NOT_FIXED,
    STATUS_DISMISSED,
    STATUS_RESOLVED,
    EventStore,
)


def _event(tmp_path, metric=METRIC_CPU):
    store = EventStore(tmp_path / "events.jsonl")
    finding = Finding(
        metric=metric,
        severity=SEV_WARNING,
        value=90.0,
        threshold=85.0,
        samples=5,
        span_s=10.0,
        top_processes=[proc(11, "app")],
        fingerprint=f"{metric}:warning:app",
    )
    event = store.record_finding(finding, make_sample())
    return store, event


OPTS = [
    {"title": "Fecha o app", "steps": ["p1"]},
    {"title": "Reinicia", "steps": ["p2"]},
    {"title": "Investiga leak", "steps": ["p3"]},
]


def test_validate_yes_first_option(tmp_path):
    store, event = _event(tmp_path)
    outcome = tutor.run_cycle(
        event,
        store,
        interactive=True,
        options=OPTS,
        source="kb",
        validate=lambda: tutor.RESPONSE_FIXED,
        echo=lambda *a: None,
    )
    assert outcome.outcome == OUTCOME_FIXED
    assert outcome.option_index == 0
    assert outcome.source == "kb"

    assert store.find(event["id"])["status"] == STATUS_RESOLVED
    res = store.resolutions_for(event["id"])[0]
    assert res["outcome"] == OUTCOME_FIXED
    assert res["option_index"] == 0


def test_cycle_advances_on_no_then_fixes(tmp_path):
    store, event = _event(tmp_path)
    responses = iter(
        [tutor.RESPONSE_NEXT, tutor.RESPONSE_NEXT, tutor.RESPONSE_FIXED]
    )
    outcome = tutor.run_cycle(
        event,
        store,
        interactive=True,
        options=OPTS,
        source="modelo",
        validate=lambda: next(responses),
        echo=lambda *a: None,
    )
    assert outcome.outcome == OUTCOME_FIXED
    assert outcome.option_index == 2
    assert outcome.tried == 3


def test_exhausted_records_not_fixed(tmp_path):
    store, event = _event(tmp_path)
    outcome = tutor.run_cycle(
        event,
        store,
        interactive=True,
        options=OPTS,
        source="kb",
        validate=lambda: tutor.RESPONSE_NEXT,  # nunca resolve
        echo=lambda *a: None,
    )
    assert outcome.outcome == OUTCOME_NOT_FIXED
    assert outcome.option_index is None
    assert outcome.tried == len(OPTS)
    # Esgotado marca dismissed (nao fica open pra sempre).
    assert store.find(event["id"])["status"] == STATUS_DISMISSED


def test_dismiss_mid_cycle(tmp_path):
    store, event = _event(tmp_path)
    responses = iter([tutor.RESPONSE_NEXT, tutor.RESPONSE_DISMISS])
    outcome = tutor.run_cycle(
        event,
        store,
        interactive=True,
        options=OPTS,
        source="kb",
        validate=lambda: next(responses),
        echo=lambda *a: None,
    )
    assert outcome.outcome == OUTCOME_DISMISSED
    assert outcome.option_index == 1


def test_non_interactive_presents_only(tmp_path):
    store, event = _event(tmp_path)
    lines = []
    outcome = tutor.run_cycle(
        event,
        store,
        interactive=False,
        options=OPTS,
        source="kb",
        echo=lambda *a: lines.append(a),
    )
    # Sem tty: nao bloqueia, nao grava resolucao, so mostra.
    assert outcome.wrote_resolution is False
    assert event["id"]
    assert store.find(event["id"])["status"] == "open"
    assert len(lines) >= len(OPTS)


def test_kill_action_offers_execute(tmp_path):
    store, event = _event(tmp_path)

    calls = {"kill": 0}

    class FakeCtl:
        def kill_tree(self, pid, *, interactive):
            calls["kill"] += 1
            from sentinel.processctl import KillResult

            return KillResult(killed=[pid])

    kill_opt = {
        "title": "Mata topo",
        "steps": ["x"],
        "action": {"type": "kill_top_process"},
    }
    with patch_confirm(True):
        outcome = tutor.run_cycle(
            event,
            store,
            interactive=True,
            ctl=FakeCtl(),
            options=[kill_opt],
            source="modelo",
            validate=lambda: tutor.RESPONSE_FIXED,
            echo=lambda *a: None,
        )
    assert outcome.outcome == OUTCOME_FIXED
    # kill foi oferecido e, com confirm=True, executado uma vez.
    assert calls["kill"] == 1


def test_kill_skips_protected_and_picks_real_target(tmp_path):
    # top_processes com idle(0), svchost protegido e um app real: o ciclo
    # deve escolher o app matavel (pid 99), nunca pid 0 nem svchost.
    store, _ = _event(tmp_path)
    event = {
        "id": "evt-x",
        "metric": METRIC_CPU,
        "severity": SEV_WARNING,
        "value": 90.0,
        "threshold": 85.0,
        "window": {"samples": 5, "span_s": 10.0},
        "top_processes": [
            {"pid": 0, "name": "System Idle Process"},
            {"pid": 4, "name": "svchost.exe"},
            {"pid": 99, "name": "chrome"},
        ],
    }
    seen = {}

    class FakeCtl:
        def kill_tree(self, pid, *, interactive):
            seen["pid"] = pid
            from sentinel.processctl import KillResult

            return KillResult(killed=[pid])

    kill_opt = {"title": "Mata topo", "steps": ["x"], "action": {"type": "kill_top_process"}}
    with patch_confirm(True):
        outcome = tutor.run_cycle(
            event,
            store,
            interactive=True,
            ctl=FakeCtl(),
            options=[kill_opt],
            source="modelo",
            validate=lambda: tutor.RESPONSE_FIXED,
            echo=lambda *a: None,
        )
    assert seen["pid"] == 99
    assert outcome.outcome == OUTCOME_FIXED


def test_kill_no_target_when_all_protected(tmp_path):
    store, _ = _event(tmp_path)
    event = {
        "id": "evt-y",
        "metric": METRIC_CPU,
        "severity": SEV_WARNING,
        "value": 90.0,
        "threshold": 85.0,
        "window": {"samples": 5, "span_s": 10.0},
        "top_processes": [{"pid": 4, "name": "lsass.exe"}],
    }
    called = {"n": 0}

    class BoomCtl:
        def kill_tree(self, *a, **k):
            called["n"] += 1
            raise AssertionError("nao deveria tentar matar protegido")

    kill_opt = {"title": "Mata topo", "steps": ["x"], "action": {"type": "kill_top_process"}}
    outcome = tutor.run_cycle(
        event,
        store,
        interactive=True,
        ctl=BoomCtl(),
        options=[kill_opt],
        source="modelo",
        validate=lambda: tutor.RESPONSE_FIXED,
        echo=lambda *a: None,
    )
    assert called["n"] == 0
    # Ainda assim o usuario pode validar a solucao (tutorial) sem matar nada.
    assert outcome.outcome == OUTCOME_FIXED


def test_build_prompt_lists_top_processes(tmp_path):
    _store, event = _event(tmp_path)
    prompt = tutor.build_prompt(event)
    assert "pid=11" in prompt
    assert "app" in prompt
    assert METRIC_CPU in prompt


# --------------------------------------------------------------------------
# anomalia de incidente (schema 2): o prompt nao tem limiar, tem fatos
# --------------------------------------------------------------------------
def _incident_event(**over):
    event = {
        "schema": 2,
        "id": "evt-20260922-101500-abcd",
        "kind": "anomaly",
        "metric": METRIC_APP_FAILURE,
        "severity": SEV_WARNING,
        "status": "open",
        "label": "Genesis.exe parou de funcionar (excecao 0xc0000005 em nvgpucomp64.dll)",
        "detail": {
            "kind": "crash",
            "app": "Genesis.exe",
            "app_version": "1.0.0.0",
            "module": "nvgpucomp64.dll",
            "exception_code": "0xc0000005",
            "pid": 15116,
            "at": "2026-09-22T10:15:32.388546+00:00",
        },
        "fingerprint": "app_failure:warning:genesis.exe",
        "occurrences": 3,
    }
    event.update(over)
    return event


def test_incident_prompt_carries_facts_and_admits_no_threshold():
    prompt = tutor.build_prompt(_incident_event())
    assert "Genesis.exe" in prompt
    assert "0xc0000005" in prompt and "nvgpucomp64.dll" in prompt
    # Não se finge de pico: as lacunas de limiar dizem "não se aplica".
    assert "Valor atual: (nao se aplica" in prompt
    assert "Fatos medidos neste incidente" in prompt
    # O loop de queda é o dado que muda a sugestão.
    assert "Ja aconteceu 3 vezes" in prompt


def test_incident_prompt_maps_the_orphan_tree():
    event = _incident_event(
        metric=METRIC_ORPHAN_TREE,
        label="setup.exe (pid 100) saiu deixando 1 processo(s) vivo(s)",
        detail={
            "parent": {"pid": 100, "name": "setup.exe"},
            "orphans": [{"pid": 200, "ppid": 100, "name": "helper.exe", "depth": 1}],
            "tree": [{"pid": 200, "ppid": 100, "name": "helper.exe", "depth": 1}],
            "orphan_count": 1,
            "tree_size": 1,
        },
        occurrences=1,
    )
    prompt = tutor.build_prompt(event)
    assert "Pai que morreu: setup.exe (pid 100)" in prompt
    assert "Sobreviveu: pid 200 helper.exe" in prompt
    assert "Ja aconteceu" not in prompt  # occurrences==1 nao e loop


def test_finding_prompt_is_untouched_by_the_incident_block(tmp_path):
    _store, event = _event(tmp_path)
    prompt = tutor.build_prompt(event)
    assert "Fatos medidos neste incidente" not in prompt
    assert "Valor atual: 90.0" in prompt


def test_propose_uses_kb_templates_for_incident_metrics():
    with patch("sentinel.local_model.complete", return_value=None):
        options, source, layer = tutor.propose(_incident_event())
    assert source == kbstore.LAYER_NAME[kbstore.LAYER_METRIC]
    assert layer == kbstore.LAYER_METRIC
    assert options and len(options) <= 3
    for option in options:
        assert option["steps"]
        # Sem top_processes no evento, oferecer kill seria promessa vazia.
        assert option.get("action") is None


# ---------------------------------------------------------------------------
# Fase B: a base local responde antes do modelo, e o modelo ensina a base
# ---------------------------------------------------------------------------


def _finding_event(
    metric=METRIC_RAM,
    severity="critical",
    name="chrome",
    pid=1234,
    rss=3200.0,
    value=96.0,
    threshold=80.0,
):
    """Evento de limiar cru, como sai do EventStore — o que `kb.bind` e as
    camadas da base leem."""
    return {
        "schema": 2,
        "id": f"evt-fase-b-{metric}-{name}",
        "kind": "anomaly",
        "metric": metric,
        "severity": severity,
        "value": value,
        "threshold": threshold,
        "window": {"samples": 5, "span_s": 10.0},
        "top_processes": [
            {"pid": pid, "name": name, "cpu": 4.0, "rss_mb": rss}
        ],
        "status": "open",
        "fingerprint": f"{metric}:{severity}:{name}",
        "occurrences": 1,
    }


def test_propose_asks_the_local_base_before_the_model(tmp_path):
    event = _finding_event()
    with kbstore.open_store(tmp_path / "kb.db") as db:
        with patch("sentinel.local_model.complete") as model:
            options, source, layer = tutor.propose(event, db=db)
    assert model.call_count == 0, (
        "a camada 3 da base ja respondia; nao havia porque chamar um modelo"
    )
    assert layer == kbstore.LAYER_METRIC
    assert source == kbstore.LAYER_NAME[kbstore.LAYER_METRIC]
    assert options


def test_propose_learns_from_the_model_once_the_base_ran_out(tmp_path):
    """A base curada cobre as metricas conhecidas, entao o modelo so e
    chamado quando aquelas opcoes ja foram recusadas — e a resposta dele
    passa a ser morada na base a partir dai."""
    event = _finding_event(metric=METRIC_CPU, name="blender")
    resposta = json.dumps(
        [{"title": "Reduz os workers do blender", "why": "mecanismo",
          "steps": ["passo"], "proof": "o clique responde",
          "risk": "o render demora mais"}]
    )
    with kbstore.open_store(tmp_path / "kb.db") as db:
        curated, _layer = db.lookup(event)
        for option in curated:
            db.record(event, option, outcome=OUTCOME_NOT_FIXED, source="kb:metrica")
        before = db.count_options()
        with patch("sentinel.local_model.complete", return_value=resposta) as model:
            options, source, layer = tutor.propose(event, db=db)
        assert model.call_count == 1
        assert source == "modelo" and layer == kbstore.LAYER_MODEL
        # O que o modelo respondeu agora e morada na base: na segunda vez a
        # resposta sai dali, sem nenhuma inferencia.
        assert db.count_options() > before
        again, again_layer = db.lookup(event)
    assert again_layer == kbstore.LAYER_FINGERPRINT
    assert again[0]["title"] == "Reduz os workers do blender"


def test_run_cycle_records_every_refusal_in_the_base(tmp_path):
    store, event = _event(tmp_path)
    with kbstore.open_store(tmp_path / "kb.db") as db:
        options, source, _layer = tutor.propose(event, db=db)
        with patch_confirm(False):
            outcome = tutor.run_cycle(
                event,
                store,
                interactive=True,
                options=options,
                source=source,
                db=db,
                validate=lambda: tutor.RESPONSE_NEXT,
                echo=lambda *a: None,
            )
        stats = db.stats()
    assert outcome.outcome == OUTCOME_NOT_FIXED
    assert stats["desfechos"] == len(options), (
        "cada opcao recusada deixa um registro — e isso que reordena a "
        "proxima vez"
    )


def test_run_cycle_surfaces_the_ranking_it_used(tmp_path):
    event = _finding_event()
    with kbstore.open_store(tmp_path / "kb.db") as db:
        first_pass = tutor.propose(event, db=db)[0]
        last = first_pass[-1]
        db.record(event, last, outcome=OUTCOME_FIXED, source="kb:metrica")
        second_pass, source, layer = tutor.propose(event, db=db)
    assert second_pass[0]["key"] == last["key"]
    assert source == kbstore.LAYER_NAME[kbstore.LAYER_METRIC]
    assert layer == kbstore.LAYER_METRIC


def test_render_option_states_mechanism_proof_and_risk():
    option = {
        "title": "Encerrar o chrome que segura 3,2 GB",
        "why": "RAM em 94% significa paginacao; liberar RSS devolve o regime.",
        "steps": ["Rode 'sentinel kill 1234'"],
        "proof": "O clique volta a ser imediato.",
        "risk": "Voce perde o estado nao salvo.",
        "reversible": True,
    }
    text = tutor.render_option(option, 1, 2)
    assert "por que: RAM em 94%" in text
    assert "como saber que funcionou: O clique" in text
    assert "risco (reversivel): Voce perde" in text
    assert "[Opcao 1/2]" in text


def test_render_option_marks_an_irreversible_step():
    option = {
        "title": "Esvaziar a Lixeira",
        "why": "Libera os GB marcados como arquivos do sistema.",
        "steps": ["Clique em Esvaziar Lixeira."],
        "proof": "O volume cai abaixo do limiar.",
        "risk": "O que estava la se perde.",
        "reversible": False,
    }
    assert "risco (sem volta)" in tutor.render_option(option, 1, 1)


def test_tokens_are_filled_with_the_measured_numbers():
    option = {
        "title": "Encerrar o {proc} que segura {rss} MB",
        "why": "{value}% de RAM do sistema.",
        "steps": ["Rode 'sentinel kill {pid}'"],
        "proof": "RAM abaixo de {threshold}%.",
        "risk": "Perda de estado do {proc}.",
    }
    bound = kb.bind(option, _finding_event(name="chrome", pid=1234, rss=3200.0))
    assert bound["title"] == "Encerrar o chrome que segura 3200 MB"
    assert bound["steps"] == ["Rode 'sentinel kill 1234'"]
    assert bound["why"] == "96% de RAM do sistema."
    assert bound["proof"] == "RAM abaixo de 80%."


def test_bind_leaves_unknown_and_broken_braces_alone():
    option = {"title": "Rode 'echo {nao_existe} e json {}'", "steps": ["x"]}
    bound = kb.bind(option, _finding_event())
    assert "{nao_existe}" in bound["title"]
    assert "{}" in bound["title"]


# helper pra patchar confirm dentro de OFFER_EXECUTE sem tty real
@contextlib.contextmanager
def patch_confirm(value):
    with patch("sentinel.system.prompt.confirm", return_value=value):
        yield

from __future__ import annotations

import datetime
import json

from conftest import make_sample, proc

from sentinel import relief, settings
from sentinel.detector import METRIC_CPU, SEV_WARNING, Finding
from sentinel.incidents import METRIC_APP_FAILURE, Incident
from sentinel.events import (
    OUTCOME_FIXED,
    STATUS_DISMISSED,
    STATUS_RESOLVED,
    EventStore,
)


def _finding(fingerprint="cpu:warning:app", value=90.0, metric=METRIC_CPU):
    return Finding(
        metric=metric,
        severity=SEV_WARNING,
        value=value,
        threshold=85.0,
        samples=5,
        span_s=10.0,
        top_processes=[proc(11, "app")],
        fingerprint=fingerprint,
    )


def _ts(day=21, minute=0):
    return datetime.datetime(
        2026, 9, day, 12, minute, 0, tzinfo=datetime.timezone.utc
    )


def test_record_finding_creates_open_anomaly(tmp_path):
    store = EventStore(tmp_path / "events.jsonl")
    sample = make_sample(cpu=90, ts=_ts())
    event = store.record_finding(_finding(), sample)

    assert event["kind"] == "anomaly"
    assert event["status"] == "open"
    assert event["metric"] == "cpu"
    assert event["occurrences"] == 1
    assert event["schema"] == settings.EVENT_SCHEMA_VERSION
    assert event["top_processes"][0]["pid"] == 11

    # Persistiu como JSONL e re-le de disco.
    again = store.find(event["id"])
    assert again == event


def test_dedupe_collapses_same_fingerprint_within_window(tmp_path):
    store = EventStore(tmp_path / "events.jsonl")
    first = store.record_finding(_finding(), make_sample(ts=_ts(minute=0)))
    second = store.record_finding(
        _finding(value=93.0), make_sample(ts=_ts(minute=2))
    )

    # Mesmo fingerprint, 2 min depois (< DEDUPE_WINDOW_S 300s): uma linha.
    assert first["id"] == second["id"]
    assert second["occurrences"] == 2
    assert second["value"] == 93.0
    assert len(store.anomalies()) == 1


def test_dedupe_does_not_collapse_outside_window(tmp_path):
    store = EventStore(tmp_path / "events.jsonl")
    a = store.record_finding(_finding(), make_sample(ts=_ts(minute=0)))
    b = store.record_finding(_finding(), make_sample(ts=_ts(minute=10)))

    # 10 min > janela de 5 min: sao duas anomalias separadas.
    assert a["id"] != b["id"]
    assert len(store.anomalies()) == 2


def test_latest_open_and_open_anomalies(tmp_path):
    store = EventStore(tmp_path / "events.jsonl")
    store.record_finding(_finding(), make_sample(ts=_ts(minute=0)))
    latest = store.record_finding(
        _finding(fingerprint="cpu:warning:other"), make_sample(ts=_ts(minute=1))
    )

    assert store.latest_open()["id"] == latest["id"]
    assert len(store.open_anomalies()) == 2


def test_resolution_links_and_closes(tmp_path):
    store = EventStore(tmp_path / "events.jsonl")
    event = store.record_finding(_finding(), make_sample(ts=_ts()))

    store.append_resolution(
        ref=event["id"],
        outcome=OUTCOME_FIXED,
        option_index=0,
        source="modelo",
        note="ok",
    )

    reloaded = store.find(event["id"])
    assert reloaded["status"] == STATUS_RESOLVED
    resolutions = store.resolutions_for(event["id"])
    assert len(resolutions) == 1
    assert resolutions[0]["outcome"] == "fixed"
    assert resolutions[0]["ref"] == event["id"]
    # Agora nao esta mais aberta.
    assert store.latest_open() is None


def test_set_status(tmp_path):
    store = EventStore(tmp_path / "events.jsonl")
    event = store.record_finding(_finding(), make_sample(ts=_ts()))
    assert store.set_status(event["id"], "addressing") is True
    assert store.find(event["id"])["status"] == "addressing"


def test_prune_drops_old_lines(tmp_path):
    store = EventStore(tmp_path / "events.jsonl")
    ancient = datetime.datetime(2000, 1, 1, tzinfo=datetime.timezone.utc)
    now = datetime.datetime.now(datetime.timezone.utc)
    store.record_finding(
        _finding(fingerprint="cpu:warning:old1"), make_sample(ts=ancient)
    )
    store.record_finding(
        _finding(fingerprint="cpu:warning:old2"),
        make_sample(ts=ancient + datetime.timedelta(minutes=1)),
    )
    kept = store.record_finding(
        _finding(fingerprint="cpu:warning:new"), make_sample(ts=now)
    )

    # prune usa utcnow real: datas de 2000 caem fora de qualquer janela
    # razoavel; o evento 'agora' sobrevive. Deterministico em qualquer host.
    dropped = store.prune(older_than_days=30)
    assert dropped == 2
    remaining = store.anomalies()
    assert len(remaining) == 1
    assert remaining[0]["id"] == kept["id"]


def test_corrupt_line_is_skipped(tmp_path):
    path = tmp_path / "events.jsonl"
    store = EventStore(path)
    event = store.record_finding(_finding(), make_sample(ts=_ts()))
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write("{ isto nao e json valido }\n")

    events = store.all()
    assert len(events) == 1
    assert events[0]["id"] == event["id"]


# --------------------------------------------------------------------------
# schema 2: anomalias de incidente (arvore órfã, queda de app)
# --------------------------------------------------------------------------
def _incident(fingerprint="app_failure:warning:genesis.exe", app="Genesis.exe"):
    return Incident(
        metric=METRIC_APP_FAILURE,
        severity=SEV_WARNING,
        detail={
            "kind": "crash",
            "app": app,
            "exception_code": "0xc0000005",
            "module": "nvgpucomp64.dll",
            "pid": 15116,
        },
        fingerprint=fingerprint,
        label=f"{app} parou de funcionar (excecao 0xc0000005)",
    )


def test_record_incident_has_no_threshold_shape(tmp_path):
    store = EventStore(tmp_path / "events.jsonl")
    event = store.record_incident(_incident(), now=_ts())

    assert event["kind"] == "anomaly"
    assert event["status"] == "open"
    assert event["schema"] == settings.EVENT_SCHEMA_VERSION
    assert event["metric"] == METRIC_APP_FAILURE
    # Unifica com as finding de limiar no MESMO histórico...
    assert event["id"] in [a["id"] for a in store.anomalies()]
    # ...mas não inventa número pra caber no molde velho.
    assert "value" not in event and "threshold" not in event
    assert event["detail"]["module"] == "nvgpucomp64.dll"
    assert "parou de funcionar" in event["label"]
    assert store.find(event["id"]) == event


def test_incident_dedupe_counts_the_crash_loop(tmp_path):
    store = EventStore(tmp_path / "events.jsonl")
    first = store.record_incident(_incident(), now=_ts(minute=0))
    second = store.record_incident(_incident(), now=_ts(minute=1))

    # Quatro quedas do mesmo app em minutos sao UMA anomalia com ocorrências:
    # a contagem é o que separa 'hoje quebrou' de 'está em loop'.
    assert first["id"] == second["id"]
    assert second["occurrences"] == 2
    assert len(store.anomalies()) == 1

    other = store.record_incident(
        _incident(fingerprint="app_failure:warning:other.exe", app="Other.exe"),
        now=_ts(minute=2),
    )
    assert other["id"] != first["id"]
    assert len(store.anomalies()) == 2


def test_incident_and_finding_share_the_status_cycle(tmp_path):
    store = EventStore(tmp_path / "events.jsonl")
    event = store.record_incident(_incident(), now=_ts())
    assert store.latest_open()["id"] == event["id"]

    store.append_resolution(
        ref=event["id"],
        outcome=OUTCOME_FIXED,
        option_index=0,
        source="kb",
        note="usuario validou solucao",
    )
    assert store.find(event["id"])["status"] == STATUS_RESOLVED
    assert store.latest_open() is None


def test_reader_tolerates_schema_1_lines_alongside_schema_2(tmp_path):
    path = tmp_path / "events.jsonl"
    store = EventStore(path)
    old = store.record_finding(_finding(), make_sample(ts=_ts()))

    # Reescreve a linha gravada como se viesse do disco de antes do v2,
    # exatamente como quem atualhou o Sentinel sem apagar .sentinel/.
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    for line in lines:
        if line["id"] == old["id"]:
            line["schema"] = 1
    path.write_text(
        "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines),
        encoding="utf-8",
    )

    new = store.record_incident(_incident(), now=_ts(minute=5))

    ids = [e["id"] for e in store.anomalies()]
    assert old["id"] in ids and new["id"] in ids
    assert store.find(old["id"])["schema"] == 1
    assert store.open_anomalies()[0]["id"] == old["id"]


# -- a linha do alivio ------------------------------------------------------


def _result(**kwargs):
    base = dict(
        action=relief.ACTION_LOWER,
        reason=relief.OK,
        pid=4242,
        name="chrome",
        from_level="normal",
        to_level="abaixo-do-normal",
        from_raw=32,
        to_raw=16384,
        ref="evt-20260922-120000-abcd",
    )
    base.update(kwargs)
    return relief.ReliefResult(**base)


def test_record_intervention_is_its_own_kind(tmp_path):
    """Uma intervencao nao e um problema, e a resposta a um: misturar as duas
    coisas no mesmo `kind` faria o historico contar como anomalia o que o
    proprio Sentinel fez."""
    store = EventStore(tmp_path / "events.jsonl")
    event = store.record_intervention(_result(), now=_ts())

    assert event["kind"] == "intervention"
    assert event["id"].startswith("int-")
    assert event["applied"] is True
    assert event["shadow"] is False
    assert event["ref"] == "evt-20260922-120000-abcd"
    assert event["metric"] == relief.ACTION_LOWER
    assert event["label"].startswith("FEZ chrome (pid 4242)")
    assert event["detail"]["priority"]["from_raw"] == 32
    assert store.find(event["id"]) == event


def test_interventions_are_never_deduped(tmp_path):
    """A segunda intervencao no mesmo app nao e a primeira repetida: e um fato
    novo, com consequencia nova. O que limita a frequencia sao as guardas do
    `relief`, nao o armazenamento."""
    store = EventStore(tmp_path / "events.jsonl")
    store.record_intervention(_result(), now=_ts())
    store.record_intervention(_result(), now=_ts(minute=1))

    assert len(store.interventions()) == 2


def test_anomalies_and_interventions_stay_in_their_lanes(tmp_path):
    """Os filtros de anomalia (`open_anomalies`, `latest_open`) continuam
    achando uma abertura no meio de um historico cheio de intervencoes -- e o
    dedupe nao colapsa nada com a linha do alivio no caminho."""
    store = EventStore(tmp_path / "events.jsonl")
    first = store.record_finding(_finding(), make_sample(ts=_ts()))
    store.record_intervention(_result(), now=_ts(minute=1))
    again = store.record_finding(_finding(value=95.0), make_sample(ts=_ts(minute=2)))

    assert first["id"] == again["id"]
    assert [e["id"] for e in store.anomalies()] == [first["id"]]
    assert len(store.interventions()) == 1
    assert store.latest_open()["id"] == first["id"]


def test_shadow_decision_is_recorded_as_not_applied(tmp_path):
    """O sombra so tem valor se cair no historico: `applied: False` com a
    decisao escrita e a prova do que o Sentinel faria."""
    store = EventStore(tmp_path / "events.jsonl")
    event = store.record_intervention(
        _result(reason=relief.SKIP_SHADOW, shadow=True), now=_ts()
    )

    assert event["applied"] is False
    assert event["shadow"] is True
    assert event["label"].startswith("SERIA ")


def test_prune_takes_the_interventions_with_the_anomalies(tmp_path):
    """Vida util compartilhada: apagar o historico velho nao pode deixar pra
    tras justamente as linhas que dizem o que foi feito na maquina."""
    path = tmp_path / "events.jsonl"
    store = EventStore(path)
    store.record_finding(_finding(), make_sample(ts=_ts()))
    store.record_intervention(_result(), now=_ts())
    old = "2020-01-01T00:00:00+00:00"
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    for line in lines:
        line["ts"] = old
    path.write_text(
        "\n".join(json.dumps(line, ensure_ascii=False) for line in lines) + "\n",
        encoding="utf-8",
    )

    assert store.prune(older_than_days=30) == 2
    assert store.anomalies() == []
    assert store.interventions() == []

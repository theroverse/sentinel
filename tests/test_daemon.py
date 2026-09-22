from __future__ import annotations

from conftest import make_sample, proc

from sentinel import daemon, settings
from sentinel.events import EventStore


class FakeSensor:
    """Devolve sempre a mesma amostra 'quente', pra o detector acumular a
    serie sustained sem depender de wall-clock nem de psutil."""

    def __init__(self, **over):
        self._over = over

    def sample(self, *, top=True):
        base = dict(cpu=99.0, ram=50.0, disk=50.0, io=10.0)
        base.update(self._over)
        return make_sample(top_cpu=[proc(1, "burn")], top_mem=[proc(1, "burn")], **base)


def test_run_watch_loop_persists_anomaly(tmp_path):
    paths = settings.paths_for(tmp_path)
    store = EventStore(paths.events)

    ticks = daemon.run_watch_loop(
        paths,
        sensor=FakeSensor(),
        store=store,
        sleep=lambda _s: None,
        stop_after=settings.MIN_SAMPLES_BEFORE_DETECT + 5,
    )

    assert ticks == settings.MIN_SAMPLES_BEFORE_DETECT + 5
    anomalies = store.anomalies()
    assert anomalies, "nenhuma anomalia gravada apesar de CPU em 99%"
    assert any(a["metric"] == "cpu" for a in anomalies)


def test_run_watch_loop_writes_heartbeat_log(tmp_path):
    paths = settings.paths_for(tmp_path)
    daemon.run_watch_loop(
        paths,
        sensor=FakeSensor(cpu=5.0),
        store=EventStore(paths.events),
        sleep=lambda _s: None,
        stop_after=3,
    )
    log = paths.daemon_log.read_text(encoding="utf-8")
    assert "tick" in log
    assert "cpu=5.0" in log


def test_run_watch_loop_dedupes_repeated_finding(tmp_path):
    paths = settings.paths_for(tmp_path)
    store = EventStore(paths.events)
    daemon.run_watch_loop(
        paths,
        sensor=FakeSensor(),
        store=store,
        sleep=lambda _s: None,
        stop_after=settings.MIN_SAMPLES_BEFORE_DETECT + 10,
    )
    # CPU 99 continuo gera MUITOS findings, mas um unico evento de cpu
    # (dedupe por fingerprint colapsa na janela).
    cpu_events = [a for a in store.anomalies() if a["metric"] == "cpu"]
    assert len(cpu_events) == 1
    assert cpu_events[0]["occurrences"] > 1


def test_status_reports_not_running_without_pidfile(tmp_path):
    paths = settings.paths_for(tmp_path)
    st = daemon.status(paths)
    assert st.running is False
    assert st.pid is None


# --------------------------------------------------------------------------
# incidentes no ciclo (arvore órfã + falha de app)
# --------------------------------------------------------------------------
class FakeIncidentSource:
    """Imita TreeMonitor/AppFailureReader: devolve incidentes uma vez e
    depois fica mudo (como os originais, que deduplicam por dentro)."""

    def __init__(self, incidents):
        self._pending = list(incidents)
        self.seen_times = []

    def observe(self, now=None):
        self.seen_times.append(now)
        if not self._pending:
            return []
        return [self._pending.pop(0)]


def _orphan_incident():
    from sentinel.incidents import METRIC_ORPHAN_TREE, Incident

    return Incident(
        metric=METRIC_ORPHAN_TREE,
        severity="info",
        detail={
            "parent": {"pid": 100, "name": "setup.exe"},
            "orphans": [{"pid": 200, "ppid": 100, "name": "helper.exe", "depth": 1}],
            "orphan_count": 1,
            "tree": [{"pid": 200, "ppid": 100, "name": "helper.exe", "depth": 1}],
            "tree_size": 1,
        },
        fingerprint="orphan_tree:info:setup.exe",
        label="setup.exe (pid 100) saiu deixando 1 processo(s) vivo(s) na arvore",
    )


def test_run_watch_loop_defaults_to_no_incident_sources(tmp_path):
    # O loop puro nao varre processo nem lanca wevtutil por conta propria:
    # quem quer isso passa `incident_sources` explicito (build_incident_sources).
    paths = settings.paths_for(tmp_path)
    daemon.run_watch_loop(
        paths,
        sensor=FakeSensor(cpu=5.0),
        store=EventStore(paths.events),
        sleep=lambda _s: None,
        stop_after=3,
    )
    assert EventStore(paths.events).anomalies() == []


def test_run_watch_loop_records_incident_from_source(tmp_path):
    paths = settings.paths_for(tmp_path)
    store = EventStore(paths.events)
    source = FakeIncidentSource([_orphan_incident()])

    daemon.run_watch_loop(
        paths,
        sensor=FakeSensor(cpu=5.0),
        store=store,
        incident_sources=[source],
        sleep=lambda _s: None,
        stop_after=2,
    )

    anomalies = store.anomalies()
    assert len(anomalies) == 1
    assert anomalies[0]["metric"] == "orphan_tree"
    assert anomalies[0]["detail"]["parent"]["pid"] == 100
    # O monitor recebe o relógio da amostra, não um utcnow paralelo: o
    # histórico inteiro fala do mesmo instante.
    assert source.seen_times[0] == source.seen_times[1]
    log = paths.daemon_log.read_text(encoding="utf-8")
    assert "ANOMALIA orphan_tree info" in log
    assert ":: setup.exe (pid 100)" in log


def test_broken_incident_source_does_not_stop_the_loop(tmp_path):
    class Exploding:
        def observe(self, now=None):
            raise OSError("AccessDenied no meio do snapshot")

    paths = settings.paths_for(tmp_path)
    store = EventStore(paths.events)
    silent = _SilentSource()
    ticks = daemon.run_watch_loop(
        paths,
        sensor=FakeSensor(),
        store=store,
        incident_sources=[Exploding(), silent],
        sleep=lambda _s: None,
        stop_after=settings.MIN_SAMPLES_BEFORE_DETECT + 2,
    )

    # Um processo que sumiu entre listar e ler nao derruba a vigilancia de
    # CPU: o tick seguinte continua, e o segundo monitor ainda é consultado.
    assert ticks == settings.MIN_SAMPLES_BEFORE_DETECT + 2
    assert silent.calls == ticks
    assert any(a["metric"] == "cpu" for a in store.anomalies())


class _SilentSource:
    def __init__(self):
        self.calls = 0

    def observe(self, now=None):
        self.calls += 1
        return []

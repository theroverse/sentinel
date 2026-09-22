from __future__ import annotations

import datetime

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
# Kill-switch sem GUI: `.sentinel/paused`
# --------------------------------------------------------------------------
def test_pause_resume_roundtrip(tmp_path):
    paths = settings.paths_for(tmp_path)
    assert daemon.is_paused(paths) is False
    assert daemon.resume(paths) is False, "retomar sem pausa nao pode fingir sucesso"

    daemon.pause(paths, now=datetime.datetime(2026, 9, 22, 12, 0, tzinfo=datetime.timezone.utc))
    assert daemon.is_paused(paths) is True
    assert daemon.paused_since(paths) == datetime.datetime(
        2026, 9, 22, 12, 0, tzinfo=datetime.timezone.utc
    )

    assert daemon.resume(paths) is True
    assert daemon.is_paused(paths) is False
    assert daemon.paused_since(paths) is None


def test_paused_since_is_lenient(tmp_path):
    """O conteudo e diagnostico; a pausa vale pela existencia do arquivo. Um
    arquivo vazio ou escrito na mao continua pausado — so sem data."""
    paths = settings.paths_for(tmp_path)
    paths.ensure_output_dir()

    paths.paused.write_text("", encoding="utf-8")
    assert daemon.is_paused(paths) is True
    assert daemon.paused_since(paths) is None

    paths.paused.write_text("nao sou um iso", encoding="utf-8")
    assert daemon.is_paused(paths) is True
    assert daemon.paused_since(paths) is None


def test_pause_survives_a_dead_daemon(tmp_path):
    """O interruptor mora num arquivo, nao na cabeca do processo: e isso que
    faz pausar sem GUI funcionar depois de um reboot."""
    paths = settings.paths_for(tmp_path)
    daemon.pause(paths)
    paths.pid.write_text("999999999", encoding="utf-8")  # pidfile obsoleto

    st = daemon.status(paths)
    assert st.running is False
    assert st.paused is True


def test_run_watch_loop_pauses_recording_but_keeps_sampling(tmp_path):
    paths = settings.paths_for(tmp_path)
    store = EventStore(paths.events)
    daemon.pause(paths)

    ticks = daemon.run_watch_loop(
        paths,
        sensor=FakeSensor(),
        store=store,
        sleep=lambda _s: None,
        stop_after=settings.MIN_SAMPLES_BEFORE_DETECT + 5,
    )

    # CPU em 99% o ciclo inteiro, e nenhuma linha de anomalia: pausado e
    # isso. O batimento continua (com paused=1) — senao `status` nao
    # distinguiria 'pausado' de 'morto'.
    assert ticks == settings.MIN_SAMPLES_BEFORE_DETECT + 5
    assert store.anomalies() == []
    log = paths.daemon_log.read_text(encoding="utf-8")
    assert "VIGILANCIA PAUSADO" in log
    assert "paused=1" in log
    assert "ANOMALIA" not in log


def test_run_watch_loop_resumes_mid_flight(tmp_path):
    """Retomar no meio do ciclo tem de voltar a registrar sem reiniciar o
    daemon — e o detector continua acumulando enquanto pausado, entao a
    anomalia que ja estava la e gravada no primeiro tick livre."""
    paths = settings.paths_for(tmp_path)
    store = EventStore(paths.events)
    daemon.pause(paths)

    calls = {"n": 0}

    def resume_on_third_tick(_seconds):
        calls["n"] += 1
        if calls["n"] == 3:
            daemon.resume(paths)

    daemon.run_watch_loop(
        paths,
        sensor=FakeSensor(),
        store=store,
        sleep=resume_on_third_tick,
        stop_after=settings.MIN_SAMPLES_BEFORE_DETECT + 5,
    )

    log = paths.daemon_log.read_text(encoding="utf-8")
    assert calls["n"] >= 3, "o loop mal chegou ao tick da retomada"
    assert "VIGILANCIA ATIVO" in log
    assert log.index("VIGILANCIA PAUSADO") < log.index("VIGILANCIA ATIVO")
    assert any(a["metric"] == "cpu" for a in store.anomalies()), \
        "retomou e continuou mudo"


def test_pause_transition_is_logged_once(tmp_path):
    paths = settings.paths_for(tmp_path)
    daemon.pause(paths)
    daemon.run_watch_loop(
        paths,
        sensor=FakeSensor(cpu=5.0),
        store=EventStore(paths.events),
        sleep=lambda _s: None,
        stop_after=6,
    )
    log = paths.daemon_log.read_text(encoding="utf-8")
    # Seis ticks, uma linha de estado: o log nao pode virar spam do switch.
    assert log.count("VIGILANCIA PAUSADO") == 1


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


# -- estagnacao: o loop medindo, encurtando e registrando ------------------


class ScriptedSensor:
    """Amostras em ordem; a ultima se repete quando a fila acaba, pra o loop
    poder rodar mais ticks do que itens."""

    def __init__(self, samples):
        self._samples = list(samples)

    def sample(self, *, top=True):
        if len(self._samples) > 1:
            return self._samples.pop(0)
        return self._samples[0]


class SlowSleep:
    """`sleep` que cobra caro: a maquina nao escalou o daemon no tempo pedido.

    `over` e o fator de esticada (3.0 = pedir 2,0 s e acordar 6,0 s depois); o
    par `sleep`/`clock` devolve exatamente isso ao loop como duracao real do
    cochilo. `flip_after` sao os cochilos depois dos quais a maquina volta a
    respirar — e como fechar um episodio sem esperar relogio de verdade.
    `asked` guarda o intervalo que o loop pediu em cada volta.
    """

    def __init__(self, *, over: float = 3.0, flip_after: int | None = None):
        self.over = over
        self.flip_after = flip_after
        self.now = 0.0
        self.asked: list = []

    def sleep(self, seconds):
        self.asked.append(seconds)
        self.now += seconds * self.over
        if self.flip_after is not None and len(self.asked) >= self.flip_after:
            self.over = 1.0

    def clock(self) -> float:
        return self.now


def hot_ticks(n, *, swap_rate=400.0):
    """`n` ciclos de maquina paginando, com um culpado no topo da RAM."""
    return [
        make_sample(
            cpu=99.0,
            ram=97.0,
            disk=50.0,
            io=10.0,
            swap_rate=swap_rate,
            top_cpu=[proc(1, "burn")],
            top_mem=[proc(1, "burn")],
        )
        for _ in range(n)
    ]


def cool_ticks(n):
    return hot_ticks(n, swap_rate=0.0)


def test_run_watch_loop_records_the_stall_incident(tmp_path):
    """O travamento vira linha no historico, com os numeros medidos dentro.

    CPU em 99% sozinho ja e gravado (fase anterior); aqui entra o segundo
    tipo de evidencia — o daemon pedindo 2 s e acordando 6 s depois.
    """
    paths = settings.paths_for(tmp_path)
    store = EventStore(paths.events)
    sleeper = SlowSleep(over=3.0)

    daemon.run_watch_loop(
        paths,
        sensor=ScriptedSensor(hot_ticks(24)),
        store=store,
        sleep=sleeper.sleep,
        clock=sleeper.clock,
        interval=settings.SAMPLE_INTERVAL_S,
        stop_after=20,
    )

    stalls = [a for a in store.anomalies() if a["metric"] == "stall"]
    assert len(stalls) == 1, "o episodio deve ser UMA linha, nao um tick por linha"
    event = stalls[0]
    assert event["severity"] == "critical"
    assert "starved" in event["detail"]["signals"]
    assert event["detail"]["culprit"]["name"] == "burn"
    measured = event["detail"]["measured"]
    assert measured["sleep_s"] >= measured["interval_s"] * settings.STALL_STARVE_FACTOR
    log = paths.daemon_log.read_text(encoding="utf-8")
    assert "ANOMALIA stall critical" in log


def test_run_watch_loop_samples_faster_while_stalled(tmp_path):
    """Spec 4: sob suspeita o daemon encurta o proprio intervalo — e a unica
    maneira de saber a hora em que o episodio acabou."""
    paths = settings.paths_for(tmp_path)
    sleeper = SlowSleep(over=3.0)

    daemon.run_watch_loop(
        paths,
        sensor=ScriptedSensor(hot_ticks(24)),
        store=EventStore(paths.events),
        sleep=sleeper.sleep,
        clock=sleeper.clock,
        interval=settings.SAMPLE_INTERVAL_S,
        stop_after=20,
    )

    assert sleeper.asked[0] == settings.SAMPLE_INTERVAL_S
    assert settings.SAMPLE_INTERVAL_FAST_S in sleeper.asked, \
        "o intervalo nunca encurtou durante o travamento"


def test_run_watch_loop_goes_back_to_the_normal_interval(tmp_path):
    """Voltar ao intervalo normal nao e detalhe de performance: a 0,5 s para
    sempre, o daemon vira o processo mais caro da maquina que ele vigia."""
    paths = settings.paths_for(tmp_path)
    sleeper = SlowSleep(over=3.0, flip_after=2)

    daemon.run_watch_loop(
        paths,
        sensor=ScriptedSensor(hot_ticks(12) + cool_ticks(20)),
        store=EventStore(paths.events),
        sleep=sleeper.sleep,
        clock=sleeper.clock,
        interval=settings.SAMPLE_INTERVAL_S,
        stop_after=28,
    )

    assert sleeper.asked[-1] == settings.SAMPLE_INTERVAL_S
    log = paths.daemon_log.read_text(encoding="utf-8")
    assert "ESTAGNACAO CESSOU" in log
    assert "dur=" in log


def test_run_watch_loop_marks_the_heartbeat(tmp_path):
    paths = settings.paths_for(tmp_path)
    sleeper = SlowSleep(over=3.0)

    daemon.run_watch_loop(
        paths,
        sensor=ScriptedSensor(hot_ticks(24)),
        store=EventStore(paths.events),
        sleep=sleeper.sleep,
        clock=sleeper.clock,
        interval=settings.SAMPLE_INTERVAL_S,
        stop_after=20,
    )

    log = paths.daemon_log.read_text(encoding="utf-8")
    assert "swap=0.0" in log, "a taxa/percentual de paginacao nao aparece no tick"
    assert "swap_rate=400" in log
    assert "stall=1" in log, "o batimento nao diz que estavamos travados"


def test_paused_loop_records_no_stall_incident(tmp_path):
    """Pausado e mudo tambem para o indice: o episodio acontece (o intervalo
    ate encurta), mas nenhuma linha nova vai para o historico."""
    paths = settings.paths_for(tmp_path)
    store = EventStore(paths.events)
    daemon.pause(paths)
    sleeper = SlowSleep(over=3.0)

    daemon.run_watch_loop(
        paths,
        sensor=ScriptedSensor(hot_ticks(24)),
        store=store,
        sleep=sleeper.sleep,
        clock=sleeper.clock,
        interval=settings.SAMPLE_INTERVAL_S,
        stop_after=20,
    )

    assert store.anomalies() == []
    log = paths.daemon_log.read_text(encoding="utf-8")
    assert "ANOMALIA" not in log
    assert settings.SAMPLE_INTERVAL_FAST_S in sleeper.asked


def test_broken_stall_monitor_does_not_stop_sampling(tmp_path):
    """Indice de estagnacao e vigilancia extra: se ele estourar, a amostra de
    CPU e o batimento seguem — como nos outros monitores."""
    paths = settings.paths_for(tmp_path)
    store = EventStore(paths.events)

    class ExplodingStall:
        def observe(self, *a, **kw):
            raise RuntimeError("indice quebrado")

        suspect = False
        stalled = False
        closed = None

    ticks = daemon.run_watch_loop(
        paths,
        sensor=FakeSensor(),
        store=store,
        stall=ExplodingStall(),
        sleep=lambda _s: None,
        stop_after=settings.MIN_SAMPLES_BEFORE_DETECT + 5,
    )

    assert ticks == settings.MIN_SAMPLES_BEFORE_DETECT + 5
    assert any(a["metric"] == "cpu" for a in store.anomalies())

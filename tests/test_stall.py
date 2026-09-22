from __future__ import annotations

import datetime

from conftest import make_sample, proc

from sentinel import settings
from sentinel.detector import METRIC_CPU, METRIC_RAM, SEV_CRITICAL, SEV_WARNING, Finding
from sentinel.stall import (
    METRIC_STALL,
    SIGNAL_DISK_SATURATED,
    SIGNAL_STARVED,
    SIGNAL_THRASHING,
    StallMonitor,
)

# Uma pausa de `sleep` acima do fator já conta como inanição. 2,0 s pedidos
# x 2,0 = 4,0; 5,0 é folgado o bastante pra não bater no limiar por acaso.
SLOW_SLEEP = 5.0
NORMAL_SLEEP = 2.0


def critical_finding(name="chrome.exe", *, metric=METRIC_RAM, pid=4242) -> Finding:
    """O que o detector entrega quando um app está em crítico: a métrica e o
    culpado no topo. O stall não refaz essa conta — só a consome."""
    return Finding(
        metric=metric,
        severity=SEV_CRITICAL,
        value=97.0,
        threshold=settings.RAM_CRITICAL,
        samples=1,
        span_s=settings.SAMPLE_INTERVAL_S,
        top_processes=[proc(pid, name, cpu=12.0, rss_mb=3200.0)],
        fingerprint=f"{metric}:critical:{name}",
    )


def hot_sample(**over):
    base = dict(swap_rate=settings.STALL_SWAP_RATE_PS + 50.0)
    base.update(over)
    return make_sample(**base)


def drive(monitor, cycles):
    """Roda `cycles` (sample, findings, sleep_s) e junta os incidentes.

    `cycles` é lista de dicts; `sleep_s`/`interval_s` viram o par pedido/de
    decorrido, igual ao daemon."""
    out = []
    for spec in cycles:
        out.extend(
            monitor.observe(
                spec.get("sample", make_sample()),
                spec.get("findings"),
                sleep_s=spec.get("sleep_s"),
                interval_s=spec.get("interval_s", settings.SAMPLE_INTERVAL_S),
            )
        )
    return out


# -- a regra de combinação ------------------------------------------------


def test_pressure_without_culprit_is_not_a_stall():
    """O caso que o spec fecha com mais força: thrash sem ninguém em crítico
    é memória sendo usada, não máquina travando."""
    monitor = StallMonitor()
    incidents = drive(
        monitor,
        [
            {"sample": hot_sample(), "sleep_s": SLOW_SLEEP},
            {"sample": hot_sample(), "sleep_s": SLOW_SLEEP},
        ],
    )
    assert incidents == []
    assert monitor.last.pressure is True
    assert monitor.stalled is False


def test_critical_without_pressure_is_not_a_stall():
    monitor = StallMonitor()
    incidents = drive(
        monitor,
        [
            {"sample": make_sample(), "findings": [critical_finding()]},
            {"sample": make_sample(), "findings": [critical_finding()]},
            {"sample": make_sample(), "findings": [critical_finding()]},
        ],
    )
    assert incidents == []
    assert monitor.last.culprit is not None
    assert monitor.stalled is False


def test_starvation_plus_sustained_culprit_opens_the_episode():
    monitor = StallMonitor()
    incidents = drive(
        monitor,
        [
            {
                "sample": make_sample(io=5.0),
                "findings": [critical_finding()],
                "sleep_s": SLOW_SLEEP,
            },
            {
                "sample": make_sample(io=5.0),
                "findings": [critical_finding()],
                "sleep_s": SLOW_SLEEP,
            },
        ],
    )
    assert len(incidents) == 1
    incident = incidents[0]
    assert incident.metric == METRIC_STALL
    assert incident.severity == SEV_CRITICAL
    assert SIGNAL_STARVED in incident.detail["signals"]
    assert incident.detail["culprit"]["name"] == "chrome.exe"
    assert "chrome.exe" in incident.label


def test_one_slow_sleep_is_not_yet_starvation():
    """Um tick atrasado e o `wevtutil` do ciclo anterior, o GC, nada. A
    sustentacao pede dois batimentos seguidos de sono longo."""
    monitor = StallMonitor()
    incidents = drive(
        monitor,
        [
            {
                "sample": make_sample(),
                "findings": [critical_finding()],
                "sleep_s": SLOW_SLEEP,
            },
        ],
    )
    assert incidents == []
    assert monitor.last.starved is False


def test_sleep_overrun_is_a_ratio_against_the_requested_interval():
    """`interval_s` e o que foi pedido e `sleep_s` o que correu: a conta e o
    fator. Dormir 3,0 s tendo pedido 2,0 (fator 2,0) ainda nao e fome."""
    monitor = StallMonitor()
    drive(
        monitor,
        [
            {
                "sample": make_sample(),
                "findings": [critical_finding()],
                "sleep_s": 3.0,
            },
            {
                "sample": make_sample(),
                "findings": [critical_finding()],
                "sleep_s": 3.0,
            },
        ],
    )
    assert monitor.last.starved is False
    assert monitor.last.sleep_s == 3.0


def test_thrash_alone_without_rate_and_commit_is_silent():
    monitor = StallMonitor()
    drive(monitor, [{"sample": make_sample(swap=20.0, swap_rate=1.0)}] * 3)
    assert monitor.last.thrashing is False


def test_commit_pressure_counts_as_thrash_even_without_movement():
    """Pagefile/commit perto do limite é o ponto em que o Windows começa a
    recusar reserva: não precisa estar paginando pra ser gargalo."""
    monitor = StallMonitor()
    incidents = drive(
        monitor,
        [
            {
                "sample": make_sample(swap=95.0, swap_rate=0.0),
                "findings": [critical_finding()],
            },
            {
                "sample": make_sample(swap=95.0, swap_rate=0.0),
                "findings": [critical_finding()],
            },
        ],
    )
    assert len(incidents) == 1
    assert SIGNAL_THRASHING in incidents[0].detail["signals"]
    assert incidents[0].detail["measured"]["swap_percent"] == 95.0


def test_saturated_disk_needs_its_own_longer_run():
    monitor = StallMonitor()
    findings = [critical_finding(metric=METRIC_CPU)]
    hot = make_sample(io=settings.STALL_DISK_BUSY + 1.0, swap_rate=0.0)
    opened = drive(
        monitor,
        [
            {"sample": hot, "findings": findings},
            {"sample": hot, "findings": findings},
        ],
    )
    assert opened == [], "2 ciclos de disco saturado nao devem abrir episodio"
    third = drive(monitor, [{"sample": hot, "findings": findings}])
    assert len(third) == 1
    assert third[0].severity == SEV_WARNING
    assert third[0].detail["signals"] == [SIGNAL_DISK_SATURATED]


# -- quem pode ser culpado ------------------------------------------------


def test_protected_process_is_never_the_culprit():
    """svchost em crítico não é matéria-prima de alívio: sem este filtro o
    daemon acusaria o Windows de travar o Windows."""
    monitor = StallMonitor()
    drive(
        monitor,
        [
            {
                "sample": hot_sample(),
                "findings": [critical_finding(name="svchost.exe")],
            },
            {
                "sample": hot_sample(),
                "findings": [critical_finding(name="svchost.exe")],
            },
        ],
    )
    assert monitor.last.culprit is None
    assert monitor.suspect is True  # pressao ha, alvo nao


def test_warning_finding_does_not_nominate_a_culprit():
    monitor = StallMonitor()
    warning = Finding(
        metric=METRIC_RAM,
        severity=SEV_WARNING,
        value=88.0,
        threshold=settings.RAM_WARNING,
        samples=5,
        span_s=10.0,
        top_processes=[proc(1, "chrome.exe")],
        fingerprint="ram:warning:chrome.exe",
    )
    drive(
        monitor,
        [
            {"sample": hot_sample(), "findings": [warning]},
            {"sample": hot_sample(), "findings": [warning]},
        ],
    )
    assert monitor.last.culprit is None


def test_culprit_must_be_the_same_process_across_cycles():
    """Dois apps críticos seguidos não são 'a máquina travando por causa de
    um': são dois apps ocupados. A sustentação é por nome."""
    monitor = StallMonitor()
    drive(
        monitor,
        [
            {"sample": hot_sample(), "findings": [critical_finding("chrome.exe")]},
            {"sample": hot_sample(), "findings": [critical_finding("code.exe")]},
            {"sample": hot_sample(), "findings": [critical_finding("chrome.exe")]},
        ],
    )
    assert monitor.last.culprit is None


def test_finding_without_processes_has_no_candidate():
    """Disco cheio (volume, não processo) é crítico e é contexto, mas não dá
    a quem age um alvo pra rebaixar."""
    monitor = StallMonitor()
    disk_full = Finding(
        metric="disk",
        severity=SEV_CRITICAL,
        value=99.0,
        threshold=settings.DISK_CRITICAL,
        samples=1,
        span_s=2.0,
        top_processes=[],
        fingerprint="disk:critical:-",
    )
    drive(
        monitor,
        [
            {"sample": hot_sample(), "findings": [disk_full]},
            {"sample": hot_sample(), "findings": [disk_full]},
        ],
    )
    assert monitor.last.culprit is None


# -- episódio: abre uma vez, fecha com soma --------------------------------


def test_episode_emits_one_incident_and_absorbs_later_signals():
    monitor = StallMonitor()
    disk = make_sample(swap_rate=0.0, io=settings.STALL_DISK_BUSY + 1.0)
    cycle = {"sample": disk, "findings": [critical_finding()]}
    opened = drive(monitor, [cycle, cycle, cycle])
    assert len(opened) == 1
    assert opened[0].detail["signals"] == [SIGNAL_DISK_SATURATED]

    # O disco continua e a paginacao entra depois: sinal novo nao gera uma
    # segunda linha no historico — o episodio e um so.
    both = make_sample(
        io=settings.STALL_DISK_BUSY + 1.0,
        swap_rate=settings.STALL_SWAP_RATE_PS + 10,
    )
    later = drive(monitor, [{"sample": both, "findings": [critical_finding()]}] * 2)
    assert later == []
    assert monitor.stalled is True
    assert monitor.last.thrashing is True

    monitor.observe(make_sample(), None, interval_s=settings.SAMPLE_INTERVAL_S)
    closed = monitor.closed
    assert closed is not None
    assert sorted(closed["signals"]) == sorted([SIGNAL_DISK_SATURATED, SIGNAL_THRASHING])
    assert closed["ticks"] == 3
    assert monitor.stalled is False


def test_episode_is_measured_from_the_cycle_that_confirmed_it():
    """O relogio do episodio e o das amostras, nao o relogio do daemon:
    comeca no ciclo em que a regra fechou (o anterior ainda era suspeita) e
    termina no primeiro ciclo limpo — o `duration_s` que o log mostra."""
    monitor = StallMonitor()
    start = datetime.datetime(2026, 9, 22, 14, 0, 0, tzinfo=datetime.timezone.utc)
    end = start + datetime.timedelta(seconds=18)
    cycle_a = {
        "sample": hot_sample(ts=start),
        "findings": [critical_finding()],
        "sleep_s": SLOW_SLEEP,
    }
    cycle_b = {
        "sample": hot_sample(ts=start + datetime.timedelta(seconds=6)),
        "findings": [critical_finding()],
        "sleep_s": SLOW_SLEEP,
    }
    drive(monitor, [cycle_a, cycle_b])
    assert monitor.stalled is True  # aberto no segundo ciclo, nao no primeiro
    monitor.observe(
        make_sample(ts=end),
        None,
        sleep_s=NORMAL_SLEEP,
        interval_s=settings.SAMPLE_INTERVAL_S,
    )
    assert monitor.closed["duration_s"] == 12.0


def test_counters_reset_after_closing_so_a_new_episode_must_sustain_again():
    monitor = StallMonitor()
    cycle = {
        "sample": hot_sample(),
        "findings": [critical_finding()],
        "sleep_s": SLOW_SLEEP,
    }
    drive(monitor, [cycle, cycle])
    drive(monitor, [{"sample": make_sample(), "findings": None}])
    assert monitor.closed is not None

    # Volta a pressao: o primeiro ciclo depois da folga nao reabre nada, e o
    # que impede um episodio de renascer com um tick de memoria residua.
    assert drive(monitor, [cycle]) == []
    assert drive(monitor, [cycle]) != []


# -- suspeita: o que manda amostrar mais rapido ----------------------------


def test_suspect_is_true_under_pressure_before_the_culprit_confirms():
    """O intervalo encurta na suspeita, não na certeza: chegar à certeza com
    resolução de 2 s é não ver o episódio passar por dentro."""
    monitor = StallMonitor()
    assert monitor.suspect is False
    drive(monitor, [{"sample": hot_sample(), "findings": None}] * 2)
    assert monitor.last.pressure is True
    assert monitor.suspect is True
    assert monitor.stalled is False


def test_not_suspect_when_only_a_culprit_is_critical():
    monitor = StallMonitor()
    monitor.observe(make_sample(), [critical_finding()], sleep_s=NORMAL_SLEEP)
    assert monitor.suspect is False


def test_overrides_move_the_thresholds():
    """Tudo no índice é sobrescrevível por config: a unidade do `sin`/`sout`
    muda de plataforma, e um limiar rígido seria um sinal mudo em Linux."""
    monitor = StallMonitor(overrides={"STALL_SWAP_RATE_PS": 4000.0})
    drive(monitor, [{"sample": hot_sample()}] * 3)
    assert monitor.last.thrashing is False

    loose = StallMonitor(overrides={"STALL_SWAP_RATE_PS": 8.0})
    drive(loose, [{"sample": make_sample(swap_rate=9.0)}] * 2)
    assert loose.last.thrashing is True

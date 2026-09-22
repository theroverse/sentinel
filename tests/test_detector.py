from __future__ import annotations

from conftest import make_sample, proc

from sentinel import settings
from sentinel.detector import (
    METRIC_CPU,
    METRIC_DISK,
    METRIC_IO,
    METRIC_NETWORK,
    METRIC_RAM,
    SEV_CRITICAL,
    SEV_INFO,
    SEV_WARNING,
    Detector,
    _consecutive_run,
    _percentile,
)


def _prime(detector: Detector, n: int, sample_factory) -> None:
    """Empura n amostras pelo detector, mas ignora o retorno — serve pra
    atravessar o periodo de silencio (MIN_SAMPLES_BEFORE_DETECT)."""
    for _ in range(n):
        detector.observe(sample_factory())


def test_consecutive_run_counts_from_the_end():
    values = [10, 90, 95, 92, 30, 88, 91]
    # Do fim pra tras: 91,88 >=85 (2), depois 30 quebra.
    assert _consecutive_run(values, 85) == 2


def test_percentile_nearest_rank():
    values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert _percentile(values, 95) == 10
    assert _percentile([], 50) == 0.0


def test_detector_silent_before_min_samples():
    det = Detector()
    hot = lambda: make_sample(cpu=99, ram=99, disk=99, io=99)
    findings = []
    for _ in range(settings.MIN_SAMPLES_BEFORE_DETECT - 1):
        findings = det.observe(hot())
    assert findings == []


def test_cpu_requires_sustained_run():
    det = Detector()
    # Cruza o piso de silencio com CPU baixa, depois sobe.
    _prime(det, settings.MIN_SAMPLES_BEFORE_DETECT, lambda: make_sample(cpu=10))
    # 4 amostras quentes < CPU_SUSTAINED (5): ainda nao dispara.
    for _ in range(settings.CPU_SUSTAINED - 1):
        out = det.observe(make_sample(cpu=90, top_cpu=[proc(1, "app")]))
    finding_metrics = [f.metric for f in out]
    assert METRIC_CPU not in finding_metrics

    # A amostra que fecha a serie sustained dispara.
    out = det.observe(make_sample(cpu=90, top_cpu=[proc(1, "app")]))
    cpu = next((f for f in out if f.metric == METRIC_CPU), None)
    assert cpu is not None
    assert cpu.severity == SEV_WARNING
    assert cpu.fingerprint == "cpu:warning:app"


def test_cpu_critical_when_over_critical_threshold():
    det = Detector()
    _prime(
        det,
        settings.MIN_SAMPLES_BEFORE_DETECT,
        lambda: make_sample(cpu=97, top_cpu=[proc(7, "stress")]),
    )
    out = det.observe(make_sample(cpu=97, top_cpu=[proc(7, "stress")]))
    cpu = next(f for f in out if f.metric == METRIC_CPU)
    assert cpu.severity == SEV_CRITICAL


def test_ram_critical_is_immediate():
    det = Detector()
    # So o necessario pra sair do silencio; RAM critica nao espera sustained.
    _prime(det, settings.MIN_SAMPLES_BEFORE_DETECT, lambda: make_sample(ram=10))
    out = det.observe(make_sample(ram=96, top_mem=[proc(3, "leak")]))
    ram = next(f for f in out if f.metric == METRIC_RAM)
    assert ram.severity == SEV_CRITICAL
    assert ram.samples == 1


def test_disk_is_immediate_not_sustained():
    det = Detector()
    _prime(det, settings.MIN_SAMPLES_BEFORE_DETECT, lambda: make_sample(disk=10))
    out = det.observe(make_sample(disk=99))
    disk = next(f for f in out if f.metric == METRIC_DISK)
    assert disk.severity == SEV_CRITICAL
    assert disk.samples == 1


def test_io_needs_longer_sustained_window():
    det = Detector()
    _prime(det, settings.MIN_SAMPLES_BEFORE_DETECT, lambda: make_sample(io=5))
    # IO_SUSTAINED (8) e maior que CPU; 6 amostras ainda nao bastam.
    for _ in range(detector_io_run_below()):
        out = det.observe(make_sample(io=75))
    assert METRIC_IO not in [f.metric for f in out]

    for _ in range(settings.IO_SUSTAINED):
        out = det.observe(make_sample(io=75))
    io = next((f for f in out if f.metric == METRIC_IO), None)
    assert io is not None
    assert io.severity == SEV_WARNING


def detector_io_run_below() -> int:
    # Quantas amostras abaixo de IO_SUSTAINED pra provar o gate sustained.
    return settings.IO_SUSTAINED - 3


def test_network_is_informational_and_relative():
    det = Detector()
    # Baseline baixa, depois um spike relativo: deve marcar info, nunca
    # critical (banda alta nao e falha).
    _prime(
        det,
        settings.MIN_SAMPLES_BEFORE_DETECT,
        lambda: make_sample(net_recv=1_000_000, net_sent=1_000_000),
    )
    out = None
    for _ in range(settings.NET_SUSTAINED):
        out = det.observe(make_sample(net_recv=50_000_000, net_sent=50_000_000))
    net = next((f for f in out if f.metric == METRIC_NETWORK), None)
    assert net is not None
    assert net.severity == SEV_INFO


def test_overrides_change_threshold():
    # Baixa o limiar de CPU pra disparar com valor que o padrao ignoraria.
    det = Detector(overrides={"CPU_WARNING": "20", "CPU_CRITICAL": "30"})
    _prime(
        det,
        settings.MIN_SAMPLES_BEFORE_DETECT,
        lambda: make_sample(cpu=25, top_cpu=[proc(1, "x")]),
    )
    out = det.observe(make_sample(cpu=25, top_cpu=[proc(1, "x")]))
    cpu = next(f for f in out if f.metric == METRIC_CPU)
    assert cpu.threshold == 20.0

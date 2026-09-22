from __future__ import annotations

import pytest

from conftest import FakeProcess, FakePsutil

from sentinel.sensor import Sensor


def _ps(**kwargs):
    return FakePsutil(**kwargs)


def test_sample_reads_cpu_ram_disk():
    ps = _ps(cpu=42.0, ram_percent=61.5, disk_percent=77.0)
    sensor = Sensor(psutil_module=ps)
    sample = sensor.sample(top=False)

    assert sample.cpu_percent == 42.0
    assert sample.ram_percent == 61.5
    assert sample.disk_percent == 77.0
    assert sample.disk_path == "C:\\"


def test_net_rate_is_zero_on_first_sample_then_delta():
    # Contadores cumulativos: 1a leitura nao tem janela anterior -> 0.
    ps = _ps(net=(1000, 2000))
    sensor = Sensor(psutil_module=ps)
    first = sensor.sample(top=False)
    assert first.net_recv_bps == 0.0
    assert first.net_sent_bps == 0.0

    # Reajusta a janela anterior para 100s atras com contadores menores,
    # e sobe os counters. Com dt ~100s, o jitter de wall-clock do teste
    # (microssegundos) e irrelevante: taxa ~ delta/100 (deterministico).
    now = sensor._prev_net[0]
    sensor._prev_net = (now - 100.0, 1000, 2000)
    ps._net = (3000, 6000)
    second = sensor.sample(top=False)
    assert second.net_sent_bps == pytest.approx(20.0, rel=0.01)
    assert second.net_recv_bps == pytest.approx(40.0, rel=0.01)


def test_top_processes_sorted_and_limited():
    procs = [
        FakeProcess(1, "idle", cpu=1.0, rss=10 * 1024 * 1024),
        FakeProcess(2, "hog", cpu=80.0, rss=500 * 1024 * 1024),
        FakeProcess(3, "mid", cpu=40.0, rss=200 * 1024 * 1024),
    ]
    ps = _ps(processes=procs)
    sensor = Sensor(psutil_module=ps)

    top_cpu = sensor.top_processes(sort="cpu", n=2)
    assert [p.name for p in top_cpu] == ["hog", "mid"]

    top_mem = sensor.top_processes(sort="mem", n=2)
    assert top_mem[0].name == "hog"
    assert top_mem[0].rss_mb == 500.0


def test_sample_populates_top_lists():
    procs = [FakeProcess(5, "app", cpu=55.0, rss=300 * 1024 * 1024)]
    ps = _ps(cpu=55.0, processes=procs)
    sensor = Sensor(psutil_module=ps)
    sample = sensor.sample(top=True)

    assert sample.top_cpu and sample.top_cpu[0].name == "app"
    assert sample.top_mem[0].pid == 5


def test_top_processes_excludes_system_idle():
    # System Idle Process lidera o 'cpu%' numa maquina ociosa; nunca deve
    # aparecer como suspeito topo.
    procs = [
        FakeProcess(0, "System Idle Process", cpu=800.0),
        FakeProcess(10, "realhog", cpu=40.0),
    ]
    sensor = Sensor(psutil_module=_ps(processes=procs))
    names = [p.name for p in sensor.top_processes(sort="cpu", n=5)]
    assert names == ["realhog"]

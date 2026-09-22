from __future__ import annotations

import contextlib
import datetime

import pytest

from sentinel.sensor import ProcessInfo, Sample


# ---------------------------------------------------------------------------
# psutil falso: cobre SO a superficie que Sensor/ProcessCtl tocam, sem
# processos reais nem privilégios. Testes de detector/events/tutor nem
# precisam disto (constroem Sample/dict direto).
# ---------------------------------------------------------------------------
class _Mem:
    def __init__(self, percent: float):
        self.percent = percent


class _DiskUsage:
    def __init__(self, percent: float):
        self.percent = percent


class _Net:
    def __init__(self, sent: int, recv: int):
        self.bytes_sent = sent
        self.bytes_recv = recv


class _DiskIO:
    def __init__(self, read_time: float, write_time: float):
        self.read_time = read_time
        self.write_time = write_time


class _Part:
    def __init__(self, device: str, mountpoint: str):
        self.device = device
        self.mountpoint = mountpoint


class FakeProcess:
    def __init__(
        self,
        pid: int,
        name: str,
        cpu: float = 0.0,
        rss: int = 0,
        ppid: int | None = None,
        children=None,
        create_time: float = 1000.0,
    ):
        self.pid = pid
        self._name = name
        self._cpu = cpu
        self._rss = rss
        self._ppid = ppid
        self._children = children or []
        self._create_time = create_time
        self.terminated = False
        self.killed = False

    def name(self) -> str:
        return self._name

    def ppid(self) -> int | None:
        return self._ppid

    def create_time(self) -> float:
        return self._create_time

    def cpu_percent(self, interval=None) -> float:
        return self._cpu

    def memory_info(self):
        proc = self

        class _MI:
            rss = proc._rss

        return _MI()

    def children(self, recursive: bool = False) -> list["FakeProcess"]:
        if not recursive:
            return list(self._children)
        out: list[FakeProcess] = []
        for child in self._children:
            out.append(child)
            out.extend(child.children(recursive=True))
        return out

    def oneshot(self):
        @contextlib.contextmanager
        def _cm():
            yield

        return _cm()

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout=None) -> None:
        return None


class FakePsutil:
    """Roteador minimo do API do psutil usado pelo Sentinel.

    `cpu_sequence`: valores sucessivos retornados por cpu_percent (o
    Sensor arma o contador no __init__ com uma chamada extra, entao a
    primeira leitura real e o item [0] depois do arm). Quando acaba,
    repete o ultimo.
    """

    def __init__(
        self,
        *,
        cpu=0.0,
        ram_percent=0.0,
        disk_percent=0.0,
        net=(0, 0),
        disk_io=(0.0, 0.0),
        processes=None,
        partitions=None,
    ):
        self._cpu = cpu
        self._ram_percent = ram_percent
        self._disk_percent = disk_percent
        self._net = net
        self._disk_io = disk_io
        self._processes = processes or []
        self._partitions = partitions or [
            _Part("C:", "C:\\"),
        ]

    def cpu_percent(self, interval=None) -> float:
        return float(self._cpu)

    def virtual_memory(self) -> _Mem:
        return _Mem(self._ram_percent)

    def disk_usage(self, path) -> _DiskUsage:
        return _DiskUsage(self._disk_percent)

    def disk_partitions(self, all=False) -> list[_Part]:
        return list(self._partitions)

    def net_io_counters(self) -> _Net:
        return _Net(*self._net)

    def disk_io_counters(self) -> _DiskIO:
        return _DiskIO(*self._disk_io)

    def process_iter(self, attrs=None):
        return list(self._processes)

    def set_processes(self, procs) -> None:
        """Troca o conjunto vivo entre ticks (o TreeMonitor le a cada
        ciclo): usa o mesmo tipo de lista que o construtor."""
        self._processes = list(procs)

    def Process(self, pid: int) -> FakeProcess:
        for proc in self._processes:
            if proc.pid == pid:
                return proc
        raise _NoSuchProcess(pid)

    def wait_procs(self, procs, timeout=None):
        # Fake: tudo termina graciosamente no primeiro round.
        return list(procs), []

    def pid_exists(self, pid: int) -> bool:
        return any(p.pid == pid for p in self._processes)


class _NoSuchProcess(Exception):
    pass


def make_sample(
    *,
    cpu: float = 0.0,
    ram: float = 0.0,
    disk: float = 0.0,
    io: float = 0.0,
    net_recv: float = 0.0,
    net_sent: float = 0.0,
    top_cpu=None,
    top_mem=None,
    ts: datetime.datetime | None = None,
) -> Sample:
    """Fabrica de Sample pra testes de detector/tutor/events (sem psutil)."""
    return Sample(
        ts=ts or datetime.datetime(2026, 9, 21, 12, 0, 0, tzinfo=datetime.timezone.utc),
        cpu_percent=cpu,
        ram_percent=ram,
        disk_percent=disk,
        disk_path="C:\\",
        io_busy_percent=io,
        net_recv_bps=net_recv,
        net_sent_bps=net_sent,
        top_cpu=top_cpu or [],
        top_mem=top_mem or [],
    )


def proc(pid: int, name: str, *, cpu: float = 0.0, rss_mb: float = 0.0) -> ProcessInfo:
    return ProcessInfo(pid=pid, name=name, cpu=cpu, rss_mb=rss_mb)


def tree_proc(pid: int, name: str, *, ppid=None, create_time: float = 1000.0) -> FakeProcess:
    """Processo minimo pro TreeMonitor (que so le pid/ppid/name/create_time)."""
    return FakeProcess(pid=pid, name=name, ppid=ppid, create_time=create_time)


@pytest.fixture
def fake_psutil_cls():
    return FakePsutil


@pytest.fixture
def make_psutil():
    return FakePsutil

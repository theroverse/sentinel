from __future__ import annotations

import datetime
import os
from dataclasses import dataclass, field, asdict

from sentinel import settings


@dataclass
class ProcessInfo:
    """Um processo "caro" capturado junto da amostra, pra enriquecer o
    evento e o tutorial. Deliberadamente minimo: pid, nome e uso. Nunca
    argv/cmdline/caminhos do usuario — so o necessario pra identificar o
    culpado (privacidade)."""

    pid: int
    name: str
    cpu: float
    rss_mb: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Sample:
    """Uma leitura pontual dos recursos. `ts` em UTC aware (o schema do
    evento grava ISO-8601 com offset)."""

    ts: datetime.datetime
    cpu_percent: float
    ram_percent: float
    disk_percent: float
    disk_path: str
    io_busy_percent: float
    net_recv_bps: float
    net_sent_bps: float
    top_cpu: list[ProcessInfo] = field(default_factory=list)
    top_mem: list[ProcessInfo] = field(default_factory=list)


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class Sensor:
    """Le recursos via psutil e devolve `Sample`s.

    O modulo psutil e injetavel (`psutil_module`) pra permitir testes com
    um fake sem depender de psutil instalado. As contrapartidas de rede e
    disco sao deltas entre chamadas: a PRIMEIRA chamada retorna 0 bps /
    io_busy 0 (nao ha janela anterior), como o psutil real faz para
    cpu_percent.

    `cpu_percent` usa modo nao-bloqueante (interval=None): na primeira
    chamada retorna 0.0 e nas seguintes, o uso desde a chamada anterior. O
    loop do daemon chama em cada tick, entao apos o primeiro tick os
    valores sao reais.
    """

    def __init__(self, psutil_module=None) -> None:
        if psutil_module is None:
            # Import tardio: quem so importa settings/sensor p/ testes com
            # fake nao precisa ter psutil no ambiente.
            import psutil as psutil_module  # type: ignore[no-redef]

        self._ps = psutil_module
        self._prev_net: tuple[float, float, float] | None = None  # (ts, sent, recv)
        self._prev_disk: tuple[float, float] | None = None  # (ts, busy_ms)
        # Primeira leitura nao-bloqueante de cpu_percent "arma" o contador
        # interno do psutil; descarta o 0.0 resultante.
        self._ps.cpu_percent(interval=None)

    def sample(self, *, top: bool = True) -> Sample:
        ps = self._ps
        now = _utcnow()
        now_mono = now.timestamp()

        cpu = float(ps.cpu_percent(interval=None))
        vm = ps.virtual_memory()
        ram_percent = float(vm.percent)

        du = ps.disk_usage(self._primary_disk())
        disk_percent = float(du.percent)

        io_busy, net_recv_bps, net_sent_bps = self._rates(now_mono, ps)

        top_cpu = self.top_processes(sort="cpu") if top else []
        top_mem = self.top_processes(sort="mem") if top else []

        return Sample(
            ts=now,
            cpu_percent=cpu,
            ram_percent=ram_percent,
            disk_percent=disk_percent,
            disk_path=self._primary_disk(),
            io_busy_percent=io_busy,
            net_recv_bps=net_recv_bps,
            net_sent_bps=net_sent_bps,
            top_cpu=top_cpu,
            top_mem=top_mem,
        )

    def _primary_disk(self) -> str:
        """Volume a vigiar: 'C:\\' no Windows, '/' fora dele. Um unico
        disco principal mantem o detector simples (YAGNI: N volumes)."""
        ps = self._ps
        part = None
        try:
            partitions = ps.disk_partitions(all=False)
        except Exception:  # psutil pode falhar em pontos de montagem ruins
            partitions = []

        if partitions:
            # Escolhe a particao do drive raiz do sistema, se visivel.
            system_drive = os.environ.get("SystemDrive")
            if system_drive:
                for p in partitions:
                    if p.device.upper().startswith(system_drive.upper()):
                        return p.mountpoint
            return partitions[0].mountpoint

        return "C:\\" if os.name == "nt" else "/"

    def _rates(self, now_mono: float, ps) -> tuple[float, float, float]:
        """Converte contadores cumulativos (net, disco) em taxas/segundo
        usando o delta desde a amostra anterior. Primeira chamada: zeros."""
        recv_bps = 0.0
        sent_bps = 0.0
        io_busy = 0.0

        try:
            net = ps.net_io_counters()
        except Exception:
            net = None

        if net is not None:
            cur = (now_mono, float(net.bytes_sent), float(net.bytes_recv))
            if self._prev_net is not None:
                dt = cur[0] - self._prev_net[0]
                if dt > 0:
                    sent_bps = (cur[1] - self._prev_net[1]) / dt
                    recv_bps = (cur[2] - self._prev_net[2]) / dt
            self._prev_net = cur

        try:
            dio = ps.disk_io_counters()
        except Exception:
            dio = None

        if dio is not None:
            busy_ms = float(getattr(dio, "read_time", 0)) + float(
                getattr(dio, "write_time", 0)
            )
            cur = (now_mono, busy_ms)
            if self._prev_disk is not None:
                dt_ms = (cur[0] - self._prev_disk[0]) * 1000.0
                if dt_ms > 0:
                    # Aproximacao: tempo de IO agregado (read+write) sobre o
                    # wall-clock, clampado a 100%. Leitura otimista — pode
                    # passar de 100 em IO paralelo; da clamp, entao e teto.
                    io_busy = max(0.0, min(100.0, (cur[1] - self._prev_disk[1]) / dt_ms * 100.0))
            self._prev_disk = cur

        return io_busy, max(0.0, recv_bps), max(0.0, sent_bps)

    def top_processes(self, sort: str = "cpu", n: int | None = None) -> list[ProcessInfo]:
        """Os `n` processos mais caros por `sort` ('cpu' ou 'mem').

        cpu_percent por processo e, como no total, delta desde a ultima
        consulta — por isso o daemon precisa chamar todo tick (faz, via
        `sample`). Nome/pid nunca sao filtrados aqui; quem protege nomes
        criticas e `processctl`.
        """
        ps = self._ps
        n = n if n is not None else settings.TOP_PROCESSES

        procs: list[ProcessInfo] = []
        for proc in ps.process_iter(attrs=None):
            try:
                with proc.oneshot():
                    name = proc.name()
                    if name.lower() in settings.NON_CULPRIT_PROCESS_NAMES:
                        # Idle nao e um consumidor real; remove do ranking
                        # pra nao virar o "suspeito topo" de um evento.
                        continue
                    cpu = float(proc.cpu_percent(interval=None))
                    rss_mb = float(proc.memory_info().rss) / (1024 * 1024)
            except Exception:
                # Processos somem entre iterar e ler (race comum); ignora.
                continue
            procs.append(ProcessInfo(pid=proc.pid, name=name, cpu=cpu, rss_mb=rss_mb))

        key = (lambda p: p.cpu) if sort == "cpu" else (lambda p: p.rss_mb)
        procs.sort(key=key, reverse=True)
        return procs[:n]

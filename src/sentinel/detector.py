from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from sentinel import settings
from sentinel.sensor import ProcessInfo, Sample


# Metricas conhecidas (string estavel no JSONL; nao trocar de leve, e o
# contrato com `events`/`kb`/filtros do CLI).
METRIC_CPU = "cpu"
METRIC_RAM = "ram"
METRIC_DISK = "disk"
METRIC_IO = "io"
METRIC_NETWORK = "network"

SEV_INFO = "info"
SEV_WARNING = "warning"
SEV_CRITICAL = "critical"


@dataclass
class Finding:
    """Resultado de uma regra disparada. `events` transforma isto numa
    linha do JSONL; nao sabe escrever disco aqui (separacao de papel)."""

    metric: str
    severity: str
    value: float
    threshold: float
    samples: int
    span_s: float
    top_processes: list[ProcessInfo]
    fingerprint: str

    @property
    def is_informational(self) -> bool:
        return self.severity == SEV_INFO


def _consecutive_run(values: list[float], threshold: float) -> int:
    """Quantas amostras CONSECUTIVAS no FIM da lista estao >= threshold.

    Medido do presente pra tras: 'agora ha N ticks seguidos acima de X'.
    """
    run = 0
    for value in reversed(values):
        if value >= threshold:
            run += 1
        else:
            break
    return run


def _percentile(values: list[float], pct: float) -> float:
    """Percentil por vizinho mais proximo (sem interpolar): suficiente pra
    estimado de baseline de rede, e nao exige numpy."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    idx = int(round((pct / 100.0) * (len(ordered) - 1)))
    idx = max(0, min(len(ordered) - 1, idx))
    return ordered[idx]


def _severity_for(value: float, warning: float, critical: float) -> str:
    if value >= critical:
        return SEV_CRITICAL
    if value >= warning:
        return SEV_WARNING
    return SEV_INFO


def _fingerprint(metric: str, severity: str, procs: list[ProcessInfo]) -> str:
    name = procs[0].name if procs else "-"
    return f"{metric}:{severity}:{name}"


@dataclass
class Detector:
    """Ve uma serie de `Sample` e devolve `Finding`s pras regras sustained.

    Mantem internamente a janela deslizante (SAMPLE_WINDOW) e uma linha de
    base de rede (NET_BASELINE_WINDOW) pra referencia relativa do pico.
    Silencioso ate MIN_SAMPLES_BEFORE_DETECT amostras.

    `overrides` (de settings.load_overrides) substitui limiares por
    nome de chave (CPU_WARNING etc). Os limiares vem de settings pra um
    lugar so; o detector so le.
    """

    overrides: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._samples: deque[Sample] = deque(maxlen=settings.SAMPLE_WINDOW)
        self._net_total: deque[float] = deque(
            maxlen=settings.NET_BASELINE_WINDOW
        )

    def _th(self, name: str, default: float) -> float:
        return settings.threshold(name, self.overrides, default)

    @property
    def count(self) -> int:
        return len(self._samples)

    def observe(self, sample: Sample) -> list[Finding]:
        self._samples.append(sample)
        self._net_total.append(sample.net_recv_bps + sample.net_sent_bps)

        if self.count < settings.MIN_SAMPLES_BEFORE_DETECT:
            return []

        findings: list[Finding] = []
        for probe in (
            self._probe_cpu,
            self._probe_ram,
            self._probe_disk,
            self._probe_io,
            self._probe_network,
        ):
            finding = probe()
            if finding is not None:
                findings.append(finding)
        return findings

    # -- regras --------------------------------------------------------

    def _values(self, attr: str) -> list[float]:
        return [getattr(s, attr) for s in self._samples]

    def _probe_cpu(self) -> Finding | None:
        warning = self._th("CPU_WARNING", settings.CPU_WARNING)
        critical = self._th("CPU_CRITICAL", settings.CPU_CRITICAL)
        sustained = int(self._th("CPU_SUSTAINED", settings.CPU_SUSTAINED))
        series = self._values("cpu_percent")
        latest = series[-1]

        if _consecutive_run(series, warning) < sustained:
            return None

        sev = _severity_for(latest, warning, critical)
        top = self._samples[-1].top_cpu
        return Finding(
            metric=METRIC_CPU,
            severity=sev,
            value=latest,
            threshold=warning if sev == SEV_WARNING else critical,
            samples=sustained,
            span_s=sustained * settings.SAMPLE_INTERVAL_S,
            top_processes=top,
            fingerprint=_fingerprint(METRIC_CPU, sev, top),
        )

    def _probe_ram(self) -> Finding | None:
        warning = self._th("RAM_WARNING", settings.RAM_WARNING)
        critical = self._th("RAM_CRITICAL", settings.RAM_CRITICAL)
        sustained = int(self._th("RAM_SUSTAINED", settings.RAM_SUSTAINED))
        series = self._values("ram_percent")
        latest = series[-1]

        # Critico imediato: RAM em >=critical e dor agora, nao espera
        # a janela sustained.
        if settings.RAM_CRITICAL_IMMEDIATE and latest >= critical:
            top = self._samples[-1].top_mem
            return Finding(
                metric=METRIC_RAM,
                severity=SEV_CRITICAL,
                value=latest,
                threshold=critical,
                samples=1,
                span_s=settings.SAMPLE_INTERVAL_S,
                top_processes=top,
                fingerprint=_fingerprint(METRIC_RAM, SEV_CRITICAL, top),
            )

        if _consecutive_run(series, warning) < sustained:
            return None

        top = self._samples[-1].top_mem
        return Finding(
            metric=METRIC_RAM,
            severity=SEV_WARNING,
            value=latest,
            threshold=warning,
            samples=sustained,
            span_s=sustained * settings.SAMPLE_INTERVAL_S,
            top_processes=top,
            fingerprint=_fingerprint(METRIC_RAM, SEV_WARNING, top),
        )

    def _probe_disk(self) -> Finding | None:
        warning = self._th("DISK_WARNING", settings.DISK_WARNING)
        critical = self._th("DISK_CRITICAL", settings.DISK_CRITICAL)
        latest = self._values("disk_percent")[-1]

        # Disco cheio nao e transitorio: dispara na hora (sustained=1).
        if latest < warning:
            return None

        sev = _severity_for(latest, warning, critical)
        return Finding(
            metric=METRIC_DISK,
            severity=sev,
            value=latest,
            threshold=warning if sev == SEV_WARNING else critical,
            samples=1,
            span_s=settings.SAMPLE_INTERVAL_S,
            top_processes=[],
            fingerprint=_fingerprint(METRIC_DISK, sev, []),
        )

    def _probe_io(self) -> Finding | None:
        warning = self._th("IO_WARNING", settings.IO_WARNING)
        critical = self._th("IO_CRITICAL", settings.IO_CRITICAL)
        sustained = int(self._th("IO_SUSTAINED", settings.IO_SUSTAINED))
        series = self._values("io_busy_percent")
        latest = series[-1]

        if _consecutive_run(series, warning) < sustained:
            return None

        sev = _severity_for(latest, warning, critical)
        top = self._samples[-1].top_cpu
        return Finding(
            metric=METRIC_IO,
            severity=sev,
            value=latest,
            threshold=warning if sev == SEV_WARNING else critical,
            samples=sustained,
            span_s=sustained * settings.SAMPLE_INTERVAL_S,
            top_processes=top,
            fingerprint=_fingerprint(METRIC_IO, sev, top),
        )

    def _probe_network(self) -> Finding | None:
        sustained = int(self._th("NET_SUSTAINED", settings.NET_SUSTAINED))
        ratio = self._th("NET_WARNING_RATIO", settings.NET_WARNING_RATIO)

        # Rede e relativa ao proprio historico: nao ha "byte/s absoluto"
        # que signifique anomalia num laptop e num servidor igual. Usa o
        # p95 da linha de base como teto; sem baseline suficiente, mudo.
        if len(self._net_total) < settings.MIN_SAMPLES_BEFORE_DETECT:
            return None

        baseline = _percentile(list(self._net_total), 95.0)
        if baseline <= 0:
            return None

        threshold = ratio * baseline
        latest = self._samples[-1].net_recv_bps + self._samples[-1].net_sent_bps

        totals = [
            s.net_recv_bps + s.net_sent_bps for s in self._samples
        ]
        if _consecutive_run(totals, threshold) < sustained:
            return None

        return Finding(
            metric=METRIC_NETWORK,
            severity=SEV_INFO,
            value=latest,
            threshold=threshold,
            samples=sustained,
            span_s=sustained * settings.SAMPLE_INTERVAL_S,
            top_processes=[],
            fingerprint=_fingerprint(METRIC_NETWORK, SEV_INFO, []),
        )

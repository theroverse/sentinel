from __future__ import annotations

# Indice de estagnacao ("stall"): distinguir "ocupado" de "travando".
#
# Recurso alto nao e prova de nada — build rodando a 100% de CPU e build
# rodando. O que muda o diagnostico e o atraso que a maquina passa a ter pra
# si mesma: o daemon que nao consegue dormir o tempo que pediu, o paginador
# que virou gargalo, o disco que mais ninguem consegue usar. Estes tres sao os
# sinais medidos aqui, e nenhum deles age — quem decide mexer no sistema e
# `relief` (fase D2), lendo o que esta medicao produziu.
#
# A regra do indice esta no spec residente, secao 4, e e ela que evita o
# falso-positivo: pressao (qualquer um dos tres) **e** um processo candidato
# em critico sustentado. Pressao sozinha e clima; critico sozinho e carga de
# trabalho que alguem pediu.
#
# Modulo puro: recebe `Sample` + `Finding`s + a duracao real do ultimo `sleep`
# e devolve `Incident`s. Nada aqui le psutil, abre processo ou toca em disco,
# entao a suite inteira roda com amostra fabricada.

import datetime
from dataclasses import dataclass, field

from sentinel import settings
from sentinel.detector import SEV_CRITICAL, SEV_WARNING, Finding
from sentinel.incidents import Incident
from sentinel.processctl import is_protected, is_self
from sentinel.sensor import Sample


# Metrica propria no mesmo contrato das outras de incidente: string estavel
# no JSONL, usada por `events --metric`, pela base (`kb`) e pelos filtros.
METRIC_STALL = "stall"

# Nomes dos sinais, na ordem canonica do detalhe do evento. Estavel porque e
# o que o tutorial cita ("a maquina nao conseguiu escalar a si mesma") e o
# que a base usa pra casar receita com sintoma.
SIGNAL_STARVED = "starved"
SIGNAL_THRASHING = "thrashing"
SIGNAL_DISK_SATURATED = "disk_saturated"


def _eligible(name: str) -> bool:
    """Nome que pode ser apontado como culpado?

    Servico do Windows e o proprio Sentinel ficam de fora do mesmo jeito que
    no `kill`: um svchost em critico nao e alvo de alivio, e o daemon que se
    auto-acusasse seria o pior vigilante possivel.
    """
    low = (name or "").lower()
    return bool(low) and not is_protected(low) and not is_self(low)


@dataclass(frozen=True)
class Culprit:
    """O processo candidato em critico: nome, pid e a metrica que o acusou."""

    name: str
    pid: int
    metric: str

    def to_dict(self) -> dict:
        return {"name": self.name, "pid": self.pid, "metric": self.metric}


@dataclass(frozen=True)
class StallSignals:
    """Leitura de um ciclo, em booleanos e nos numeros crus.

    Os numeros vao junto pro evento de proposito: a promessa do tutorial
    assertivo e citar o que foi medido ("o sleep de 2,0 s levou 4,3 s"), nao
    dizer "o sistema esta lento".
    """

    starved: bool = False
    thrashing: bool = False
    disk_saturated: bool = False
    culprit: Culprit | None = None

    sleep_s: float | None = None
    interval_s: float | None = None
    swap_percent: float = 0.0
    swap_activity_ps: float = 0.0
    io_busy_percent: float = 0.0

    @property
    def pressure(self) -> bool:
        """Algum dos tres gargalos esta ativo. Sozinho, nenhum deles basta."""
        return self.starved or self.thrashing or self.disk_saturated

    @property
    def stalled(self) -> bool:
        return self.pressure and self.culprit is not None

    @property
    def severity(self) -> str:
        """Qual sinal abriu o episodio decide o peso.

        Auto-inanicao (o daemon sem janela de CPU) e thrash sao a maquina sem
        folego; disco saturado com um culpado em critico ja e mais perto de
        "ninguem deveria estar usando isso agora" — grave, mas um degrau
        abaixo.
        """
        if self.starved or self.thrashing:
            return SEV_CRITICAL
        return SEV_WARNING

    @property
    def names(self) -> list[str]:
        out: list[str] = []
        if self.starved:
            out.append(SIGNAL_STARVED)
        if self.thrashing:
            out.append(SIGNAL_THRASHING)
        if self.disk_saturated:
            out.append(SIGNAL_DISK_SATURATED)
        return out

    def to_detail(self) -> dict:
        """O mapa `detail` da linha de anomalia (schema 2)."""
        return {
            "signals": self.names,
            "culprit": self.culprit.to_dict() if self.culprit else None,
            "measured": {
                "sleep_s": None if self.sleep_s is None else round(self.sleep_s, 3),
                "interval_s": (
                    None if self.interval_s is None else round(self.interval_s, 3)
                ),
                "swap_percent": round(self.swap_percent, 1),
                "swap_activity_ps": round(self.swap_activity_ps, 1),
                "io_busy_percent": round(self.io_busy_percent, 1),
            },
        }


@dataclass
class StallMonitor:
    """Ve os ciclos e abre/fecha episodios de estagnacao.

    Estado em campo, como no `TreeMonitor`: os sinais precisam ser
    SUSTENTADOS (o spec nao aceita um tick isolado como prova), e sustentacao
    e historico. `observe()` e chamado uma vez por ciclo do daemon.

    Um episodio = o intervalo continuo em que a regra valeu. O incidente sai
    na ENTRADA, nao a cada ciclo: dentro de um travamento o daemon amostra a
    0,5 s, e vinte linhas de `stall` no historico apagariam o resto da
    leitura. O que aconteceu durante o episodio fica na soma dele (`ticks`,
    `duration_s`, a uniao dos sinais), registrada no fechamento.
    """

    overrides: dict = field(default_factory=dict)

    _starve_run: int = field(default=0, init=False)
    _swap_run: int = field(default=0, init=False)
    _disk_run: int = field(default=0, init=False)
    _culprit: Culprit | None = field(default=None, init=False)
    _culprit_run: int = field(default=0, init=False)
    _episode: dict | None = field(default=None, init=False)

    # Ultima leitura, e o resumo do episodio que acabou de fechar: o daemon le
    # os dois pra escolher o intervalo do proximo tick e pra escrever a linha
    # certa no log.
    last: StallSignals | None = field(default=None, init=False)
    closed: dict | None = field(default=None, init=False)

    # -- limiares ------------------------------------------------------

    def _th(self, name: str, default: float) -> float:
        return settings.threshold(name, self.overrides, default)

    # -- API do daemon -------------------------------------------------

    @property
    def suspect(self) -> bool:
        """Val a pena amostrar mais rapido?

        Verdadeiro sob pressao OU dentro de um episodio aberto. E a "suspeita"
        do spec: reduzir o intervalo comeca antes da certeza, porque a certeza
        sem resolucao temporal nao sabe dizer quando o travamento passou.
        """
        if self._episode is not None:
            return True
        return self.last is not None and self.last.pressure

    @property
    def stalled(self) -> bool:
        return self._episode is not None

    # -- ciclo ---------------------------------------------------------

    def observe(
        self,
        sample: Sample,
        findings: list[Finding] | None = None,
        *,
        sleep_s: float | None = None,
        interval_s: float | None = None,
    ) -> list[Incident]:
        """Um ciclo do daemon. Devolve os incidentes abertos neste ciclo."""
        signals = self._read(sample, findings, sleep_s, interval_s)
        self.last = signals
        self.closed = None

        if not signals.stalled:
            self._close(sample)
            return []

        if self._episode is not None:
            self._absorb(signals)
            return []

        self._episode = {
            "started": sample.ts,
            "signals": list(signals.names),
            "ticks": 1,
        }
        return [self._incident(signals)]

    # -- leitura -------------------------------------------------------

    def _read(
        self,
        sample: Sample,
        findings: list[Finding] | None,
        sleep_s: float | None,
        interval_s: float | None,
    ) -> StallSignals:
        """Atualiza as corridas sustentadas e devolve a leitura do ciclo."""
        factor = self._th("STALL_STARVE_FACTOR", settings.STALL_STARVE_FACTOR)
        starved_now = (
            sleep_s is not None
            and interval_s is not None
            and interval_s > 0
            and sleep_s >= interval_s * factor
        )
        self._starve_run = self._starve_run + 1 if starved_now else 0

        swap_run_now = (
            sample.swap_activity_ps
            >= self._th("STALL_SWAP_RATE_PS", settings.STALL_SWAP_RATE_PS)
            or sample.swap_percent
            >= self._th("STALL_SWAP_PERCENT", settings.STALL_SWAP_PERCENT)
        )
        self._swap_run = self._swap_run + 1 if swap_run_now else 0

        disk_now = (
            sample.io_busy_percent
            >= self._th("STALL_DISK_BUSY", settings.STALL_DISK_BUSY)
        )
        self._disk_run = self._disk_run + 1 if disk_now else 0

        culprit = self._track_culprit(findings or [])

        return StallSignals(
            starved=self._starve_run >= settings.STALL_SIGNAL_SUSTAINED,
            thrashing=self._swap_run >= settings.STALL_SIGNAL_SUSTAINED,
            disk_saturated=self._disk_run >= settings.STALL_DISK_SUSTAINED,
            culprit=culprit,
            sleep_s=sleep_s,
            interval_s=interval_s,
            swap_percent=sample.swap_percent,
            swap_activity_ps=sample.swap_activity_ps,
            io_busy_percent=sample.io_busy_percent,
        )

    def _track_culprit(self, findings: list[Finding]) -> Culprit | None:
        """O mesmo candidato em critico por N ciclos seguidos.

        Sustenta por NOME, nao por "qualquer critico": se a RAM acusou o
        navegador num tick e o disco acusou o indexador no seguinte, nao ha um
        processo travando a maquina — ha dois ocupados. O alivio (D2) precisa
        de um alvo, e alvo que muda a cada ciclo nao e alvo.
        """
        candidate: Culprit | None = None
        for finding in findings:
            if finding.severity != SEV_CRITICAL:
                continue
            if not finding.top_processes:
                continue
            proc = finding.top_processes[0]
            if not _eligible(proc.name):
                continue
            candidate = Culprit(name=proc.name, pid=proc.pid, metric=finding.metric)
            break

        if candidate is None:
            self._culprit = None
            self._culprit_run = 0
            return None

        if self._culprit is not None and self._culprit.name == candidate.name:
            self._culprit_run += 1
        else:
            self._culprit = candidate
            self._culprit_run = 1

        if self._culprit_run >= settings.STALL_CULPRIT_SUSTAINED:
            return candidate
        return None

    # -- episodio ------------------------------------------------------

    def _absorb(self, signals: StallSignals) -> None:
        """Conta o ciclo no episodio aberto e junta os sinais vistos."""
        episode = self._episode
        if episode is None:  # pragma: no cover - garantido pelo chamador
            return
        episode["ticks"] += 1
        for name in signals.names:
            if name not in episode["signals"]:
                episode["signals"].append(name)

    def _close(self, sample: Sample) -> None:
        """Fecha o episodio e guarda o resumo pro log do daemon.

        Zera as corridas junto: sem isso, um episodio que acabou de fechar
        reabriria no tick seguinte com o historico do anterior, e o
        intervalo rapido nunca voltaria ao normal.
        """
        episode = self._episode
        if episode is None:
            return
        started = episode["started"]
        duration = None
        if isinstance(started, datetime.datetime) and isinstance(
            sample.ts, datetime.datetime
        ):
            duration = round((sample.ts - started).total_seconds(), 1)
        self.closed = {
            "started": started,
            "duration_s": duration,
            "ticks": episode["ticks"],
            "signals": list(episode["signals"]),
        }
        self._episode = None
        self._starve_run = 0
        self._swap_run = 0
        self._disk_run = 0
        self._culprit = None
        self._culprit_run = 0

    # -- incidente -----------------------------------------------------

    def _incident(self, signals: StallSignals) -> Incident:
        severity = signals.severity
        culprit = signals.culprit
        parts = ", ".join(_phrase(name) for name in signals.names)
        label = (
            f"estagnacao: {culprit.name} em critico ({culprit.metric}) com {parts}"
            if culprit
            else f"estagnacao: {parts}"
        )
        return Incident(
            metric=METRIC_STALL,
            severity=severity,
            detail=signals.to_detail(),
            fingerprint=f"{METRIC_STALL}:{severity}:{culprit.name if culprit else '-'}",
            label=label,
        )


def _phrase(signal: str) -> str:
    """O sinal em uma frase, pra linha de log e pro `label` do evento.

    Escrita pra quem le o `daemon.log` as 2h da manha sem abrir o JSONL.
    """
    if signal == SIGNAL_STARVED:
        return "o proprio daemon nao foi escalado no tempo pedido"
    if signal == SIGNAL_THRASHING:
        return "paginacao em ritmo de gargalo"
    if signal == SIGNAL_DISK_SATURATED:
        return "disco saturado"
    return signal

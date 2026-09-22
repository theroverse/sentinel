from __future__ import annotations

import datetime
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from sentinel import settings
from sentinel.detector import Detector, Finding
from sentinel.events import EventStore
from sentinel.sensor import Sensor, Sample
from sentinel.stall import StallMonitor


class AlreadyRunning(RuntimeError):
    pass


class NotRunning(RuntimeError):
    pass


@dataclass
class DaemonStatus:
    running: bool
    pid: int | None = None
    last_heartbeat: datetime.datetime | None = None
    paused: bool = False


def _read_pid(paths: settings.Paths) -> int | None:
    try:
        text = paths.pid.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def pid_alive(pid: int) -> bool:
    """Heuristica multiplataforma de 'este pid esta vivo.'

    POSIX: signal 0 nao mata, so testa permissao/existencia. Windows: sem
    signal util, entao abre o processo via OpenProcess do `tasklist`? — mais
    leve e barato e perguntar ao psutil. Como psutil ja e dependencia de
    runtime, usa-lo aqui e de graca e evita falsos-positivos por pid
    reusado.
    """
    try:
        import psutil

        return psutil.pid_exists(pid)
    except Exception:
        # Sem psutil (ex.: ambiente minimo de teste): assume morto so se o
        # pidfile sumir; aqui devolve False pra nao travar `stop`.
        try:
            os_kill_zero(pid)
            return True
        except Exception:
            return False


def os_kill_zero(pid: int) -> None:
    if sys.platform == "win32":
        raise NotImplementedError("signal 0 indisponivel no Windows")
    os_signal(pid, 0)


def os_signal(pid: int, sig: int) -> None:
    import os

    os.kill(pid, sig)


def status(paths: settings.Paths) -> DaemonStatus:
    # A pausa e lida mesmo com o daemon morto: ela mora num arquivo, nao na
    # cabeca do processo, entao sobrevive a reboot e a um `start` novo (que e
    # justamente o ponto — pausar sem GUI nao pode depender do daemon viver).
    paused = is_paused(paths)
    pid = _read_pid(paths)
    if pid is None:
        return DaemonStatus(running=False, paused=paused)

    if not pid_alive(pid):
        # pidfile obsoleto (crash/machine reboot): trata como nao rodando,
        # mas NAO apaga sozinho — quem apaga e `start`/`stop`, pra evitar
        # corrida entre dois processos lendo isso.
        return DaemonStatus(running=False, pid=pid, paused=paused)

    heartbeat = _read_heartbeat(paths)
    return DaemonStatus(running=True, pid=pid, last_heartbeat=heartbeat, paused=paused)


def _read_heartbeat(paths: settings.Paths) -> datetime.datetime | None:
    try:
        text = paths.daemon_log.read_text(encoding="utf-8")
    except OSError:
        return None
    # Última linha com um ISO parseável é o batimento mais recente.
    last = None
    for line in text.splitlines():
        stamp = line[:32].strip()
        try:
            last = datetime.datetime.fromisoformat(stamp)
        except ValueError:
            continue
    return last


def start(paths: settings.Paths) -> int:
    """Lanca o daemon como processo filho destacado e grava o pid.

    Retorna o pid do filho. Levanta AlreadyRunning se ja ha um vivo.
    """
    current = status(paths)
    if current.running:
        raise AlreadyRunning(f"daemon ja rodando (pid {current.pid})")

    paths.ensure_output_dir()

    cmd = [
        sys.executable,
        str(_entry_script()),
        "__daemon-run",
        "--dir",
        str(paths.root),
    ]

    kwargs: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform == "win32":
        # Destaca do console/pai: DETACHED_PROCESS + novo grupo, senao o
        # filho morre quando o `sentinel start` retorna.
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
        kwargs["creationflags"] = flags
    else:
        kwargs["start_new_session"] = True

    proc = subprocess.Popen(cmd, **kwargs)  # noqa: S603 (argv controlado)

    paths.pid.write_text(str(proc.pid), encoding="utf-8")
    return proc.pid


def stop(paths: settings.Paths) -> int:
    """Pede shutdown ao daemon e remove o pidfile. Retorna o pid parado."""
    current = status(paths)
    if not current.running or current.pid is None:
        raise NotRunning("daemon nao esta rodando")

    pid = current.pid
    try:
        if sys.platform == "win32":
            # Windows: sem SIGTERM. terminate() do psutil chama
            # TerminateProcess — encerramento abrupto, mas o loop do daemon
            # so escreve de forma atomica (append/replace), entao nao ha
            # estado corrompido pra preservar.
            import psutil

            psutil.Process(pid).terminate()
        else:
            os_signal(pid, signal.SIGTERM)
    except Exception:
        # Processo ja morreu entre o status e o kill: considera parado.
        pass

    try:
        paths.pid.unlink()
    except OSError:
        pass
    return pid


def _entry_script() -> Path:
    """Caminho do sentinel.py lancador (o bootstrap na raiz do repo).

    Em execucao normal `__main__` e sentinel.py; quando chamado como
    modulo, cai no irmao ../sentinel.py relativo ao pacote.
    """
    pkg_dir = Path(__file__).resolve().parent  # .../src/sentinel
    candidate = pkg_dir.parents[1] / "sentinel.py"  # .../sentinel.py
    if candidate.is_file():
        return candidate
    main_module = sys.modules.get("__main__")
    main_file = getattr(main_module, "__file__", None)
    return Path(main_file).resolve() if main_file else candidate


# ----------------------------------------------------------------------
# Loop de vigilancia (nucleo testavel, sem subprocess)
# ----------------------------------------------------------------------
def is_paused(paths: settings.Paths) -> bool:
    """Existe `.sentinel/paused`? Só a existência manda; o conteúdo é
    diagnóstico pra quem lê o log.

    `OSError` conta como não-pausado porque é o estado de sempre (arquivo
    nunca criado). O inverso — um erro qualquer virar "pausado" — desligaria
    a vigilância inteira, silenciosamente, num disco cheio.
    """
    try:
        return paths.paused.is_file()
    except OSError:
        return False


def paused_since(paths: settings.Paths) -> datetime.datetime | None:
    """Quando a pausa começou, ou None se não há pausa (ou o conteúdo não é um
    ISO legível). O timestamp é conveniência: a pausa vale pelo arquivo."""
    if not is_paused(paths):
        return None
    try:
        text = paths.paused.read_text(encoding="utf-8-sig").strip()
    except OSError:
        return None
    if not text:
        return None
    try:
        return datetime.datetime.fromisoformat(text.splitlines()[0].strip())
    except ValueError:
        return None


def pause(paths: settings.Paths, *, now: datetime.datetime | None = None) -> None:
    """Grava o arquivo de pausa com o instante (UTC) em que começou."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    paths.ensure_output_dir()
    paths.paused.write_text(_iso(now) + "\n", encoding="utf-8", newline="\n")


def resume(paths: settings.Paths) -> bool:
    """Apaga a pausa. Devolve True se havia alguma pausa pra apagar — assim o
    CLI diz 'nada pausado' em vez de fingir que retomou algo."""
    try:
        paths.paused.unlink()
    except FileNotFoundError:
        return False
    except OSError:
        return False
    return True


def build_incident_sources() -> list:
    """Monitores de incidente do daemon: arvore de processos + falha de app.

    Construidos aqui (e nao dentro de `run_watch_loop`) por duas razoes: o
    loop continua deterministico e injetavel pra teste — nenhum teste de
    suite real precisa lancar `wevtutil` nem varrer os 300 processos da
    maquina — e a ausencia de psutil nao derruba a vigilancia: sem ele so
    perdem os incidentes, as metricas seguem.
    """
    from sentinel.appfail import AppFailureReader
    from sentinel.incidents import TreeMonitor

    sources: list = []
    try:
        sources.append(TreeMonitor())
    except Exception:  # psutil ausente/quebrado
        pass
    sources.append(AppFailureReader())
    return sources


def run_watch_loop(
    paths: settings.Paths,
    *,
    sensor: Sensor | None = None,
    store: EventStore | None = None,
    detector: Detector | None = None,
    incident_sources: list | None = None,
    stall: StallMonitor | None = None,
    interval: float | None = None,
    sleep=time.sleep,
    clock=time.monotonic,
    stop_after: int | None = None,
    on_sample=None,
) -> int:
    """Loop principal: amostra -> detecta -> registra. Retorna nº de ticks.

    Totalmente injetavel (sensor/store/detector/sleep) pra testes rodarem
    o ciclo inteiro sem psutil real, sem wall-clock e sem disco fora de um
    tmp_path. `stop_after` encerra apos N ticks (usado nos testes e por
    `watch` uma-shot); None = roda ate KeyboardInterrupt/SIGTERM.

    `incident_sources` é a lista de monitores que não medem recurso (arvore
    órfã, queda de app). Vazio por padrão de propósito: quem quer a
    vigilância completa chama `build_incident_sources()` — assim o loop
    nunca abre processo filho nem lê o Event Log por conta propria num
    contexto de teste.

    `stall` mede a estagnacao a cada ciclo e faz duas coisas com o loop:
    encurta o proprio intervalo sob suspeita (`SAMPLE_INTERVAL_FAST_S`) e
    entrega o incidente do episodio quando ele abre. Roda mesmo sem os
    monitores de incidente — e so aritmetica sobre o que ja foi amostrado.

    `clock` mede quanto o `sleep(interval)` *realmente* demorou; e dai que
    sai o sinal de auto-inanição. O padrao e `time.monotonic`, e um teste
    que injeta `sleep` falso continua deterministico: dormir de mentirinha
    nao atrasa nada.

    Pausado (`.sentinel/paused`) e mudo, nao fila: o sensor continua
    amostrando e os monitores continuam consumindo o proprio estado — a
    diferenca entre um processo vivo e um morto so existe naquele par de
    batimentos. O que aconteceu durante a pausa nao e recuperado no
    `resume`, e o detector segue acumulando pra que a sustentacao esteja
    certa no primeiro tick livre.
    """
    sensor = sensor or Sensor()
    store = store or EventStore(paths.events)
    detector = detector or Detector(settings.load_overrides(paths))
    sources = list(incident_sources or ())
    interval = interval if interval is not None else settings.SAMPLE_INTERVAL_S

    overrides = settings.load_overrides(paths)
    detector.overrides = overrides
    stall = stall or StallMonitor(overrides=overrides)

    store.path.parent.mkdir(parents=True, exist_ok=True)

    ticks = 0
    # None no primeiro tick: o estado e gravado no log mesmo sem transicao,
    # pra um buraco no historico nunca comecar sem explicacao.
    was_paused: bool | None = None
    # Duracao real do ultimo `sleep`, e o intervalo pedido antes dele. O
    # primeiro ciclo nao tem historico de sono — nem sinal de inanicao.
    last_sleep_s: float | None = None
    current = interval
    try:
        while True:
            sample = sensor.sample()
            paused = is_paused(paths)
            if paused != was_paused:
                _log_pause(paths, sample, paused)
                was_paused = paused
            findings = detector.observe(sample)
            incidents: list = []
            for source in sources:
                incidents.extend(_observe_incidents(source, sample))
            incidents.extend(
                _observe_stall(
                    stall,
                    sample,
                    findings,
                    sleep_s=last_sleep_s,
                    interval_s=current,
                )
            )
            if not paused:
                for finding in findings:
                    _persist(store, paths, finding, sample)
                for incident in incidents:
                    _persist_incident(store, paths, incident, sample)
            if stall.closed is not None:
                _log_stall_clear(paths, sample, stall.closed)
            _heartbeat(paths, sample, paused=paused, stalled=stall.stalled)
            if on_sample is not None:
                on_sample(sample, findings)
            ticks += 1
            if stop_after is not None and ticks >= stop_after:
                return ticks
            current = (
                settings.SAMPLE_INTERVAL_FAST_S
                if stall.suspect
                else interval
            )
            before = clock()
            sleep(current)
            last_sleep_s = clock() - before
    except (KeyboardInterrupt, SystemExit):
        return ticks


def _log_pause(paths: settings.Paths, sample: Sample, paused: bool) -> None:
    """Marca a virada no log. Sem ela, um buraco no historico parece bug de
    sensor — e a pergunta 'quando isso foi pausado?' e a primeira que se faz
    depois."""
    state = "PAUSADO" if paused else "ATIVO"
    _append_daemon_line(
        paths,
        f"{_iso(sample.ts)} VIGILANCIA {state} "
        f"(arquivo {settings.PAUSED_FILENAME})"
        + ("" if not paused else " — nada novo sera registrado ate 'sentinel resume'"),
    )


def _observe_incidents(source, sample: Sample) -> list:
    """Um monitor de incidente, protegido: arvore órfã e queda de app são
    vigilância extra, e um `AccessDenied` no meio de um snapshot não tem o
    direito de derrubar o loop que mede CPU."""
    try:
        return list(source.observe(sample.ts))
    except Exception:
        return []


def _observe_stall(
    stall: StallMonitor,
    sample: Sample,
    findings: list,
    *,
    sleep_s: float | None,
    interval_s: float | None,
) -> list:
    """Indice de estagnacao, protegido igual aos outros monitores.

    O `observe()` do stall nao faz I/O, mas recebe `Finding`s de fora e um
    dia desses recebe tambem a janela pendurada (ctypes): uma excecao ali
    nao pode custar a amostragem de CPU, que e o motivo do loop existir.
    """
    try:
        return list(
            stall.observe(sample, findings, sleep_s=sleep_s, interval_s=interval_s)
        )
    except Exception:
        return []


def _log_stall_clear(paths: settings.Paths, sample: Sample, episode: dict) -> None:
    """Fim do episodio, com a duracao e os sinais que o abriram.

    Sem esta linha, o historico mostra uma anomalia `stall` e nada que diga
    quando ela parou — e 'parou sozinho ou eu que resolvi?' e exatamente a
    pergunta que decide se o degrau 1 merece existir (fase D2).
    """
    duration = episode.get("duration_s")
    spent = "?" if duration is None else f"{duration:.1f}s"
    signals = ", ".join(episode.get("signals") or ()) or "-"
    _append_daemon_line(
        paths,
        f"{_iso(sample.ts)} ESTAGNACAO CESSOU dur={spent} "
        f"ticks={episode.get('ticks', 0)} sinais={signals}",
    )


def _persist_incident(
    store: EventStore, paths: settings.Paths, incident, sample: Sample
) -> None:
    event = store.record_incident(incident, now=sample.ts)
    line = (
        f"{_iso(sample.ts)} ANOMALIA {incident.metric} {incident.severity} "
        f"occ={event.get('occurrences', 1)} status={event.get('status')} "
        f"id={event.get('id')} :: {incident.label}"
    )
    _append_daemon_line(paths, line)


def _persist(store: EventStore, paths: settings.Paths, finding: Finding, sample: Sample) -> None:
    event = store.record_finding(finding, sample)
    line = (
        f"{_iso(sample.ts)} ANOMALIA {finding.metric} {finding.severity} "
        f"value={finding.value:.1f} thr={finding.threshold:.1f} "
        f"status={event.get('status')} id={event.get('id')}"
    )
    _append_daemon_line(paths, line)


def _heartbeat(
    paths: settings.Paths,
    sample: Sample,
    *,
    paused: bool = False,
    stalled: bool = False,
) -> None:
    flag = " paused=1" if paused else ""
    flag += " stall=1" if stalled else ""
    line = (
        f"{_iso(sample.ts)} tick cpu={sample.cpu_percent:.1f} "
        f"ram={sample.ram_percent:.1f} disk={sample.disk_percent:.1f} "
        f"io={sample.io_busy_percent:.1f} "
        f"swap={sample.swap_percent:.1f} swap_rate={sample.swap_activity_ps:.0f} "
        f"net_down_bps={sample.net_recv_bps:.0f} net_up_bps={sample.net_sent_bps:.0f}"
        f"{flag}"
    )
    _append_daemon_line(paths, line)


def _append_daemon_line(paths: settings.Paths, line: str) -> None:
    try:
        paths.ensure_output_dir()
        with paths.daemon_log.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(line + "\n")
    except OSError:
        # Log e diagnostico; falhar o daemon por nao conseguir escrever o
        # log seria pior que perder a linha.
        pass


def _iso(dt: datetime.datetime) -> str:
    return dt.astimezone(datetime.timezone.utc).isoformat()

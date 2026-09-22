"""Saida para maquina: o que a GUI e um agente leem sem parser de texto.

A fase 0 da spec da GUI (docs/superpowers/specs/2026-09-22-sentinel-gui-design.md)
exige que todo dado que a interface mostra exista num endpoint JSON do proprio
CLI. Este modulo e essa camada: ele so reorganiza o que os modulos de medicao
ja sabem (`sensor`, `daemon`, `events`, `kb`, `processctl`) e nao inventa
regra nenhuma — limiar, severidade, lista de protecao e recusa continuam
morando no Python que a interface chama, nunca aqui.

Por que as formas sao as do `gui/sentinel/mock.js`: o mock espelha
`sensor.Sample`, `detector.Finding` e as linhas do `events.jsonl`. Manter as
duas iguais e o que permite a GUI ligar no motor sem reescrever nenhum
renderizador.
"""

from __future__ import annotations

import datetime
import json
import re
import time
from pathlib import Path

from sentinel import settings
from sentinel.events import (
    OUTCOME_DISMISSED,
    OUTCOME_FIXED,
    OUTCOME_NOT_FIXED,
    STATUS_ADDRESSING,
    STATUS_DISMISSED,
    STATUS_RESOLVED,
    EventStore,
)


# Uma linha de batimento do daemon: "<iso> tick cpu=38.4 ram=76.1 ...". O
# resto (ANOMALIA, ALIVIO, ESTAGNACAO CESSOU) e texto pra quem le o log.
_TICK_FIELDS = re.compile(
    r"cpu=(?P<cpu>[\d.]+)\s+ram=(?P<ram>[\d.]+)\s+disk=(?P<disk>[\d.]+)"
    r"\s+io=(?P<io>[\d.]+)"
    r"(?:\s+swap=(?P<swap>[\d.]+))?"
    r"(?:\s+swap_rate=(?P<swap_rate>[\d.]+))?"
    r"(?:\s+net_down_bps=(?P<down>[\d.]+))?"
    r"(?:\s+net_up_bps=(?P<up>[\d.]+))?"
)

# Quantas linhas do fim do log ler numa chamada. O log nao e rotacionado,
# entao "ler tudo" seria abrir um arquivo de semanas a cada 2 s de poll.
_TAIL_LINES = 600


# --------------------------------------------------------------------- log --
def _tail(path: Path, *, max_lines: int = _TAIL_LINES) -> list[str]:
    """Ultimas `max_lines` linhas de um arquivo, sem carregar o inteiro.

    Ler o `daemon.log` todo custaria o dobro a cada pergunta: o arquivo e
    append-only e cresce com o daemon ligado (um batimento a cada 2 s sao
    ~43 mil linhas/dia). Lê só o rabo, em blocos que dobram ate caber o
    tanto de linhas pedido.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return []

    chunk = 8192
    buf = b""
    try:
        with path.open("rb") as fh:
            pos = size
            need = chunk
            while pos > 0 and buf.count(b"\n") <= max_lines:
                take = min(need, pos)
                pos -= take
                fh.seek(pos)
                buf = fh.read(take) + buf
                need *= 4
    except OSError:
        return []
    return buf.decode("utf-8", "replace").splitlines()[-max_lines:]


def _split_stamp(line: str) -> tuple[datetime.datetime | None, str]:
    """Separa o ISO que o daemon pe na frente de cada linha do resto."""
    stamp, _, rest = line.partition(" ")
    try:
        return datetime.datetime.fromisoformat(stamp), rest
    except ValueError:
        return None, line


def _read_ticks(paths: settings.Paths, *, history: int) -> list[dict]:
    """Os batimentos mais recentes, na ordem antiga->nova.

    Historico e o que o processo do CLI nao tem: ele nasce, responde e morre.
    As series que a GUI mostra, entao, vem do que o daemon mediu e gravou —
    a mesma fonte do `status`, nao uma segunda medicao divergente.
    """
    rows: list[dict] = []
    for line in _tail(paths.daemon_log):
        ts, rest = _split_stamp(line)
        if ts is None or not rest.startswith("tick "):
            continue
        m = _TICK_FIELDS.search(rest)
        if not m:  # pragma: no cover - linha tick sem campos nao e emitida
            continue
        rows.append(
            {
                "ts": ts,
                "cpu": float(m.group("cpu")),
                "ram": float(m.group("ram")),
                "disk": float(m.group("disk")),
                "io": float(m.group("io")),
                "swap": float(m.group("swap") or 0.0),
                "swap_rate": float(m.group("swap_rate") or 0.0),
                "down": float(m.group("down") or 0.0),
                "up": float(m.group("up") or 0.0),
                "stalled": "stall=1" in rest,
                "paused": "paused=1" in rest,
            }
        )
    return rows[-history:] if history else rows


def series_for(paths: settings.Paths, *, history: int = 60) -> dict:
    """As cinco janelas de plot, com a unidade que a GUI ja conhece.

    `net` e o recebido em Mbit/s, nao a soma dos dois lados: e o numero que o
    medidor mostra, e um sparkline de outra grandeza ao lado dele seria
    enfeite, nao evidencia.
    """
    ticks = _read_ticks(paths, history=history)
    cols = {
        "cpu": ([t["cpu"] for t in ticks], "%"),
        "ram": ([t["ram"] for t in ticks], "%"),
        "disk": ([t["disk"] for t in ticks], "%"),
        "io": ([t["io"] for t in ticks], "%"),
        "net": ([t["down"] * 8.0 / 1e6 for t in ticks], "Mbit"),
    }
    return {
        key: {"points": [round(v, 2) for v in points], "unit": unit}
        for key, (points, unit) in cols.items()
    }


def log_lines(paths: settings.Paths, *, limit: int = 60) -> list[dict]:
    """O rabo do `daemon.log` mais novo primeiro, com o timestamp já partido.

    Toda linha que o daemon escreve comeca com um ISO — batimento, anomalia,
    intervencao. As que nao tem (restos de escrita, arquivo editado a mao)
    vao com `ts` vazio em vez de sumir: esconder uma linha ileivel seria
    apagar evidencia.
    """
    rows: list[dict] = []
    for line in _tail(paths.daemon_log)[-limit:]:
        ts, rest = _split_stamp(line)
        rows.append({"ts": ts.isoformat() if ts else "", "text": rest})
    rows.reverse()
    return rows


# ------------------------------------------------------------------- config --
def thresholds(paths: settings.Paths) -> dict:
    """Os limiares ativos (padrao do codigo + override do `config.json`).

    A GUI nao tem numeros proprios: ela mostra o que o detector vai usar. Se
    este dict divergir do `Detector`, a interface esta mentindo sobre a regra.
    """
    ov = settings.load_overrides(paths)

    def g(name: str, default: float) -> float:
        return settings.threshold(name, ov, default)

    return {
        "cpu": {
            "warning": g("CPU_WARNING", settings.CPU_WARNING),
            "critical": g("CPU_CRITICAL", settings.CPU_CRITICAL),
            "sustained": int(g("CPU_SUSTAINED", settings.CPU_SUSTAINED)),
        },
        "ram": {
            "warning": g("RAM_WARNING", settings.RAM_WARNING),
            "critical": g("RAM_CRITICAL", settings.RAM_CRITICAL),
            "sustained": int(g("RAM_SUSTAINED", settings.RAM_SUSTAINED)),
        },
        "disk": {
            "warning": g("DISK_WARNING", settings.DISK_WARNING),
            "critical": g("DISK_CRITICAL", settings.DISK_CRITICAL),
            "sustained": int(g("DISK_SUSTAINED", settings.DISK_SUSTAINED)),
        },
        "io": {
            "warning": g("IO_WARNING", settings.IO_WARNING),
            "critical": g("IO_CRITICAL", settings.IO_CRITICAL),
            "sustained": int(g("IO_SUSTAINED", settings.IO_SUSTAINED)),
        },
        "network": {
            "warning_ratio": g("NET_WARNING_RATIO", settings.NET_WARNING_RATIO),
            "sustained": int(g("NET_SUSTAINED", settings.NET_SUSTAINED)),
        },
    }


# ------------------------------------------------------------------- daemon --
def daemon_state(paths: settings.Paths) -> dict:
    """Vivo? desde quando? pausado? sombra? — o estado que a titlebar mostra.

    O instante de partida vem do pidfile, nao de um cache: o daemon grava o
    proprio pid ao subir, entao a hora de modificacao do arquivo e a hora em
    que ele subiu (com a imprecisao de um `start`, que e o que interessa).
    """
    from sentinel import daemon, orders as orders_mod

    st = daemon.status(paths)
    started = None
    if st.running:
        try:
            mtime = datetime.datetime.fromtimestamp(
                paths.pid.stat().st_mtime, tz=datetime.timezone.utc
            )
            started = mtime.isoformat()
        except OSError:
            started = None
    return {
        "running": st.running,
        "pid": st.pid,
        "last_heartbeat": st.last_heartbeat.isoformat() if st.last_heartbeat else None,
        "started_ts": started,
        "interval_s": settings.SAMPLE_INTERVAL_S,
        "paused": st.paused,
        "shadow": orders_mod.load(paths).shadow,
    }


# ------------------------------------------------------------------ eventos --
def _anomaly_row(event: dict) -> dict:
    """Uma linha do historico, garantindo o que a GUI Indexa sem existir.

    As anomalias de incidente (`stall`, `app_failure`, `orphan_tree`) sao de
    schema 2 e nao tem `value`/`threshold`/`window`/`top_processes`: quem
    escreve e `EventStore.build_incident_record`. Em vez de obrigar a GUI a
    saber quais metricas tem numero, a saida de maquina normaliza — o campo
    aparece, vazio quando a natureza do evento nao o tem.
    """
    row = dict(event)
    row.setdefault("top_processes", [])
    row.setdefault("window", {"samples": 0, "span_s": 0.0})
    row.setdefault("value", None)
    row.setdefault("threshold", None)
    row.setdefault("status", "open")
    row.setdefault("occurrences", 1)
    row.setdefault("ts_last", row.get("ts", ""))
    return row


def _newest_first(rows: list[dict], *, limit: int) -> list[dict]:
    return rows[::-1][:limit] if limit else rows[::-1]


def event_rows(paths: settings.Paths, *, limit: int = 60) -> list[dict]:
    store = EventStore(paths.events)
    return _newest_first([_anomaly_row(e) for e in store.anomalies()], limit=limit)


def resolution_rows(paths: settings.Paths, *, limit: int = 30) -> list[dict]:
    store = EventStore(paths.events)
    rows = [e for e in store.all() if e.get("kind") == "resolution"]
    return _newest_first(rows, limit=limit)


def intervention_rows(paths: settings.Paths, *, limit: int = 30) -> list[dict]:
    rows = EventStore(paths.events).interventions()
    return _newest_first(rows, limit=limit)


# ---------------------------------------------------------------- amostra --
def _sample_dict(sample) -> dict:
    """`sensor.Sample` -> o formato do `sample` do mock, um a um.

    O `Sample` nao tem `to_dict` (e uma serie, nao um registro), e a GUI nao
    conhece dataclass: a traducao mora aqui, num lugar so.
    """
    return {
        "ts": sample.ts.isoformat(),
        "cpu_percent": round(sample.cpu_percent, 1),
        "ram_percent": round(sample.ram_percent, 1),
        "disk_percent": round(sample.disk_percent, 1),
        "disk_path": sample.disk_path,
        "io_busy_percent": round(sample.io_busy_percent, 1),
        "net_recv_bps": round(sample.net_recv_bps, 0),
        "net_sent_bps": round(sample.net_sent_bps, 0),
        "swap_percent": round(sample.swap_percent, 1),
        "swap_activity_ps": round(sample.swap_activity_ps, 0),
        "top_cpu": [p.to_dict() for p in sample.top_cpu],
        "top_mem": [p.to_dict() for p in sample.top_mem],
    }


def live_sample(*, settle_s: float | None = None, sleeper=time.sleep) -> dict:
    """Uma medicao feita agora, por este processo, sem depender do daemon.

    O psutil so devolve uso real na SEGUNDA leitura de um contador (a primeira
    arma o delta). Por isso o `Sensor` nao-bloqueante e um loop que dorme
    `intervalo` entre ticks: um CLI que roda uma vez e sai precisaria de dois
    ticks, e a janela entre eles e o `METRICS_SETTLE_S`. Dormir 0,6 s numa
    pergunta de interface e o preco de responder com numero medido em vez de
    0.0 inventado.
    """
    from sentinel.sensor import Sensor

    wait = settings.METRICS_SETTLE_S if settle_s is None else settle_s
    sensor = Sensor()
    sensor.sample(top=False)  # arma cpu/io/net/swap; o valor e descartavel
    if wait > 0:
        sleeper(wait)
    return _sample_dict(sensor.sample())


def process_rows(sample: dict, *, limit: int = 25) -> list[dict]:
    """A tabela de processos da GUI, com as travas marcadas por quem manda.

    `protected` e `self` vem de `processctl.is_protected`/`is_self` — as
    mesmas funcoes que o `kill` consulta antes de tocar em qualquer coisa. A
    lista mostra os protegidos em vez de esconde-los: esconder faria parecer
    que dava para encerrar, e a recusa e a informação mais útil ali.
    """
    from sentinel.processctl import is_protected, is_self

    child_counts = _child_counts()
    rows: list[dict] = []
    seen: set[int] = set()
    for key in ("top_cpu", "top_mem"):
        for proc in sample.get(key, []):
            pid = proc["pid"]
            if pid in seen:
                continue
            seen.add(pid)
            rows.append(
                {
                    "pid": pid,
                    "name": proc["name"],
                    "cpu": round(proc["cpu"], 1),
                    "rss_mb": round(proc["rss_mb"], 1),
                    "protected": is_protected(proc["name"]),
                    "self": is_self(proc["name"]),
                    "children": child_counts.get(pid, 0),
                }
            )
    rows.sort(key=lambda r: r["cpu"], reverse=True)
    return rows[:limit]


def _child_counts() -> dict[int, int]:
    """Quantos processos cada pai tem — só o numero, nenhum caminho.

    Fica vazio sem psutil: a coluna "Dependentes" e diagnostico do modal de
    confirmacao, e nao ha motivo para uma maquina sem psutil nao responder a
    pergunta nenhuma.
    """
    try:
        import psutil
    except Exception:  # ImportError e tambem ambiente quebrado
        return {}
    counts: dict[int, int] = {}
    try:
        for proc in psutil.process_iter(attrs=["ppid"]):
            ppid = proc.info.get("ppid")
            if ppid is None:
                continue
            counts[ppid] = counts.get(ppid, 0) + 1
    except Exception:
        return counts
    return counts


# -------------------------------------------------------------------- base --
def kb_catalog() -> dict:
    """As opcoes curadas por metrica (`kb.options_for`), sem evento.

    Sem evento os tokens `{...}` nao tem o que preencher, e o conteudo sai
    com eles literais: o catalogo do painel e um mapa do que a base sabe. O
    tutorial de verdade pede `fix --plan` para UMA anomalia, e la os tokens
    estao bindados (`kb.bind`).
    """
    from sentinel import kb

    return {metric: kb.options_for(metric) for metric in kb.known_metrics()}


# --------------------------------------------------------------- dashboard --
def dashboard(
    paths: settings.Paths,
    *,
    events_limit: int = 60,
    log_lines_limit: int = 60,
    history: int = 60,
    sample: dict | None = None,
    sleeper=time.sleep,
) -> dict:
    """Tudo o que a interface pinta numa resposta so.

    Um endpoint unico (em vez de cinco) porque a GUI atualiza o painel
    inteiro de uma vez: cinco chamadas de processo filho a cada 2 s custariam
    mais que o monitoramento que ela mostra, e ainda produziram cinco
    instantes diferentes na mesma tela.

    `sample` e injetavel para o teste nao precisar de maquina nenhuma: sem
    ele, mede de verdade.
    """
    from sentinel import __version__

    metrics = sample if sample is not None else live_sample(sleeper=sleeper)
    return {
        "demo": False,
        "app": "sentinel",
        "version": __version__,
        "root": str(paths.root),
        "territory": str(paths.output_dir),
        "daemon": daemon_state(paths),
        "sample": metrics,
        "thresholds": thresholds(paths),
        "series": series_for(paths, history=history),
        "events": event_rows(paths, limit=events_limit),
        "resolutions": resolution_rows(paths),
        "interventions": intervention_rows(paths),
        "processes": process_rows(metrics),
        "log": log_lines(paths, limit=log_lines_limit),
        "kb": kb_catalog(),
        "arriving": None,
    }


def status(paths: settings.Paths) -> dict:
    """`status --json`: estado enxuto, sem medir nada.

    Sem medicao de proposito — um script de monitoramento chama isto em loop,
    e um loop que acorda o sensor a cada segundo seria o proprio problema que
    o Sentinel vigia.
    """
    store = EventStore(paths.events)
    opens = store.open_anomalies()
    return {
        "app": "sentinel",
        "daemon": daemon_state(paths),
        "events_open": len(opens),
        "events_total": len(store.anomalies()),
        "interventions": len(store.interventions()),
        "territory": str(paths.output_dir),
        "recent": [_anomaly_row(e) for e in opens[-5:]],
    }


# ------------------------------------------------------------------ tutorial --
def plan(paths: settings.Paths, event: dict) -> dict:
    """As opcoes de uma anomalia, na ordem em que a base local responde.

    Reusa `tutor.propose` sem reimplementar nada: as camadas 1-3
    (`.sentinel/kb.db` e o catalogo curado) respondem na hora, e o motor local
    so roda se houver motor nesta maquina — ver `local_model`, que recusa
    qualquer endereco que nao seja o loopback.

    `key` de cada opcao vai na resposta de proposito: e o que o `--resolve`
    devolve pra ligar o desfecho a opcao certa, sem repropor (repropor com
    motor ligado daria outra lista, e o "nao funcionou" seria gravado contra
    um conselho que ninguém viu).
    """
    from sentinel.tutor import propose

    db = _open_db(paths)
    overrides = settings.load_overrides(paths)
    try:
        options, fonte, camada = propose(event, overrides=overrides, db=db)
        if db is not None:
            db.touch_anomaly(event)
    finally:
        if db is not None:
            db.close()

    return {
        "event_id": event.get("id", ""),
        "metric": event.get("metric", ""),
        "severity": event.get("severity", ""),
        "options": options,
        "fonte": fonte,
        "camada": camada,
    }


# O desfecho terminal de cada caminho do ciclo, espelhando tutor._finalize.
_OUTCOME_STATUS = {
    OUTCOME_FIXED: STATUS_RESOLVED,
    OUTCOME_DISMISSED: STATUS_DISMISSED,
    OUTCOME_NOT_FIXED: STATUS_DISMISSED,
}


def resolve(
    paths: settings.Paths,
    event: dict,
    *,
    outcome: str,
    option_index: int | None = None,
    key: str = "",
    source: str = "",
    note: str = "",
) -> dict:
    """Grava UMA decisao do usuario sobre uma anomalia.

    As duas regras do ciclo de terminal valem aqui, e sao a razao de este
    endpoint nao ser um simples "escreve a linha":

    - `not_fixed` com opcao e o meio do caminho (a proxima da fila): vira
      desfecho na base, nao resolucao no historico. Escrever uma resolucao aqui
      fecharia a anomalia como descartada no instante em que o usuario so
      disse "esta nao era".
    - `not_fixed` sem opcao e a fila esgotada, e AI sim fecha.

    O que resolveu, nao resolveu ou foi pulado vai para `kb.db` quando a opcao
    tem `key` — e o ranking que faz a proxima rodada daquela anomalia comegar
    pela que ja funcionou nesta maquina.
    """
    from sentinel.events import EventStore

    if outcome not in _OUTCOME_STATUS:
        return {"ok": False, "error": f"outcome desconhecido: {outcome}"}

    event_id = event.get("id", "")
    if not event_id:
        return {"ok": False, "error": "anomalia sem id: nada a que ligar o desfecho"}

    store = EventStore(paths.events)
    terminal = outcome != OUTCOME_NOT_FIXED or option_index is None

    tally = False
    if key:
        db = _open_db(paths)
        if db is not None:
            try:
                tally = db.record(event, {"key": key}, outcome=outcome, source=source)
            finally:
                db.close()

    resolution = None
    if terminal:
        resolution = store.append_resolution(
            ref=event_id,
            outcome=outcome,
            option_index=option_index,
            source=source,
            note=note,
            set_status_to=_OUTCOME_STATUS[outcome],
        )
    else:
        store.set_status(event_id, STATUS_ADDRESSING)

    return {
        "ok": True,
        "event_id": event_id,
        "outcome": outcome,
        "option_index": option_index,
        "resolution_id": resolution.get("id") if resolution else None,
        "status": (
            _OUTCOME_STATUS[outcome] if terminal else STATUS_ADDRESSING
        ),
        "tally": tally,
    }


def _open_db(paths: settings.Paths):
    """Abre a base local, ou None. Mesma regra do CLI: a base e memoria, nao
    requisito — se ela nao abrir, o tutorial sai do catalogo curado."""
    from sentinel import kbstore

    try:
        paths.ensure_output_dir()
        return kbstore.open_store(paths.kb_db)
    except OSError:
        return None


def dump(payload: dict) -> str:
    """JSON de saida: UTF-8 sem escapes, chave estavel.

    `ensure_ascii=False` importa aqui porque o texto dos tutoriais tem
    acento, e `\u00e3` numa resposta de maquina so faz a GUI decodificar duas
    vezes.
    """
    return json.dumps(payload, ensure_ascii=False, default=str)

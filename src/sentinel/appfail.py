from __future__ import annotations

import datetime
import os
import subprocess
import xml.etree.ElementTree as ET

from sentinel import settings
from sentinel.detector import SEV_WARNING
from sentinel.incidents import METRIC_APP_FAILURE, Incident


# O Event Log só existe no Windows, e é aqui (não no daemon) que isso pesa.
_IS_WINDOWS = os.name == "nt"

_NS = "{http://schemas.microsoft.com/win/2004/08/events/event}"

# Que tipo de falha cada EventID significa, uma vez filtrado o provedor.
_KIND_BY_EVENT_ID = {1000: "crash", 1002: "hang"}


def _build_query(*, window_s: float, event_ids) -> str:
    """XPath da busca, montado só com inteiros vindos de `settings`.

    Nenhum trecho vem de entrada do usuário, então não há o que escapar: a
    string inteira é literal de código. O filtro de tempo usa
    `timediff(@SystemTime)` em milissegundos (medido nesta máquina: a
    janela estreita é o que impede o daemon de replayear o log ao subir).
    """
    ids = " or ".join(f"EventID={int(i)}" for i in event_ids)
    ms = int(max(1, window_s) * 1000)
    return (
        f"*[System[({ids}) and "
        f"TimeCreated[timediff(@SystemTime) <= {ms}]]]"
    )


def build_command(
    *, window_s: float, limit: int | None = None, event_ids=None, log: str | None = None
) -> list[str]:
    """argv de `wevtutil qe` em modo XML.

    Por que `/f:xml` e não `/f:text`: nesta máquina (Windows pt-BR) o texto
    vem traduzido — "Nome do Evento", "Assinatura do problema", "Level:
    Informaþ§es" — e em cp850, não UTF-8. O XML traz os `Data Name` do
    manifest do provedor (AppName, ExceptionCode, ProcessId...), que são
    os mesmos em qualquer idioma, e sai codificado em UTF-8. Parser que lê
    rótulo traduzido quebra calado num Windows em outra língua; este não.
    """
    return [
        "wevtutil",
        "qe",
        log or settings.APP_FAILURE_LOG,
        "/q:" + _build_query(
            window_s=window_s,
            event_ids=event_ids or settings.APP_FAILURE_EVENT_IDS,
        ),
        f"/c:{int(limit or settings.APP_FAILURE_QUERY_LIMIT)}",
        "/rd:true",  # mais recente primeiro
        "/f:xml",
    ]


def _default_runner(cmd: list[str]) -> tuple[int, bytes]:
    """Executa wevtutil sem shell e sem janela de console.

    argv como lista + `shell=False`: não há interpetação possível de
    string, e os argumentos são literais do próprio módulo.
    """
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    proc = subprocess.run(
        cmd,
        capture_output=True,
        timeout=settings.APP_FAILURE_TIMEOUT_S,
        creationflags=flags,
        shell=False,  # noqa: S603 - argv fixo, nada vem de fora
    )
    return proc.returncode, proc.stdout


def _parse_system_time(text: str | None) -> datetime.datetime | None:
    """`2026-09-20T13:26:40.9987212Z` -> datetime UTC aware.

    O Event Log devolve fração de 7 dígitos (unidades de 100 ns) e sufixo
    'Z'. `fromisoformat` só aceita isso a partir do 3.11, e o Sentinel
    declara 3.10+ — então normaliza à mão, sem depender de versão.
    """
    if not text:
        return None
    stamp = text.strip()
    if stamp.endswith("Z"):
        stamp = stamp[:-1] + "+00:00"
    if "." in stamp:
        head, _, frac = stamp.partition(".")
        frac = (frac[:6] or "0").rstrip()
        stamp = f"{head}.{frac}" if frac else head
    try:
        parsed = datetime.datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def _int_from_hex(text: str | None) -> int | None:
    """`0x3b0c` -> 15116. O log escreve PID em hex; o resto do Sentinel
    trabalha com int, e é o int que o `kill`/`relief` vai receber."""
    if not text:
        return None
    try:
        return int(text.strip(), 16)
    except ValueError:
        return None


def _event_data(event) -> dict:
    """{Nome: texto} do <EventData>, ignorando `<Data>` sem nome."""
    out: dict = {}
    node = event.find(_NS + "EventData")
    if node is None:
        return out
    for data in node:
        name = data.get("Name")
        if name:
            out[name] = (data.text or "").strip()
    return out


class AppFailureReader:
    """Lê falhas de aplicativo do Event Log local e vira `Incident`.

    Porque o log e não o psutil: quando um app quebra, ele já foi. A
    memória que ele segurava sumiu, o CPU dele zerou — nenhuma métrica de
    recurso conta a história. O Event Log conta: módulo culpado, código de
    exceção, versão, PID, e se foi queda ou travamento. Tudo local, com
    `wevtutil` (binário do próprio Windows), sem rede e sem elevação —
    ler o log `Application` não é operação privilegiada (verificado nesta
    máquina numa shell de usuário comum).

    Dois eventos ficam de fora por decisão medida, não por gosto:

    - **1001 (Windows Error Reporting)** é o espelho do 1000/1002 — chega
      com o mesmo app segundos depois, e quando chega sozinho é
      diagnóstico, não falha (`RADAR_PRE_LEAK_64`, `crashpad_log`,
      `StoreAgentInstallFailure1` dominam o log desta máquina). Contar 1001
      seria inflacionar uma queda em duas anomalias e chamar vazamento de
      leak de "crash".
    - **1002 de outro provedor** (ex.: `Microsoft-Windows-Winlogon`) não é
      travamento de app; daí o filtro por provedor além do filtro por ID.

    `runner` injetável pra teste; ausência do `wevtutil` (ou Windows) é
    estado normal, não erro: o Sentinel segue vigiando recursos e só deixa
    de anunciar quedas.
    """

    def __init__(
        self,
        *,
        runner=None,
        window_s: float | None = None,
        query_interval_s: float | None = None,
        limit: int | None = None,
    ) -> None:
        self._runner = runner or _default_runner
        self.window_s = window_s if window_s is not None else settings.APP_FAILURE_WINDOW_S
        self.query_interval_s = (
            query_interval_s
            if query_interval_s is not None
            else settings.APP_FAILURE_QUERY_INTERVAL_S
        )
        self.limit = limit
        self.unavailable = False
        self.query_calls = 0
        self._last_query_at: datetime.datetime | None = None
        self._seen: set = set()

    # -- ciclo ---------------------------------------------------------

    def observe(self, now: datetime.datetime | None = None) -> list[Incident]:
        """Um tick: devolve as falhas ainda não vistas, se estiver na hora.

        A consulta é lenta (processo filho + leitura do log), então roda no
        máximo a cada `query_interval_s`, não a cada amostra de 2 s.
        """
        if not _IS_WINDOWS or self.unavailable:
            return []

        moment = now or datetime.datetime.now(datetime.timezone.utc)
        if (
            self._last_query_at is not None
            and (moment - self._last_query_at).total_seconds() < self.query_interval_s
        ):
            return []
        self._last_query_at = moment

        cmd = build_command(
            window_s=self.window_s, limit=self.limit
        )
        try:
            code, payload = self._runner(cmd)
        except FileNotFoundError:
            # Sem wevtutil não há log pra ler: desiste uma vez só.
            self.unavailable = True
            return []
        except Exception:
            # Timeout, permissão, log corrompido: o ciclo de vigilância não
            # pode parar por causa de um diagnóstico ausente.
            return []

        self.query_calls += 1
        if code != 0 or not payload:
            return []

        return self._ingest(payload)

    # -- parsing -------------------------------------------------------

    def _ingest(self, payload: bytes) -> list[Incident]:
        try:
            text = payload.decode("utf-8", errors="replace")
        except Exception:
            return []
        if "<Event" not in text:
            return []

        try:
            # wevtutil emite N raízes <Event> soltas (não um <Events>):
            # embrulha pra virar XML válido e descarta o invólucro.
            root = ET.fromstring("<sentinel-root>" + text + "</sentinel-root>")
        except ET.ParseError:
            return []

        incidents: list[Incident] = []
        for element in root:
            incident, key = self._to_incident(element)
            if incident is None or key in self._seen:
                continue
            self._remember(key)
            incidents.append(incident)
        return incidents

    def _to_incident(self, element):
        system = element.find(_NS + "System")
        if system is None:
            return None, None

        provider_node = system.find(_NS + "Provider")
        provider = ((provider_node.get("Name") if provider_node is not None else "") or "")
        if provider.lower() not in settings.APP_FAILURE_PROVIDERS:
            return None, None

        event_id = _int_of(_text(system.find(_NS + "EventID")))
        when = _parse_system_time(
            system.find(_NS + "TimeCreated").get("SystemTime")
            if system.find(_NS + "TimeCreated") is not None
            else None
        )
        record_id = _text(system.find(_NS + "EventRecordID"))
        kind = _KIND_BY_EVENT_ID.get(event_id or 0)
        if kind is None:
            return None, None

        data = _event_data(element)
        app = data.get("AppName") or data.get("App") or ""
        if not app:
            return None, None  # sem nome de app, não há o que tutoriar

        detail = {
            "kind": kind,
            "app": app,
            "app_version": data.get("AppVersion") or "",
            "provider": provider,
            "event_id": event_id,
            "pid": _int_from_hex(data.get("ProcessId")),
            "report_id": data.get("ReportId") or "",
            "at": when.isoformat() if when else "",
        }
        if kind == "crash":
            code = data.get("ExceptionCode") or ""
            if code:
                detail["exception_code"] = code if code.lower().startswith("0x") else f"0x{code}"
            if data.get("ModuleName"):
                detail["module"] = data["ModuleName"]
            label = f"{app} parou de funcionar"
            if detail.get("exception_code"):
                label += f" (excecao {detail['exception_code']}"
                label += f" em {detail['module']})" if detail.get("module") else ")"
        else:
            label = f"{app} parou de responder e o Windows o fechou"

        incident = Incident(
            metric=METRIC_APP_FAILURE,
            severity=SEV_WARNING,
            detail=detail,
            fingerprint=f"{METRIC_APP_FAILURE}:{SEV_WARNING}:{app.lower()}",
            label=label,
        )
        # Chave de "já contei esta linha": o EventRecordID e o log, únicos
        # por registro; sem ele, tempo + provedor + pid servem.
        key = f"{provider}:{record_id}" if record_id else f"{detail['at']}:{app}:{detail.get('pid')}"
        return incident, key

    def _remember(self, key: str) -> None:
        # Limitado: o daemon roda dias, e um set sem teto só cresce.
        if len(self._seen) >= settings.APP_FAILURE_SEEN_MAX:
            self._seen.clear()
        self._seen.add(key)


def _text(node) -> str:
    return (node.text or "").strip() if node is not None else ""


def _int_of(value: str):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

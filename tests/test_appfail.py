from __future__ import annotations

import datetime

from sentinel.detector import SEV_WARNING
from sentinel.incidents import METRIC_APP_FAILURE
from sentinel.appfail import AppFailureReader


# Amostra real, colhida nesta máquina em 2026-09-22 com
#   wevtutil qe Application /q:...\[EventID=1000 or 1002\] /f:xml
# (FieldNames em inglês mesmo com o Windows em pt-BR — é o que torna o
# parser imune ao idioma, ao contrário do /f:text, que vem traduzido.)
NS = "http://schemas.microsoft.com/win/2004/08/events/event"


def _event(
    *,
    provider: str,
    event_id: int,
    record_id: int,
    when: str = "2026-09-22T10:15:32.3885461Z",
    data: dict | None = None,
) -> str:
    rows = "".join(
        f"<Data Name='{k}'>{v}</Data>" for k, v in (data or {}).items()
    )
    return (
        f"<Event xmlns='{NS}'><System>"
        f"<Provider Name='{provider}'/>"
        f"<EventID Qualifiers='0'>{event_id}</EventID>"
        f"<Level>2</Level><Task>100</Task><Keywords>0x80000000000000</Keywords>"
        f"<TimeCreated SystemTime='{when}'/>"
        f"<EventRecordID>{record_id}</EventRecordID>"
        "<Channel>Application</Channel>"
        "<Computer>ANTHERO-PC</Computer><Security/></System>"
        f"<EventData>{rows}</EventData></Event>"
    )


CRASH_1000 = dict(
    provider="Application Error",
    event_id=1000,
    data={
        "AppName": "Genesis.exe",
        "AppVersion": "1.0.0.0",
        "AppTimeStamp": "6aafcb23",
        "ModuleName": "nvgpucomp64.dll",
        "ModuleVersion": "31.0.15.3632",
        "ModuleTimeStamp": "65123655",
        "ExceptionCode": "c0000005",
        "FaultingOffset": "00001581",
        "ProcessId": "0x3b0c",
        "AppPath": "C:\\Users\\anthe\\Genesis.exe",
        "ModulePath": "C:\\Windows\\System32\\nvgpucomp64.dll",
        "ReportId": "bcb5675f-987e",
    },
)

HANG_1002 = dict(
    provider="Application Hang",
    event_id=1002,
    data={
        "AppName": "Qoder IDE.exe",
        "AppVersion": "1.31.0.0",
        "ProcessId": "0x772c",
        "StartTime": "0x1dd49038b085163",
        "TerminationTime": "4294967295",
        "ExeFileName": "C:\\Program Files\\Qoder\\Qoder IDE.exe",
        "ReportId": "7ef27331-6243",
    },
)


def _runner(*xml_parts):
    payload = "".join(xml_parts).encode("utf-8")

    def run(cmd):
        run.calls.append(list(cmd))
        return 0, payload

    run.calls: list = []
    return run


def test_non_windows_never_runs_the_query(monkeypatch):
    monkeypatch.setattr("sentinel.appfail._IS_WINDOWS", False)
    reader = AppFailureReader(runner=_runner(_event(**CRASH_1000, record_id=1)))
    assert reader.observe() == []
    assert reader.query_calls == 0  # nenhum subprocess disparado


def test_wevtutil_absent_degrades_to_silence_once():
    def missing(cmd):
        raise FileNotFoundError(2, "wevtutil")

    reader = AppFailureReader(runner=missing)
    assert reader.observe() == []
    assert reader.observe() == []  # nao tenta de novo a cada tick
    assert reader.unavailable is True


def test_query_is_built_from_settings_with_time_window():
    calls = []

    def run(cmd):
        calls.append(list(cmd))
        return 0, b""

    reader = AppFailureReader(runner=run, window_s=120)
    reader.observe()

    cmd = calls[0]
    assert cmd[0] == "wevtutil" and cmd[1] == "qe" and cmd[2] == "Application"
    xpath = cmd[3]
    assert xpath.startswith("/q:")
    assert "EventID=1000" in xpath and "EventID=1002" in xpath
    assert "timediff(@SystemTime) <= 120000" in xpath  # s -> ms
    assert "/f:xml" in cmd  # nunca /f:text: o texto vem traduzido


def test_crash_becomes_warning_incident_with_measured_detail():
    reader = AppFailureReader(
        runner=_runner(_event(record_id=77, **CRASH_1000))
    )
    found = reader.observe()

    assert len(found) == 1
    inc = found[0]
    assert inc.metric == METRIC_APP_FAILURE
    assert inc.severity == SEV_WARNING
    assert inc.detail["app"] == "Genesis.exe"
    assert inc.detail["exception_code"] == "0xc0000005"
    assert inc.detail["module"] == "nvgpucomp64.dll"
    assert inc.detail["pid"] == 0x3B0C  # hex do log vira int de verdade
    assert inc.detail["event_id"] == 1000
    assert inc.detail["at"].startswith("2026-09-22T10:15:32")
    assert "Genesis.exe" in inc.label and "0xc0000005" in inc.label


def test_hang_is_labelled_as_hang_not_as_crash():
    reader = AppFailureReader(
        runner=_runner(_event(record_id=88, **HANG_1002))
    )
    inc = reader.observe()[0]
    assert inc.detail["kind"] == "hang"
    assert inc.detail["app"] == "Qoder IDE.exe"
    assert "parou de responder" in inc.label
    # Sem ExceptionCode no evento de hang: nao se inventa campo.
    assert "exception_code" not in inc.detail


def test_same_death_never_reports_twice():
    # 1000 (Application Error) e 1001 (WER) descrevem a MESMA queda com
    # timestamps a segundos de distancia; o EventRecordID diferencia linhas
    # mas o fingerprint e o que colapsa no store. Aqui: dois ticks com o
    # mesmo registro nao re-emitem nada.
    payload = _event(record_id=77, **CRASH_1000)
    reader = AppFailureReader(runner=_runner(payload))
    assert len(reader.observe()) == 1
    assert reader.observe() == []


def test_winlogon_1002_is_not_an_app_hang():
    # EventID 1002 também aparece em outros provedores; só os dois de app
    # ("Application Error" / "Application Hang") são falha de aplicativo.
    noise = _event(
        provider="Microsoft-Windows-Winlogon",
        event_id=1002,
        record_id=99,
        data={None: "C:\\WINDOWS\\system32\\userinit.exe"},
    )
    reader = AppFailureReader(runner=_runner(noise))
    assert reader.observe() == []


def test_fingerprint_groups_crash_loop_of_same_app():
    a = AppFailureReader(
        runner=_runner(_event(record_id=1, **CRASH_1000))
    ).observe()[0]
    b = AppFailureReader(
        runner=_runner(
            _event(
                record_id=2,
                when="2026-09-22T11:15:32.0000000Z",
                **CRASH_1000,
            )
        )
    ).observe()[0]
    assert a.fingerprint == b.fingerprint == "app_failure:warning:genesis.exe"


def test_malformed_or_empty_output_is_ignored_not_fatal():
    assert AppFailureReader(runner=lambda cmd: (0, b"")).observe() == []
    assert (
        AppFailureReader(runner=lambda cmd: (0, b"<Event><nope")).observe()
        == []
    )
    assert AppFailureReader(runner=lambda cmd: (1, b"erro")).observe() == []


def test_reader_is_throttled_between_queries():
    calls = []

    def run(cmd):
        calls.append(cmd)
        return 0, b""

    reader = AppFailureReader(runner=run, query_interval_s=60)
    now = datetime.datetime(2026, 9, 22, 12, 0, 0, tzinfo=datetime.timezone.utc)
    reader.observe(now)
    reader.observe(now + datetime.timedelta(seconds=5))
    reader.observe(now + datetime.timedelta(seconds=50))
    assert len(calls) == 1
    reader.observe(now + datetime.timedelta(seconds=61))
    assert len(calls) == 2

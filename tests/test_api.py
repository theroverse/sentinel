"""Testes da camada de maquina (`sentinel.api`) e das flags `--json` do CLI.

A regra do jogo: `api` nao inventa regra nenhuma, so reorganiza o que os
modulos de medicao ja sabem. Entao cada teste abaixo confirma uma promessa de
forma (o que a GUI indexa) e uma promessa de honestidade (o numero vem de
onde o daemon escreveu, nao de uma segunda medicao).
"""

from __future__ import annotations

import datetime
import json

import pytest

from conftest import make_sample, proc

from sentinel import api, settings
from sentinel.detector import SEV_CRITICAL, SEV_WARNING, Finding
from sentinel.incidents import METRIC_APP_FAILURE, Incident
from sentinel.events import (
    OUTCOME_FIXED,
    OUTCOME_NOT_FIXED,
    STATUS_ADDRESSING,
    STATUS_DISMISSED,
    STATUS_RESOLVED,
    EventStore,
)


# ------------------------------------------------------------------ helpers --
@pytest.fixture
def paths(tmp_path):
    p = settings.paths_for(tmp_path)
    p.ensure_output_dir()
    return p


def tick(ts, *, cpu=10.0, ram=20.0, disk=30.0, io=40.0, swap=0.0, swap_rate=0.0,
         down=0.0, up=0.0, paused=False, stalled=False) -> str:
    """Uma linha de batimento no formato exato que `daemon._heartbeat` escreve."""
    line = (
        f"{ts.isoformat()} tick cpu={cpu:.1f} ram={ram:.1f} disk={disk:.1f} "
        f"io={io:.1f} swap={swap:.1f} swap_rate={swap_rate:.0f} "
        f"net_down_bps={down:.0f} net_up_bps={up:.0f}"
    )
    if paused:
        line += " paused=1"
    if stalled:
        line += " stall=1"
    return line


def write_log(paths, lines) -> None:
    paths.daemon_log.write_text("\n".join(lines) + "\n", encoding="utf-8")


def anomaly_metric_cpu(**over) -> Finding:
    base = dict(
        metric="cpu",
        severity=SEV_CRITICAL,
        value=97.0,
        threshold=settings.CPU_CRITICAL,
        samples=5,
        span_s=10.0,
        top_processes=[proc(11, "chrome.exe", cpu=40.0, rss_mb=900.0)],
        fingerprint="cpu:critical:chrome.exe",
    )
    base.update(over)
    return Finding(**base)


def record_cpu_anomaly(paths, *, severity=SEV_CRITICAL, ts=None, culprit="chrome.exe"):
    sample = make_sample(cpu=97.0, ts=ts)
    finding = anomaly_metric_cpu(
        severity=severity, fingerprint=f"cpu:{severity}:{culprit}",
        top_processes=[proc(11, culprit, cpu=40.0, rss_mb=900.0)],
    )
    return EventStore(paths.events).record_finding(finding, sample)


# ---------------------------------------------------------------- _tail() --
def test_tail_de_arquivo_inexistente_devolve_lista_vazia(tmp_path):
    assert api._tail(tmp_path / "nao-existe.log") == []


def test_tail_so_le_o_rabo_do_arquivo(paths):
    write_log(paths, [f"linha {i}" for i in range(500)])
    tail = api._tail(paths.daemon_log, max_lines=3)
    assert tail == ["linha 497", "linha 498", "linha 499"]


def test_tail_sem_max_lines_nao_engole_linhas(paths):
    linhas = [f"l{i}" for i in range(20)]
    write_log(paths, linhas)
    assert api._tail(paths.daemon_log) == linhas


def test_tail_arquivo_sem_nova_linha_final_mantem_a_ultimalinha(paths):
    paths.daemon_log.write_text("a\nb\nsem nova linha", encoding="utf-8")
    assert api._tail(paths.daemon_log)[-1] == "sem nova linha"


# --------------------------------------------------------- series_for() ----
def test_series_vem_dos_batimentos_do_daemon(paths):
    t0 = datetime.datetime(2026, 9, 22, 12, 0, tzinfo=datetime.timezone.utc)
    write_log(paths, [
        tick(t0, cpu=11.0, ram=22.0, disk=33.0, io=44.0),
        "2026-09-22T12:00:02+00:00 ANOMALIA cpu/critical value=97.0 thr=95.0 status=open id=evt-1",
        tick(t0 + datetime.timedelta(seconds=2), cpu=55.0, ram=66.0, disk=77.0, io=88.0),
    ])
    series = api.series_for(paths)
    assert series["cpu"]["points"] == [11.0, 55.0]
    assert series["cpu"]["unit"] == "%"
    assert series["ram"]["points"] == [22.0, 66.0]
    assert series["io"]["points"] == [44.0, 88.0]


def test_series_de_rede_e_so_o_recebido_em_mbit(paths):
    t0 = datetime.datetime(2026, 9, 22, 12, 0, tzinfo=datetime.timezone.utc)
    # 1_250_000 B/s recebido = 10 Mbit/s; o enviado (5 Mbit) nao aparece.
    write_log(paths, [tick(t0, down=1_250_000, up=625_000)])
    series = api.series_for(paths)
    assert series["net"]["points"] == [10.0]
    assert series["net"]["unit"] == "Mbit"


def test_series_history_limita_as_ultimas_amostras(paths):
    t0 = datetime.datetime(2026, 9, 22, 12, 0, tzinfo=datetime.timezone.utc)
    write_log(paths, [tick(t0 + datetime.timedelta(seconds=i), cpu=float(i)) for i in range(10)])
    assert api.series_for(paths, history=3)["cpu"]["points"] == [7.0, 8.0, 9.0]


def test_series_sem_log_responde_com_series_vazias(paths):
    series = api.series_for(paths)
    assert set(series) == {"cpu", "ram", "disk", "io", "net"}
    assert series["cpu"] == {"points": [], "unit": "%"}


# ----------------------------------------------------------- log_lines() ---
def test_log_lines_devolve_da_mais_nova_primeiro_com_ts_partido(paths):
    t0 = datetime.datetime(2026, 9, 22, 12, 0, tzinfo=datetime.timezone.utc)
    t1 = t0 + datetime.timedelta(seconds=2)
    write_log(paths, [tick(t0, cpu=1.0), tick(t1, cpu=2.0)])
    rows = api.log_lines(paths)
    assert len(rows) == 2
    assert rows[0]["ts"] == t1.isoformat()
    assert rows[0]["text"].startswith("tick cpu=2.0")
    assert rows[1]["ts"] == t0.isoformat()


def test_log_lines_mantem_linha_ilegivel_sem_ts(paths):
    """Esconder uma linha que nao parseia seria apagar evidencia."""
    write_log(paths, ["lixo sem carimbo", "2026-99-99 inválido"])
    rows = api.log_lines(paths)
    assert {r["ts"] for r in rows} == {""}
    assert rows[0]["text"] == "2026-99-99 inválido"


def test_log_lines_limit_nao_corta_a_ponta_mais_recente(paths):
    t0 = datetime.datetime(2026, 9, 22, 12, 0, tzinfo=datetime.timezone.utc)
    write_log(paths, [tick(t0 + datetime.timedelta(seconds=i), cpu=float(i)) for i in range(20)])
    rows = api.log_lines(paths, limit=5)
    assert len(rows) == 5
    assert "cpu=19.0" in rows[0]["text"]


def test_log_lines_descarta_bom_da_primeira_linha(paths):
    """Um `daemon.log` escrito por PowerShell (`Set-Content -Encoding UTF8`) vem
    com BOM. Sem removelo o \\ufeff viaja dentro do JSON e faz o `print` da
    resposta morrer num console cp1252 — a janela fica muda."""
    t0 = datetime.datetime(2026, 9, 22, 12, 0, tzinfo=datetime.timezone.utc)
    paths.daemon_log.write_text(
        "\ufeff" + tick(t0, cpu=3.0) + "\n", encoding="utf-8"
    )
    rows = api.log_lines(paths)
    assert len(rows) == 1
    assert rows[0]["text"].startswith("tick cpu=3.0")
    assert "\ufeff" not in api.dump({"log": rows})


# ------------------------------------------------------- thresholds() ------
def test_thresholds_reflete_override_do_config_json(paths):
    paths.config.write_text(json.dumps({"CPU_CRITICAL": 70.0}), encoding="utf-8")
    th = api.thresholds(paths)
    assert th["cpu"]["critical"] == 70.0
    assert th["cpu"]["warning"] == settings.CPU_WARNING  # nao sobrescrito


def test_thresholds_traz_as_chaves_que_o_mock_da_gui_indexa(paths):
    th = api.thresholds(paths)
    assert set(th) == {"cpu", "ram", "disk", "io", "network"}
    assert set(th["cpu"]) == {"warning", "critical", "sustained"}
    assert set(th["network"]) == {"warning_ratio", "sustained"}
    assert isinstance(th["cpu"]["sustained"], int)


# ------------------------------------------------- normalizacao de evento --
def test_anomaly_row_completa_o_que_incidente_nao_tem():
    """Schema 2 (stall/app_failure/orphan_tree) nao tem valor nem topo: a GUI
    indexa esses campos sem existir -> a saida de maquina normaliza."""
    incidente = {
        "id": "evt-1", "kind": "anomaly", "metric": "orphan_tree",
        "severity": "warning", "label": "3 filhos órfãos", "status": "open",
    }
    row = api._anomaly_row(incidente)
    assert row["value"] is None
    assert row["threshold"] is None
    assert row["top_processes"] == []
    assert row["window"] == {"samples": 0, "span_s": 0.0}
    assert row["ts_last"] == ""
    assert row["label"] == "3 filhos órfãos"  # o que a GUI mostra como titulo


def test_anomaly_row_nao_pisa_no_que_anomalia_de_limiar_ja_tem():
    original = {"id": "e", "metric": "cpu", "value": 97.0, "threshold": 95.0,
                "window": {"samples": 5, "span_s": 10.0}, "top_processes": [{"pid": 1}],
                "status": "open", "occurrences": 2, "ts_last": "x"}
    assert api._anomaly_row(original) == original


def test_event_rows_na_ordem_mais_nova_primeiro_com_limite(paths):
    t0 = datetime.datetime(2026, 9, 22, 12, 0, tzinfo=datetime.timezone.utc)
    # Culprados diferentes: o EventStore colapsa por fingerprint, e quatro
    # linhas do mesmo processo dariam uma anomalia com `occurrences: 4`.
    for i in range(4):
        record_cpu_anomaly(paths, ts=t0 + datetime.timedelta(minutes=i),
                           culprit=f"p{i}.exe")
    rows = api.event_rows(paths, limit=2)
    assert len(rows) == 2
    assert rows[0]["top_processes"][0]["name"] == "p3.exe"
    assert rows[0]["window"]["samples"] == 5  # normalizado, nao ausente


# ------------------------------------------------------ _sample_dict() -----
def test_sample_dict_arredonda_e_preserva_os_nomes_do_mock():
    s = make_sample(cpu=12.345, ram=50.0, disk=60.0, io=70.0, net_recv=1234.5,
                    top_cpu=[proc(7, "a.exe", cpu=3.0, rss_mb=1.5)])
    d = api._sample_dict(s)
    assert d["cpu_percent"] == 12.3
    assert d["net_recv_bps"] == 1234.0
    assert d["swap_percent"] == 0.0
    assert d["top_cpu"][0]["name"] == "a.exe"
    assert "disk_path" in d and "ts" in d


# --------------------------------------------------------- live_sample() ---
class _FakeSensor:
    """Registra quantas leituras o chamador fez e em que ordem."""

    instancias = []

    def __init__(self, *a, **k):
        self.calls = []
        _FakeSensor.instancias.append(self)

    def sample(self, top=True):
        self.calls.append(top)
        return make_sample(cpu=42.0)


def test_live_sample_arma_o_contador_antes_de_medir(monkeypatch):
    """A primeira leitura do psutil so arma o delta: medir uma vez daria 0.0
    inventado no painel."""
    _FakeSensor.instancias.clear()
    monkeypatch.setitem(
        __import__("sys").modules, "sentinel.sensor",
        type("m", (), {"Sensor": _FakeSensor}),
    )
    slept = []
    d = api.live_sample(settle_s=0.5, sleeper=slept.append)
    assert _FakeSensor.instancias[0].calls == [False, True]
    assert slept == [0.5]
    assert d["cpu_percent"] == 42.0


def test_live_sample_usa_a_janela_de_settings_quando_nao_especificada(monkeypatch):
    _FakeSensor.instancias.clear()
    monkeypatch.setitem(
        __import__("sys").modules, "sentinel.sensor",
        type("m", (), {"Sensor": _FakeSensor}),
    )
    slept = []
    api.live_sample(sleeper=slept.append)
    assert slept == [settings.METRICS_SETTLE_S]


# -------------------------------------------------------- process_rows() ---
def test_process_rows_marca_protegidos_pela_lista_que_o_kill_usa():
    sample = {
        "top_cpu": [{"pid": 4, "name": "System", "cpu": 1.0, "rss_mb": 0.0}],
        "top_mem": [{"pid": 700, "name": "chrome.exe", "cpu": 5.0, "rss_mb": 10.0}],
    }
    rows = api.process_rows(sample)
    by_pid = {r["pid"]: r for r in rows}
    assert by_pid[4]["protected"] is True
    assert by_pid[700]["protected"] is False


def test_process_rows_unifica_topo_cpu_e_mem_sem_duplicar(paths):
    sample = {
        "top_cpu": [{"pid": 1, "name": "a", "cpu": 9.0, "rss_mb": 1.0},
                    {"pid": 2, "name": "b", "cpu": 1.0, "rss_mb": 1.0}],
        "top_mem": [{"pid": 1, "name": "a", "cpu": 9.0, "rss_mb": 1.0},
                    {"pid": 3, "name": "c", "cpu": 5.0, "rss_mb": 99.0}],
    }
    rows = api.process_rows(sample)
    assert [r["pid"] for r in rows] == [1, 3, 2]  # ordenado por cpu, sem repetir


def test_process_rows_respeita_limite_e_coluna_de_dependentes():
    sample = {"top_cpu": [{"pid": i, "name": f"p{i}", "cpu": float(i), "rss_mb": 0.0}
                          for i in range(40)], "top_mem": []}
    rows = api.process_rows(sample, limit=5)
    assert len(rows) == 5
    assert all("children" in r for r in rows)


# -------------------------------------------------------- daemon_state() ---
def test_daemon_state_sem_daemon_nao_inventa_heartbeat(paths):
    st = api.daemon_state(paths)
    assert st["running"] is False
    assert st["last_heartbeat"] is None
    assert st["interval_s"] == settings.SAMPLE_INTERVAL_S
    assert st["shadow"] in (True, False)


def test_daemon_state_reconhece_o_kill_switch(paths):
    paths.paused.write_text("2026-09-22T12:00:00+00:00", encoding="utf-8")
    assert api.daemon_state(paths)["paused"] is True


# --------------------------------------------------------------- status() --
def test_statusConta_anomalias_abertas_e_o_total(paths):
    t0 = datetime.datetime(2026, 9, 22, 12, 0, tzinfo=datetime.timezone.utc)
    aberto = record_cpu_anomaly(paths, ts=t0, severity=SEV_CRITICAL)
    fechado = record_cpu_anomaly(paths, ts=t0 + datetime.timedelta(minutes=1),
                                 severity=SEV_WARNING)
    store = EventStore(paths.events)
    store.append_resolution(ref=fechado["id"], outcome=OUTCOME_FIXED,
                            option_index=0, source="test")
    out = api.status(paths)
    assert out["app"] == "sentinel"
    assert out["events_total"] == 2
    assert out["events_open"] == 1
    assert out["recent"][0]["id"] == aberto["id"]
    assert out["territory"] == str(paths.output_dir)


# ----------------------------------------------------------------- plan() --
def test_plan_devolve_ate_tres_opcoes_com_porque(paths):
    event = record_cpu_anomaly(paths)
    out = api.plan(paths, event)
    assert out["event_id"] == event["id"]
    assert out["metric"] == "cpu"
    assert 0 < len(out["options"]) <= settings.MAX_FIX_OPTIONS
    assert out["camada"] in (1, 2, 3, 4)
    opt = out["options"][0]
    assert opt["title"] and opt["key"]
    assert opt["why"]  # o tutorial vem com o por que, nao so o que fazer


def test_plan_da_base_local_responde_antes_do_catalogo(paths):
    """A promessa do pedido: a base local e consultada primeiro, e o que ja
    resolveu nesta maquina comeca a fila na proxima rodada."""
    event = record_cpu_anomaly(paths)
    primeiro = api.plan(paths, event)
    outras = [o["key"] for o in primeiro["options"][1:]]
    assert outras, "precisa de mais de uma opcao pra existir fila"

    # O usuario tenta a ultima da fila e resolve: a base conta, e a ordem muda.
    api.resolve(paths, event, outcome=OUTCOME_FIXED, option_index=len(outras),
                key=outras[-1], source="user")

    depois = api.plan(paths, event)
    assert depois["options"][0]["key"] == outras[-1]


def test_label_acentuada_de_incidente_sobe_no_dump_sem_quebrar(paths):
    """O texto de um incidente vem do Event Log, com acento ('parou de
    funcionar'). Se ele nao sobreviver ao dump + print, a ponte devolve JSON
    truncado e a GUI mostra 'o motor nao respondeu nada'."""
    inc = Incident(
        metric=METRIC_APP_FAILURE,
        severity=SEV_WARNING,
        detail={"kind": "crash", "app": "Genesis.exe", "exception_code": "0xc0000005"},
        fingerprint="app_failure:warning:genesis.exe",
        label="Genesis.exe parou de funcionar (exceção 0xc0000005)",
    )
    EventStore(paths.events).record_incident(
        inc, now=datetime.datetime.now(datetime.timezone.utc)
    )

    payload = api.dump({"events": api.event_rows(paths)})
    assert "funcionar" in payload
    assert "\ufeff" not in payload
    assert json.loads(payload)["events"][0]["label"] == inc.label


# -------------------------------------------------------------- resolve() --
def test_resolve_fixed_escreve_resolucao_e_fecha(paths):
    event = record_cpu_anomaly(paths)
    out = api.resolve(paths, event, outcome=OUTCOME_FIXED, option_index=0,
                      key="cpu:restart", source="user")
    assert out["ok"] is True
    assert out["status"] == STATUS_RESOLVED
    assert out["resolution_id"]
    assert out["tally"] is True
    assert EventStore(paths.events).find(event["id"])["status"] == STATUS_RESOLVED


def test_resolve_not_fixed_com_opcao_nao_fecha_a_anomalia(paths):
    """'Esta nao era' nao e 'resolvido': e o meio da fila. Fechar aqui sumiria
    com o episodio antes das proximas opcoes."""
    event = record_cpu_anomaly(paths)
    out = api.resolve(paths, event, outcome=OUTCOME_NOT_FIXED, option_index=0,
                      key="cpu:restart", source="user")
    assert out["resolution_id"] is None
    assert out["status"] == STATUS_ADDRESSING
    assert EventStore(paths.events).find(event["id"])["status"] == STATUS_ADDRESSING
    assert api.resolution_rows(paths) == []


def test_resolve_not_fixed_sem_opcao_e_fila_esgotada_e_fecha(paths):
    event = record_cpu_anomaly(paths)
    out = api.resolve(paths, event, outcome=OUTCOME_NOT_FIXED, option_index=None)
    assert out["status"] == STATUS_DISMISSED
    assert out["resolution_id"]
    assert EventStore(paths.events).find(event["id"])["status"] == STATUS_DISMISSED


def test_resolve_sem_key_nao_finge_desfecho_na_base(paths):
    """Opcao do catalogo nao tem `key`: sem ela nao ha o que contar, e
    `tally` diz a verdade em vez de mentir que aprendeu."""
    event = record_cpu_anomaly(paths)
    out = api.resolve(paths, event, outcome=OUTCOME_FIXED, option_index=1)
    assert out["tally"] is False
    assert out["resolution_id"]


def test_resolve_recusa_outcome_desconhecido(paths):
    event = record_cpu_anomaly(paths)
    out = api.resolve(paths, event, outcome="talvez")
    assert out["ok"] is False
    assert "outcome" in out["error"]


def test_resolve_exige_id_para_ligar_o_desfecho(paths):
    out = api.resolve(paths, {"metric": "cpu"}, outcome=OUTCOME_FIXED)
    assert out["ok"] is False
    assert "id" in out["error"]


def test_resolve_do_ciclo_completo_muda_a_ordem_do_proximo_plan(paths):
    """O caminho completo sem GUI: 'esta nao era', depois 'esta resolveu', e a
    fila da proxima rodada ja reflete a historia desta maquina."""
    event = record_cpu_anomaly(paths)
    chaves = [o["key"] for o in api.plan(paths, event)["options"]]
    assert len(chaves) >= 2, "sem fila nao ha o que reordenar"

    meio = api.resolve(paths, event, outcome=OUTCOME_NOT_FIXED, option_index=0,
                       key=chaves[0], source="user")
    assert meio["status"] == STATUS_ADDRESSING  # a anomalia continua aberta
    fim = api.resolve(paths, event, outcome=OUTCOME_FIXED, option_index=1,
                      key=chaves[1], source="user")
    assert fim["status"] == STATUS_RESOLVED

    depois = api.plan(paths, dict(event))
    assert [o["key"] for o in depois["options"]][0] == chaves[1]


# ------------------------------------------------------------------ dump --
def test_dump_nao_escapa_acento():
    """GUI que recebe `\\u00e3` decodifica duas vezes e mostra o escape."""
    out = api.dump({"texto": "não há telemetria"})
    assert "não há telemetria" in out
    assert "\\u" not in out


def test_dump_serializa_datetime_sem_estourar():
    ts = datetime.datetime(2026, 9, 22, 12, 0, tzinfo=datetime.timezone.utc)
    assert "2026-09-22" in api.dump({"ts": ts})


# ----------------------------------------------------------- dashboard() ---
def _sample_payload():
    return {
        "ts": "2026-09-22T12:00:00+00:00",
        "cpu_percent": 12.0, "ram_percent": 34.0, "disk_percent": 50.0,
        "disk_path": "C:\\", "io_busy_percent": 1.0,
        "net_recv_bps": 0.0, "net_sent_bps": 0.0,
        "swap_percent": 0.0, "swap_activity_ps": 0.0,
        "top_cpu": [{"pid": 9, "name": "jogo.exe", "cpu": 12.0, "rss_mb": 100.0}],
        "top_mem": [],
    }


def test_dashboard_responde_tudo_o_que_a_gui_pinta_em_uma_unica_chamada(paths):
    t0 = datetime.datetime(2026, 9, 22, 12, 0, tzinfo=datetime.timezone.utc)
    write_log(paths, [tick(t0, cpu=12.0)])
    record_cpu_anomaly(paths, ts=t0)
    out = api.dashboard(paths, sample=_sample_payload())
    for key in ("app", "version", "root", "territory", "daemon", "sample",
                "thresholds", "series", "events", "resolutions",
                "interventions", "processes", "log", "kb", "arriving"):
        assert key in out, key
    assert out["demo"] is False  # nada aqui e maquete
    assert out["processes"][0]["name"] == "jogo.exe"
    assert out["events"][0]["metric"] == "cpu"
    assert out["series"]["cpu"]["points"] == [12.0]
    assert out["kb"]["cpu"]


def test_dashboard_nao_medir_novamente_o_que_o_daemon_ja_mediu(paths):
    """`sample` injetado e o caminho da GUI; sem ele o dashboard mede uma vez
    e nao dez."""
    out = api.dashboard(paths, sample=_sample_payload())
    assert out["sample"]["cpu_percent"] == 12.0
    assert out["territory"] == str(paths.output_dir)

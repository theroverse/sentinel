"""Testes do CLI em modo maquina (a superficie que a GUI e um agente chamam).

O que estes testes seguram sao duas promessas diferentes:

- pureza: com `--json`, o stdout e UMA resposta JSON e nada mais, porque quem
  chama faz `json.loads(stdout)`. O texto humano, se existir, vai pro stderr.
- codigo de saida: 0 so quando a operacao deu certo. Uma recusa do `kill` ou
  um `fix` sem `--plan` nao podem sair como sucesso.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest

from conftest import make_sample, proc

from sentinel import cli, settings
from sentinel.detector import SEV_CRITICAL, Finding
from sentinel.events import STATUS_RESOLVED, EventStore


# ------------------------------------------------------------------ helpers --
@pytest.fixture
def paths(tmp_path):
    p = settings.paths_for(tmp_path)
    p.ensure_output_dir()
    return p


def run(tmp_path, capsys, *argv):
    """Chama o CLI de verdade e devolve (codigo de saida, stdout, stderr)."""
    monkey = Path("sentinel.py")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("sys.argv", ["sentinel.py", "--dir", str(tmp_path), *argv])
        with pytest.raises(SystemExit) as exc:
            cli.main(monkey)
    cap = capsys.readouterr()
    return exc.value.code, cap.out, cap.err


def payload(out: str) -> dict:
    """Decodifica o stdout exigindo pureza: uma chamada, um objeto JSON."""
    text = out.strip()
    assert text, "stdout vazio em modo maquina"
    return json.loads(text)


def abrir_anomalia(paths, *, culprit="chrome.exe"):
    finding = Finding(
        metric="cpu",
        severity=SEV_CRITICAL,
        value=97.0,
        threshold=settings.CPU_CRITICAL,
        samples=5,
        span_s=10.0,
        top_processes=[proc(11, culprit, cpu=40.0, rss_mb=900.0)],
        fingerprint=f"cpu:critical:{culprit}",
    )
    return EventStore(paths.events).record_finding(finding, make_sample(cpu=97.0))


FAKE_SAMPLE = {
    "ts": "2026-09-22T12:00:00+00:00",
    "cpu_percent": 12.0, "ram_percent": 34.0, "disk_percent": 50.0,
    "disk_path": "C:\\", "io_busy_percent": 1.0,
    "net_recv_bps": 0.0, "net_sent_bps": 0.0,
    "swap_percent": 0.0, "swap_activity_ps": 0.0,
    "top_cpu": [{"pid": 9, "name": "jogo.exe", "cpu": 12.0, "rss_mb": 100.0}],
    "top_mem": [],
}


@pytest.fixture
def sem_medicao(monkeypatch):
    """Nenhuma test de CLI acorda o sensor real: medir 0,6 s por teste e
    resultado de maquina, nao da regra."""
    monkeypatch.setattr(cli.api, "live_sample", lambda **k: dict(FAKE_SAMPLE))
    return FAKE_SAMPLE


# ------------------------------------------------------------------ status --
def test_status_json_e_so_json_no_stdout(paths, capsys):
    rc, out, err = run(paths.root, capsys, "status", "--json")
    assert rc == 0
    data = payload(out)
    assert data["app"] == "sentinel"
    assert data["daemon"]["running"] is False
    assert err == ""


def test_status_humano_nao_imprime_json(paths, capsys):
    rc, out, _ = run(paths.root, capsys, "status")
    assert rc == 0
    pytest.raises(json.JSONDecodeError, json.loads, out.strip() or "")


# ----------------------------------------------------------------- metrics --
def test_metrics_json_responde_o_painel_inteiro(paths, capsys, sem_medicao):
    abrir_anomalia(paths)
    rc, out, _ = run(paths.root, capsys, "metrics", "--json")
    assert rc == 0
    data = payload(out)
    assert data["demo"] is False
    assert data["sample"]["cpu_percent"] == 12.0
    assert data["processes"][0]["name"] == "jogo.exe"
    assert data["events"][0]["metric"] == "cpu"
    assert data["kb"]["cpu"]


def test_metrics_json_respeita_os_limites_de_history_e_log(paths, capsys, sem_medicao):
    t0 = datetime.datetime(2026, 9, 22, 12, 0, tzinfo=datetime.timezone.utc)
    lines = [
        f"{(t0 + datetime.timedelta(seconds=i)).isoformat()} tick cpu={float(i)} "
        f"ram=0.0 disk=0.0 io=0.0 swap=0.0 swap_rate=0 net_down_bps=0 net_up_bps=0"
        for i in range(10)
    ]
    paths.daemon_log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _, out, _ = run(paths.root, capsys, "metrics", "--json", "--history", "3", "--log", "2")
    data = payload(out)
    assert data["series"]["cpu"]["points"] == [7.0, 8.0, 9.0]
    assert len(data["log"]) == 2


def test_metrics_humano_aponta_o_caminho_da_maquina(paths, capsys, sem_medicao):
    rc, out, _ = run(paths.root, capsys, "metrics")
    assert rc == 0
    assert "--json" in out
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)


# --------------------------------------------------------------- fix plan --
def test_fix_plan_json_devolve_as_opcoes_com_key(paths, capsys):
    event = abrir_anomalia(paths)
    rc, out, _ = run(paths.root, capsys, "fix", event["id"], "--plan", "--json")
    assert rc == 0
    data = payload(out)
    assert data["event_id"] == event["id"]
    assert 0 < len(data["options"]) <= settings.MAX_FIX_OPTIONS
    assert all(o["key"] for o in data["options"])
    assert all(o["why"] for o in data["options"])


def test_fix_json_sem_plan_nem_resolve_recusa_em_vez_de_dialogar(paths, capsys):
    """Dialogo nao tem o que responder pra maquina — e dizer isso, nao travar
    esperando tecla."""
    abrir_anomalia(paths)
    rc, out, _ = run(paths.root, capsys, "fix", "--json")
    assert rc == 1
    data = payload(out)
    assert data["ok"] is False
    assert "--plan" in data["error"]


def test_fix_resolve_json_fecha_o_ciclo_e_grava_resolucao(paths, capsys):
    event = abrir_anomalia(paths)
    _, plan_out, _ = run(paths.root, capsys, "fix", event["id"], "--plan", "--json")
    primeira = payload(plan_out)["options"][0]

    rc, out, _ = run(
        paths.root, capsys, "fix", event["id"], "--resolve", "fixed",
        "--option", "0", "--key", primeira["key"], "--json",
    )
    assert rc == 0
    data = payload(out)
    assert data["ok"] is True
    assert data["status"] == STATUS_RESOLVED
    assert data["resolution_id"].startswith("res-")
    evento = EventStore(paths.events).find(event["id"])
    assert evento["status"] == STATUS_RESOLVED


def test_fix_resolve_de_anomalia_inexistente_sai_como_erro(paths, capsys):
    rc, out, _ = run(paths.root, capsys, "fix", "evt-que-nao-existe",
                     "--resolve", "fixed", "--json")
    assert rc == 1
    assert payload(out)["ok"] is False


# -------------------------------------------------------------------- kill --
def test_kill_json_de_pid_inexistente_sai_com_erro(paths, capsys):
    """Sucesso so quando um processo morreu de fato; rc 0 com `killed: []`
    faria a GUI mostrar 'encerrado' para o nada."""
    rc, out, _ = run(paths.root, capsys, "kill", "999999", "--yes", "--json")
    assert rc == 1
    data = payload(out)
    assert data["ok"] is False
    assert data["killed"] == []


def test_kill_sem_yes_nem_pede_confirmacao_em_sessao_sem_tty(paths, capsys):
    """Sem tty nao ha como responder a pergunta: a saida tem que ser recusa
    explicita, nao um programa parado esperando tecla."""
    rc, out, _ = run(paths.root, capsys, "kill", "999999", "--json")
    assert rc == 1
    assert payload(out)["ok"] is False


# ------------------------------------------------------------- events json --
def test_events_json_continua_uma_linha_por_evento(paths, capsys):
    """Formato historico: agentes leem isto linha a linha; nao pode virar um
    array unico."""
    abrir_anomalia(paths)
    rc, out, _ = run(paths.root, capsys, "events", "--json")
    assert rc == 0
    linhas = [l for l in out.splitlines() if l.strip()]
    assert len(linhas) == 1
    assert json.loads(linhas[0])["kind"] == "anomaly"


# ------------------------------------------------------ pause / resume -----
def test_pause_e_resume_json_reportam_o_kill_switch(paths, capsys):
    _, out, _ = run(paths.root, capsys, "pause", "--json")
    assert payload(out)["paused"] is True
    assert paths.paused.is_file()

    _, out, _ = run(paths.root, capsys, "resume", "--json")
    assert payload(out)["paused"] is False
    assert not paths.paused.exists()


def test_metrics_json_mostra_o_pause_na_janela_da_gui(paths, capsys, sem_medicao):
    run(paths.root, capsys, "pause", "--json")
    _, out, _ = run(paths.root, capsys, "metrics", "--json")
    assert payload(out)["daemon"]["paused"] is True

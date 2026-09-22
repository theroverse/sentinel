from __future__ import annotations

import json
import urllib.error

import pytest

from sentinel import settings
from sentinel.local_model import complete, config, parse_options, probe


# O motor roda em loopback num teste offline: cada caso empresta um `post`
# ou `get` fake, que devolve o que o caso quer e registra o que foi
# perguntado. Nenhuma linha daqui abre socket.


@pytest.fixture(autouse=True)
def _no_env_host(monkeypatch):
    """Limpa as env vars do motor: senao a maquina de quem roda os testes
    (que pode ter SENTINEL_OLLAMA_HOST definida) muda o resultado."""
    monkeypatch.delenv(settings.OLLAMA_HOST_ENV, raising=False)
    monkeypatch.delenv(settings.OLLAMA_MODEL_ENV, raising=False)


def _json(status, data):
    return status, json.dumps(data).encode("utf-8")


def _http_error(url, code):
    return urllib.error.HTTPError(url, code, "nope", {}, None)  # type: ignore[arg-type]


# -- config: env > config.json > padrao, e o veto de loopback -------------
def test_config_defaults_to_loopback_ollama():
    cfg = config()
    assert cfg["base"] == settings.DEFAULT_MODEL_BASE
    assert cfg["model"] == settings.DEFAULT_MODEL_NAME
    assert cfg["refused"] is None


def test_config_json_is_used_when_there_is_no_env():
    cfg = config({"ollama_host": "localhost:1234", "ollama_model": "um-modelo"})
    assert cfg["base"] == "http://localhost:1234"  # esquema ganha do usuario
    assert cfg["model"] == "um-modelo"


def test_env_beats_config_json(monkeypatch):
    monkeypatch.setenv(settings.OLLAMA_HOST_ENV, "http://127.0.0.1:11434/")
    monkeypatch.setenv(settings.OLLAMA_MODEL_ENV, "outro")
    cfg = config({"ollama_host": "http://127.0.0.1:9999", "ollama_model": "velho"})
    assert cfg["base"] == "http://127.0.0.1:11434"  # barra final fora
    assert cfg["model"] == "outro"


def test_a_remote_host_is_refused_by_the_code_not_by_the_config(monkeypatch):
    """A invariante de privacidade: nenhuma combinacao de env/config abre
    excecao. Um host que nao e esta maquina esta recusado."""
    for host in (
        "http://10.0.0.5:11434",
        "https://ollama.example.com",
        "192.168.1.10:11434",
    ):
        monkeypatch.setenv(settings.OLLAMA_HOST_ENV, host)
        assert config()["refused"], host


def test_ipv6_loopback_counts_as_local(monkeypatch):
    monkeypatch.setenv(settings.OLLAMA_HOST_ENV, "http://[::1]:11434")
    assert config()["refused"] is None


# -- complete() -----------------------------------------------------------
def test_complete_asks_ollama_first():
    calls = []

    def post(url, body, timeout):
        calls.append((url, json.loads(body), timeout))
        return _json(200, {"response": "  [{}]  "})

    assert complete("p", post=post) == "[{}]"
    url, payload, timeout = calls[0]
    assert url.endswith("/api/generate")
    assert payload["stream"] is False
    assert payload["model"] == settings.DEFAULT_MODEL_NAME
    assert timeout == settings.MODEL_TIMEOUT_S


def test_complete_falls_to_the_openai_route_when_ollama_has_no_such_path():
    """LM Studio e llama.cpp server respondem na mesma porta, mas nao tem
    /api/generate. Um 404 e 'troca de dialeto', nao 'motor ausente'."""
    seen = []

    def post(url, body, timeout):
        seen.append(url)
        if url.endswith("/api/generate"):
            raise _http_error(url, 404)
        return _json(200, {"choices": [{"message": {"content": "ola"}}]})

    assert complete("p", post=post) == "ola"
    assert seen[-1].endswith("/v1/chat/completions")


def test_a_dead_port_does_not_cost_two_timeouts():
    """Recusa de conexao encerra na primeira rota: esperar o segundo
    transporte atras de um host morto e so dobrar a espera pelo mesmo nada."""
    calls = []

    def post(url, body, timeout):
        calls.append(url)
        raise urllib.error.URLError("connection refused")

    assert complete("p", post=post) is None
    assert len(calls) == 1


def test_complete_refused_before_the_network(monkeypatch, capsys):
    monkeypatch.setenv(settings.OLLAMA_HOST_ENV, "http://evil.example:11434")

    def post(url, body, timeout):  # nunca deve rodar
        raise AssertionError("o Sentinel tentou falar fora da maquina")

    assert complete("p", post=post) is None
    assert "loopback" in capsys.readouterr().out


def test_complete_returns_none_when_the_answer_has_no_text(capsys):
    def post(url, body, timeout):
        return _json(200, {"response": "   "})

    assert complete("p", post=post) is None
    assert "sem texto" in capsys.readouterr().out


def test_complete_returns_none_when_no_dialect_matches():
    """Servidor vivo que nao e nenhum dos dois: o tutor recebe None e a base
    curada assume — sem excecao pra fora."""

    def post(url, body, timeout):
        raise _http_error(url, 404)

    assert complete("p", post=post) is None


def test_an_http_error_is_reported_not_raised(capsys):
    """Um 500 nao e 'troca de dialeto': e o motor doente. O tutor recebe
    None (e cai na base curada), e o motivo impresso cita a rota tentada —
    da pra diagnosticar sem repetir o comando em debug."""

    def post(url, body, timeout):
        raise _http_error(url, 500)

    assert complete("p", post=post) is None
    out = capsys.readouterr().out
    assert "HTTP 500" in out and "/api/generate" in out


# -- probe(): sonda, nunca provisionamento --------------------------------
def _routes(table):
    """GET fake sobre um dict caminho->resposta. 404 para o que nao esta na
    tabela, como um servidor de verdade faria."""

    def get(url, timeout):
        for path, value in table.items():
            if url.endswith(path):
                if isinstance(value, Exception):
                    raise value
                return _json(200, value)
        raise _http_error(url, 404)

    return get


def test_probe_reads_version_and_confirms_the_model_is_loaded():
    get = _routes(
        {
            "/api/version": {"version": "0.34.2"},
            "/api/tags": {"models": [{"name": "qwen3-coder-next:latest"}]},
        }
    )
    report = probe(get=get)
    assert report["transport"] == "ollama"
    assert report["version"] == "0.34.2"
    assert report["model_present"] is True
    assert report["reason"] == ""


def test_probe_says_when_the_model_is_not_announced():
    get = _routes(
        {
            "/api/version": {"version": "0.34.2"},
            "/api/tags": {"models": [{"name": "llama3.2:latest"}]},
        }
    )
    report = probe(get=get)
    assert report["transport"] == "ollama"
    assert report["model_present"] is False
    assert settings.DEFAULT_MODEL_NAME in report["reason"]


def test_probe_does_not_claim_absence_when_the_engine_lists_nothing():
    """Um servidor que responde mas nao lista modelos nao autoriza um
    `False`: sem lista, nao se pode afirmar nada, e afirmar seria mentira."""
    get = _routes({"/api/version": {"version": "0.34.2"}, "/api/tags": {"models": []}})
    assert probe(get=get)["model_present"] is None


def test_probe_finds_an_openai_compatible_server():
    get = _routes(
        {
            "/api/version": _http_error("/api/version", 404),
            "/v1/models": {"data": [{"id": "qwen3-coder-next-q2k"}]},
        }
    )
    report = probe(get=get)
    assert report["transport"] == "openai"
    assert report["model_present"] is True


def test_probe_on_a_dead_port_stops_at_the_first_route():
    calls = []

    def get(url, timeout):
        calls.append(url)
        raise urllib.error.URLError("nope")

    report = probe(get=get)
    assert report["transport"] is None
    assert "nada respondendo" in report["reason"]
    assert len(calls) == 1


def test_probe_never_probes_a_remote_host(monkeypatch):
    monkeypatch.setenv(settings.OLLAMA_HOST_ENV, "http://10.0.0.5:11434")

    def get(url, timeout):
        raise AssertionError("a sonda nao pode sair da maquina")

    report = probe(get=get)
    assert report["transport"] is None
    assert "loopback" in report["reason"]


def test_probe_uses_the_short_timeout():
    """Status roda em terminal, as vezes com o motor desligado: tem que
    desistir em segundos, nao no tempo de geracao."""
    seen = []

    def get(url, timeout):
        seen.append(timeout)
        return _json(200, {"version": "0.34.2"})

    probe(get=get)
    assert len(seen) == 2  # vida + lista de modelos
    assert set(seen) == {settings.MODEL_PROBE_TIMEOUT_S}


# -- parse_options (tolerante a cerca de codigo / prosa) -----------------
def test_parse_plain_json_array():
    text = '[{"title": "A", "steps": ["um", "dois"]}]'
    assert parse_options(text, max_options=3) == [
        {"title": "A", "steps": ["um", "dois"]}
    ]


def test_parse_with_code_fence_and_prose():
    text = (
        "Claro! Aqui esta:\n"
        "```json\n"
        '[{"title": "X", "steps": ["a"], "action": {"type": "kill_top_process"}}]\n'
        "```\n"
        "Espero ter ajudado."
    )
    options = parse_options(text, max_options=3)
    assert options[0]["action"]["type"] == "kill_top_process"


def test_parse_keeps_the_assertive_fields():
    text = json.dumps(
        [
            {
                "title": "Fecha o que nao usa",
                "why": "libera as paginas residentes",
                "steps": ["um"],
                "proof": "o medidor cai",
                "risk": "voce perde a sessao",
                "reversible": False,
            }
        ]
    )
    option = parse_options(text, max_options=3)[0]
    assert option["why"].startswith("libera")
    assert option["proof"] == "o medidor cai"
    assert option["risk"] == "voce perde a sessao"
    assert option["reversible"] is False


def test_parse_drops_malformed_options():
    text = (
        '[{"title": "ok", "steps": ["a"]}, '
        '{"no_title": true}, {"title": "no steps"}, '
        '{"title": "empty", "steps": []}]'
    )
    options = parse_options(text, max_options=3)
    assert len(options) == 1
    assert options[0]["title"] == "ok"


def test_parse_truncates_to_max():
    arr = [{"title": str(i), "steps": ["x"]} for i in range(10)]
    assert len(parse_options(json.dumps(arr), max_options=3)) == 3


def test_parse_returns_none_on_garbage():
    assert parse_options("sem json aqui", max_options=3) is None
    assert parse_options("", max_options=3) is None

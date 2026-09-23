from __future__ import annotations

# Motor de modelo LOCAL: a unica saida de rede do Sentinel, e ela nao sai da
# maquina.
#
# Substitui a ponte `claude -p`. O desenho todo decorre de tres fatos que o
# usuario decidiu antes do codigo existir:
#
#   1. Nada de IA paga. O motor e um servidor na propria maquina (Ollama, ou
#      qualquer endpoint OpenAI-compativel — LM Studio, llama.cpp server).
#   2. Quem prove o motor e o usuario. Este modulo so pergunta: nao instala,
#      nao baixa, nao puxa modelo. `probe()` existe pra dizer o que encontrou.
#   3. Ausencia do motor e estado normal, nao erro: quem chama recebe None e
#      cai na base curada (`kb`), que responde sem pedir nada a ninguem.
#
# Por isso as duas funcoes publicas sao curtas — `complete()` devolve texto
# ou None, `probe()` devolve diagnostico. Ninguem aqui decide o que fazer com
# a resposta; isso e do `tutor`.

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from sentinel import settings


# Ordem importa: Ollama e o motor escolhido; o dialeto OpenAI cobre os
# servidores que so falam essa lingua na mesma porta de loopback.
TRANSPORT_OLLAMA = "ollama"
TRANSPORT_OPENAI = "openai"
TRANSPORTS = (TRANSPORT_OLLAMA, TRANSPORT_OPENAI)


class EngineAbsent(Exception):
    """Nao ha nada respondendo naquele endereco (ou ha, e respondeu erro).

    Excecao esperada e comum: e o caminho de uma maquina sem Ollama ligado.
    Quem chama traduz em "a base curada responde", nunca em stack trace.
    """


class _DialectMismatch(Exception):
    """Tem servidor, mas ele nao tem aquela rota: tenta o outro dialeto.

    So 404/405 chegam aqui. Uma recusa de conexao NAO cai nesta classe — se o
    host esta morto, o segundo transporte so faria o usuario esperar mais um
    timeout pelo mesmo nada.
    """


# --------------------------------------------------------------------------
# Resolucao de endereco (env > config.json > padrao) + o veto de loopback
# --------------------------------------------------------------------------
def base_url(overrides: dict | None = None) -> str:
    """Endereco do motor, sem barra final. Aceita `localhost:11434` sem
    esquema porque e assim que as pessoas escrevem."""
    raw = (
        os.environ.get(settings.OLLAMA_HOST_ENV)
        or (overrides or {}).get("ollama_host")
        or settings.DEFAULT_MODEL_BASE
    )
    raw = str(raw).strip() or settings.DEFAULT_MODEL_BASE
    if "://" not in raw:
        raw = "http://" + raw
    return raw.rstrip("/")


def model_name(overrides: dict | None = None) -> str:
    """Id do modelo como o motor local o anuncia (`ollama list` /
    `GET /v1/models`). Uma tag de registry nao: nao ha download aqui."""
    raw = (
        os.environ.get(settings.OLLAMA_MODEL_ENV)
        or (overrides or {}).get("ollama_model")
        or settings.DEFAULT_MODEL_NAME
    )
    return str(raw).strip() or settings.DEFAULT_MODEL_NAME


def refused_reason(base: str) -> str | None:
    """Motivo para NAO perguntar, ou None se o endereco e de loopback.

    A invariante de privacidade mora aqui, e nao no config.json: um host
    remoto esta recusado no codigo, entao uma env var esquecida ou um config
    editado por outra mao nao transformam o Sentinel em upload de dados.
    """
    host = (urllib.parse.urlparse(base).hostname or "").lower()
    if host in settings.MODEL_LOOPBACK_HOSTS:
        return None
    return (
        f"{base} nao e esta maquina (host {host or 'ilegivel'}); "
        "o Sentinel so pergunta a um motor em loopback"
    )


def config(overrides: dict | None = None) -> dict:
    """Onde perguntar, o que pedir, e se esta proibido de perguntar."""
    base = base_url(overrides)
    return {"base": base, "model": model_name(overrides), "refused": refused_reason(base)}


# --------------------------------------------------------------------------
# HTTP — com as duas costuras injetaveis (`post`/`get`) que deixam o modulo
# testavel sem rede nenhuma
# --------------------------------------------------------------------------
def _why(exc: BaseException) -> str:
    reason = getattr(exc, "reason", None)
    return str(reason if reason is not None else exc)


def _http_post(url: str, body: bytes, timeout: float):
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read()


def _http_get(url: str, timeout: float):
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read()


def _check(exc: urllib.error.HTTPError):
    """HTTPError -> a excecao certa. 404/405 e 'rota errada'; o resto e
    'motor indisponivel'."""
    if exc.code in (404, 405):
        return _DialectMismatch(str(exc.code))
    return EngineAbsent(f"HTTP {exc.code}")


def _request_json(url, body, *, fetch, timeout):
    """Uma chamada, um resultado: o dict decodificado, ou a excecao que
    explica por que nao.

    `body=None` e o GET; qualquer outra coisa e POST com JSON. As duas rotas
    compartilham a traducao de erro porque o que importa e a distinguicao:
    404/405 e 'rota errada, tenta o outro dialeto', e tudo o resto e 'motor
    indisponivel'.
    """
    try:
        status, raw = fetch(url, timeout) if body is None else fetch(url, body, timeout)
    except urllib.error.HTTPError as exc:
        raise _check(exc) from None
    except (urllib.error.URLError, OSError) as exc:
        raise EngineAbsent(_why(exc)) from None
    if status >= 400:
        raise EngineAbsent(f"HTTP {status}")
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except (ValueError, AttributeError):
        raise EngineAbsent("resposta sem JSON") from None
    if not isinstance(data, dict):
        raise EngineAbsent("resposta JSON sem objeto no topo")
    return data


def _post(url, payload, *, fetch, timeout):
    body = json.dumps(payload).encode("utf-8")
    return _request_json(url, body, fetch=fetch, timeout=timeout)


def _get(url, *, fetch, timeout):
    return _request_json(url, None, fetch=fetch, timeout=timeout)


def _url(base: str, transport: str) -> str:
    return base + ("/api/generate" if transport == TRANSPORT_OLLAMA else "/v1/chat/completions")


def _payload(transport: str, model: str, prompt: str) -> dict:
    if transport == TRANSPORT_OLLAMA:
        return {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": settings.MODEL_TEMPERATURE,
                "num_predict": settings.MODEL_MAX_TOKENS,
            },
        }
    return {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "temperature": settings.MODEL_TEMPERATURE,
        "max_tokens": settings.MODEL_MAX_TOKENS,
    }


def _answer_text(transport: str, data: dict) -> str:
    if transport == TRANSPORT_OLLAMA:
        value = data.get("response")
        return value.strip() if isinstance(value, str) else ""
    choices = data.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            return content.strip()
    return ""


# --------------------------------------------------------------------------
# Publico: completar um prompt, e sondar o motor
# --------------------------------------------------------------------------
def complete(prompt: str, *, overrides=None, timeout=None, post=None) -> str | None:
    """Manda `prompt` ao motor local e devolve o texto, ou None.

    None em qualquer falha, com o motivo impresso — o mesmo contrato que a
    ponte anterior tinha, porque quem chama (o `tutor`) ja trata None como
    "a base curada assume". O daemon nunca chama isto.

    Ao contrario da ponte antiga, o custo de uma maquina sem motor e zero:
    a primeira recusa de conexao encerra a tentativa, sem esperar o timeout
    do segundo transporte atras de um host morto.
    """
    cfg = config(overrides)
    if cfg["refused"]:
        print(f"[motor local] recusa: {cfg['refused']}")
        return None

    fetch = post or _http_post
    wait = settings.MODEL_TIMEOUT_S if timeout is None else timeout
    for transport in TRANSPORTS:
        url = _url(cfg["base"], transport)
        try:
            data = _post(
                url,
                _payload(transport, cfg["model"], prompt),
                fetch=fetch,
                timeout=wait,
            )
        except _DialectMismatch:
            continue
        except EngineAbsent as exc:
            print(f"[motor local] sem motor em {url}: {exc}")
            return None

        text = _answer_text(transport, data)
        if text:
            return text
        print(
            f"[motor local] {cfg['base']} respondeu pelo dialeto {transport}, "
            "mas sem texto na resposta."
        )
        return None

    print(
        f"[motor local] {cfg['base']} tem um servidor, mas nao fala nem Ollama "
        "nem OpenAI."
    )
    return None


def _names(data: dict) -> list[str]:
    """Nomes de modelo nos tres formatos que aparecem por ai: Ollama
    (`models[].name`), OpenAI (`data[].id`), e o array solto de alguns
    servidores llama.cpp."""
    rows = data.get("models")
    if not isinstance(rows, list):
        rows = data.get("data")
    if not isinstance(rows, list):
        rows = []
    names: list[str] = []
    for row in rows:
        if isinstance(row, dict):
            value = row.get("name") or row.get("model") or row.get("id")
            if isinstance(value, str) and value.strip():
                names.append(value.strip())
        elif isinstance(row, str) and row.strip():
            names.append(row.strip())
    return names


def _model_present(want: str, names: list[str]):
    """True/False, ou None quando o servidor nao listou nada — ausencia de
    lista nao e ausencia de modelo, e afirmar o contrario mentiria no
    `model status`."""
    if not names:
        return None
    needle = want.split(":")[0].lower()
    return any(needle in n.lower() for n in names)


def probe(*, overrides=None, timeout=None, get=None) -> dict:
    """O que ha do outro lado do endereco: vivo, morto, ou vivo-e-de-outra-
    lingua. So leitura — nao instala, nao baixa, nao cria arquivo.

    Devolve sempre um dict com o mesmo formato (pra `--json` e pra GUI):
    base, model, transport, version, model_present, usable, reason.
    """
    cfg = config(overrides)
    report = {
        "base": cfg["base"],
        "model": cfg["model"],
        "transport": None,
        "version": None,
        "model_present": None,
        "usable": False,
        "reason": cfg["refused"] or "",
    }
    if cfg["refused"]:
        return report

    fetch = get or _http_get
    wait = settings.MODEL_PROBE_TIMEOUT_S if timeout is None else timeout

    # (dialeto, rota de vida, rota da lista de modelos)
    routes = (
        (TRANSPORT_OLLAMA, "/api/version", "/api/tags"),
        (TRANSPORT_OPENAI, "/v1/models", None),
    )
    dead_end = ""
    for transport, alive_path, list_path in routes:
        try:
            data = _get(
                cfg["base"] + alive_path,
                fetch=fetch,
                timeout=wait,
            )
        except EngineAbsent as exc:
            # Host morto: o outro dialeto esta no mesmo host morto.
            report["reason"] = f"nada respondendo em {cfg['base']}{alive_path} ({exc})"
            return report
        except _DialectMismatch:
            dead_end = f"{cfg['base']} nao tem a rota {alive_path}"
            continue

        report["transport"] = transport
        version = data.get("version")
        report["version"] = version if isinstance(version, str) else None

        names: list[str] = _names(data)
        if list_path:
            try:
                listed = _get(
                    cfg["base"] + list_path, fetch=fetch, timeout=wait
                )
                names = _names(listed) or names
            except EngineAbsent:
                pass  # o motor responde mas nao lista: model_present fica None
        report["model_present"] = _model_present(cfg["model"], names)
        report["usable"] = report["model_present"] is not False
        if not report["usable"]:
            report["reason"] = f"o motor nao anuncia o modelo {cfg['model']}"
        return report

    report["reason"] = dead_end or f"o motor em {cfg['base']} nao respondeu"
    return report


# --------------------------------------------------------------------------
# Leitura da resposta do modelo (o contrato assertivo)
# --------------------------------------------------------------------------
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_options(text: str, *, max_options: int) -> list[dict] | None:
    """Converte a resposta do modelo em lista de opcoes. Tolera cerca de
    codigo e prosa ao redor: isola o primeiro array JSON [ ... ]. Devolve
    None se nada utilizavel sair — ai o tutor cai no fallback do kb.

    O contrato assertivo (title/why/steps/proof/risk/reversible) e validado
    com tolerancia de proposito: `title`+`steps` sao inegociaveis, e um
    modelo que respondeu um tutorial bom sem o campo `why` merece ser
    ouvido — nao descartado por formatacao. Quem escreve na base guarda o
    que veio vazio como vazio, e o `origin` diz que aquilo nao e curado.

    Opcoes malformadas sao descartadas uma a uma, sem derrubar o lote.
    Trunca em max_options.
    """
    if not text:
        return None

    candidate = text

    fenced = _FENCE.search(text)
    if fenced:
        candidate = fenced.group(1)

    start = candidate.find("[")
    end = candidate.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None

    blob = candidate[start : end + 1]

    try:
        data = json.loads(blob)
    except ValueError:
        return None

    if not isinstance(data, list):
        return None

    options: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        title = item.get("title")
        steps = item.get("steps")
        if not isinstance(title, str) or not isinstance(steps, list):
            continue
        steps = [str(s) for s in steps if str(s).strip()]
        if not steps:
            continue
        option = {"title": title.strip(), "steps": steps}
        for field in ("why", "proof", "risk"):
            value = item.get(field)
            if isinstance(value, str) and value.strip():
                option[field] = value.strip()
        if "reversible" in item:
            option["reversible"] = bool(item["reversible"])
        action = item.get("action")
        if isinstance(action, dict) and isinstance(action.get("type"), str):
            option["action"] = action
        options.append(option)

    if not options:
        return None

    return options[:max_options]

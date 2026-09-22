from __future__ import annotations

from dataclasses import dataclass, field

from sentinel import kb, kbstore, local_model, prompts, settings
from sentinel.events import (
    OUTCOME_DISMISSED,
    OUTCOME_FIXED,
    OUTCOME_NOT_FIXED,
    STATUS_DISMISSED,
    STATUS_RESOLVED,
    EventStore,
)
from sentinel.processctl import ProcessCtl


# Respostas possiveis no ponto de validacao do usuario.
RESPONSE_FIXED = "fixed"
RESPONSE_NEXT = "next"
RESPONSE_DISMISS = "dismiss"


@dataclass
class TutorOutcome:
    """Resultado de um ciclo de tutoria. `outcome` vazio = so apresentou
    (modo nao-interativo), sem resolucao gravada.

    `layer` e o numero da camada que respondeu (ver `kbstore`): e o que
    `--explain-source` mostra, e o que diz se o Sentinel tirou da propria
    memoria ou se precisou perguntar ao modelo.
    """

    outcome: str
    option_index: int | None
    source: str
    tried: int = 0
    detail: str = ""
    layer: int = 0

    @property
    def wrote_resolution(self) -> bool:
        return self.outcome in (OUTCOME_FIXED, OUTCOME_NOT_FIXED, OUTCOME_DISMISSED)



_INCIDENT_DETAIL_LABELS = (
    ("kind", "Tipo", {"crash": "queda (o processo morreu)", "hang": "travamento (parou de responder)"}),
    ("app", "Aplicativo", None),
    ("app_version", "Versao do aplicativo", None),
    ("module", "Modulo culpado", None),
    ("exception_code", "Codigo de excecao", None),
    ("pid", "PID registrado no evento", None),
    ("at", "Hora do evento (UTC)", None),
    ("provider", "Fonte no Event Log", None),
    ("event_id", "EventID", None),
)


def _incident_facts(event: dict) -> str:
    """Bloco 'o que foi medido' pra anomalia de incidente.

    Uma queda de app e uma arvore órfã não têm número nenhum pra colocar no
    molde de limiar — o que sustenta um tutorial bom aqui é o nome do modulo,
    o código de exceção e o mapa dos processos que sobraram. Sem isso, o
    modelo recebe uma anomalia vazia e inventa.
    """
    detail = event.get("detail") or {}
    if not detail:
        return ""

    rows: list[str] = []
    if event.get("label"):
        rows.append(f"- Ocorrencia: {event['label']}")
    occurrences = int(event.get("occurrences", 1) or 1)
    if occurrences > 1:
        # O loop de queda e o dado mais forte que existe aqui: muda a
        # resposta de "feche e reabra" pra "isto esta quebrado de verdade".
        rows.append(f"- Ja aconteceu {occurrences} vezes no mesmo episodio")
    for key, label, mapping in _INCIDENT_DETAIL_LABELS:
        value = detail.get(key)
        if value in (None, ""):
            continue
        rows.append(f"- {label}: {mapping.get(value, value) if mapping else value}")

    parent = detail.get("parent")
    if parent:
        rows.append(f"- Pai que morreu: {parent.get('name')} (pid {parent.get('pid')})")
    tree = detail.get("tree") or []
    for row in tree:
        rows.append(
            f"- Sobreviveu: pid {row.get('pid')} {row.get('name')} "
            f"(profundidade {row.get('depth')}, pai declarado {row.get('ppid')})"
        )

    if not rows:
        return ""
    return (
        "\n\nFatos medidos neste incidente (nao foi um limiar que estourou; "
        "foi isto que aconteceu):\n" + "\n".join(rows)
    )


def build_prompt(event: dict) -> str:
    metric = event.get("metric", "")
    top = event.get("top_processes", [])
    top_lines = "\n".join(
        f"  - pid={p.get('pid')} {p.get('name')} "
        f"cpu={p.get('cpu')}% rss={p.get('rss_mb')}MB"
        for p in top
    ) or "  (nenhum processo associado)"
    window = event.get("window", {})
    is_incident = "value" not in event
    span_note = (
        "nao se aplica: nao e pico sustentado, e um fato que aconteceu"
        if is_incident
        else prompts.span_note(
            int(window.get("samples", 1)), float(window.get("span_s", 0.0))
        )
    )
    return (
        prompts.TUTOR_PROMPT.format(
            max_options=settings.MAX_FIX_OPTIONS,
            metric=metric,
            severity=event.get("severity", ""),
            value="(nao se aplica: anomalia de incidente)" if is_incident else event.get("value", ""),
            threshold="(nao se aplica)" if is_incident else event.get("threshold", ""),
            span_note=span_note,
            top_processes=top_lines,
        )
        + _incident_facts(event)
    )


def propose(
    event: dict,
    *,
    overrides: dict | None = None,
    db: kbstore.KbStore | None = None,
) -> tuple[list[dict], str, int]:
    """PROPOSE na ordem que o pedido exige: a base local responde primeiro.

    1-3. `.sentinel/kb.db` — fingerprint exato, depois metrica+causa, depois
       a camada generica (o catalogo de `kb.py`). Acertou aqui, nenhuma
       inferencia roda: a resposta boa e local e instantanea.
    4.   o modelo, e o resultado VIRA entrada na base (`db.learn`), pra que
       a proxima vez desta mesma anomalia a resposta saia dos passos 1-3.

    Devolve (opcoes, fonte, camada). Sem `db` aberta, cai direto na camada
    generica ou no modelo — a base e memoria, nao requisito.
    """
    if db is not None:
        options, layer = db.lookup(event)
        if options:
            return options, kbstore.LAYER_NAME[layer], layer

    raw = local_model.complete(build_prompt(event), overrides=overrides)
    if raw:
        options = local_model.parse_options(raw, max_options=settings.MAX_FIX_OPTIONS)
        if options:
            if db is not None:
                db.learn(event, options, source=kbstore.LAYER_MODEL)
            layer = kbstore.LAYER_MODEL
            return options, "modelo", layer

    metric = event.get("metric", "")
    options = kb.options_for(metric, event=event)
    return options, kbstore.LAYER_NAME[kbstore.LAYER_METRIC], kbstore.LAYER_METRIC



def render_option(option: dict, index: int, total: int) -> str:
    """RENDER: texto de uma opcao (1-based). Um texto plano, sem side
    effect — quem imprime e o chamador (facilita testar).

    A ordem das linhas e a ordem em que uma decisao se toma: o que fazer,
    por que isto mexe no problema, como voce vai saber que funcionou, o que
    doi. Uma opcao sem `why` e uma promessa vazia, e ela sai mesmo assim —
    omitir e mais honesto do que inventar mecanismo.
    """
    lines = [f"[Opcao {index}/{total}] {option.get('title', '')}"]
    why = str(option.get("why", "")).strip()
    if why:
        lines.append(f"   por que: {why}")
    for step in option.get("steps", []):
        lines.append(f"   - {step}")
    proof = str(option.get("proof", "")).strip()
    if proof:
        lines.append(f"   como saber que funcionou: {proof}")
    risk = str(option.get("risk", "")).strip()
    if risk:
        reversivel = "reversivel" if option.get("reversible", True) else "sem volta"
        lines.append(f"   risco ({reversivel}): {risk}")
    action = option.get("action")
    if action:
        kind = action.get("type", "")
        if kind == "kill_top_process":
            lines.append("   > o Sentinel pode encerrar o processo topo por voce (pede confirmacao).")
        elif kind == "open_settings":
            lines.append(f"   > abre/ajusta: {action.get('target', 'configuracao')}")
    return "\n".join(lines)


def _ask_validate() -> str:
    """Le a validacao do usuario no tty. Traduz variantes pt/en pros tres
    caminhos. Qualquer coisa nao reconhecida = 'next' (falha segura: tenta a
    proxima em vez de marcar resolvida a toa)."""
    from sentinel.system.prompt import is_interactive

    if not is_interactive():
        return RESPONSE_DISMISS

    print(
        "  A solucao funcionou? [s]im  |  [n]ao, proxima  |  [p]ular tudo "
        "(ou Ctrl+C):"
    )
    try:
        answer = input("  > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return RESPONSE_DISMISS

    if answer in ("s", "sim", "y", "yes"):
        return RESPONSE_FIXED
    if answer in ("p", "pular", "skip", "q", "quit"):
        return RESPONSE_DISMISS
    return RESPONSE_NEXT


def _offer_execute(
    option: dict,
    event: dict,
    *,
    ctl: ProcessCtl,
    interactive: bool,
) -> str:
    """OFFER_EXECUTE: se a opcao carrega uma acao matar-processo, oferece
    rodar agora (o kill_tree ainda pede 2a confirmacao la dentro). Devolve
    uma linha de status pro log do ciclo."""
    action = option.get("action") or {}
    if action.get("type") != "kill_top_process":
        return ""

    from sentinel.processctl import is_protected, is_self

    top = event.get("top_processes") or []
    # Escolhe o primeiro alvo REAL e matavel: pula protegidos e o proprio
    # Sentinel. O detector ja exclui o System Idle Process da lista, mas o
    # kill nao pode confiar cegamente no [0] — um svchost topo legitimo nao
    # e pra matar por PID.
    target = None
    for candidate in top:
        name = candidate.get("name", "")
        pid = candidate.get("pid")
        if pid is None:
            continue
        if is_protected(name) or is_self(name):
            continue
        target = candidate
        break

    if target is None:
        return (
            "  (sem alvo matavel: os processos topo sao protegidos ou do "
            "proprio sistema; encerre via Gerenciador de Tarefas)"
        )

    # ProcessCtl so e construido aqui (nao no topo do ciclo): e a unica
    # rota que precisa de psutil, entao um `fix` sobre anomalia sem acao de
    # kill roda mesmo sem psutil instalado.
    ctl = ctl or ProcessCtl()

    pid = int(target["pid"])
    name = target.get("name", "?")

    from sentinel.system.prompt import confirm

    if not confirm(f"Encerrar '{name}' (pid {pid}) agora?", default=False):
        return f"  cancelado; rode depois: sentinel kill {pid}"

    result = ctl.kill_tree(pid, interactive=interactive)
    if result.refused:
        return f"  recusa do Sentinel: {result.refused_reason}"
    if result.ok:
        return f"  encerrado: pid(s) {', '.join(map(str, result.killed))}"
    return f"  parcial: encerrados {result.killed}, falharam {result.failed}"


def run_cycle(
    event: dict,
    store: EventStore,
    *,
    ctl: ProcessCtl | None = None,
    interactive: bool = True,
    overrides: dict | None = None,
    options: list[dict] | None = None,
    source: str | None = None,
    db: kbstore.KbStore | None = None,
    validate=None,
    echo=print,
) -> TutorOutcome:
    """Dirige a maquina de estados do tutorial sobre UMA anomalia.

    PROPOSE -> (RENDER -> [OFFER_EXECUTE] -> AWAIT_VALIDATE) -> ADVANCE |
    RESOLVED | DISMISSED; esgotar opcoes sem sucesso -> EXHAUSTED ->
    DISMISSED.

    Todo ponto de decisao e injetavel (options/source/validate/ctl/echo) pra
    o teste rodar o ciclo inteiro sem motor local, sem tty e sem matar processo
    real. Em sessao nao-interativa so APRESENTA as opcoes e sai (nunca
    bloqueia esperando tecla).

    `db` e a memoria de longo prazo: cada validacao do usuario vira uma
    linha de desfecho ligada aquela opcao e aquele fingerprint. E o que faz
    a proxima rodada daquela anomalia comegar pela opcao que ja funcionou
    aqui — sem depender de voce lembrar qual foi.
    """
    layer = 0
    if options is None or source is None:
        options, source, layer = propose(event, overrides=overrides, db=db)

    if not options:
        # Sem opcao alguma (metrica desconhecida sem template): nada a
        # tutoriar. Marca descartado pra nao ficar 'open' pra sempre.
        return _finalize(event, store, OUTCOME_DISMISSED, None, source, 0, layer=layer)

    total = len(options)

    if not interactive:
        echo("Modo nao-interativo: exibindo opcoes sem ciclo de validacao.")
        for i, opt in enumerate(options, start=1):
            echo(render_option(opt, i, total))
        echo(
            "Rode 'sentinel fix' num terminal interativo para validar cada "
            "solucao."
        )
        return TutorOutcome(outcome="", option_index=None, source=source, tried=0,
                            detail="presented-only", layer=layer)

    validate = validate or _ask_validate
    event_id = event.get("id", "")

    store.set_status(event_id, "addressing") if event_id else None
    if db is not None:
        db.touch_anomaly(event)

    index = 0
    tried = 0
    while index < total:
        option = options[index]
        echo("")
        echo(render_option(option, index + 1, total))
        tried += 1

        note = _offer_execute(option, event, ctl=ctl, interactive=interactive)
        if note:
            echo(note)

        response = validate()
        if response == RESPONSE_FIXED:
            _tally(db, event, option, OUTCOME_FIXED, source)
            return _finalize(
                event, store, OUTCOME_FIXED, index, source, tried,
                layer=layer,
                note="usuario validou solucao",
            )
        if response == RESPONSE_DISMISS:
            _tally(db, event, option, OUTCOME_DISMISSED, source)
            return _finalize(
                event, store, OUTCOME_DISMISSED, index, source, tried,
                layer=layer,
                note="usuario pulou/descartou",
            )
        # RESPONSE_NEXT -> ADVANCE: "nao funcionou" e o dado mais valioso
        # que existe aqui, e ele morre se nao for gravado.
        _tally(db, event, option, OUTCOME_NOT_FIXED, source)
        index += 1

    # EXHAUSTED: nenhuma opcao resolveu.
    echo(
        "Nenhuma das opcoes resolveu. Rode 'sentinel events --json' pra "
        "inspecionar o historico, ou reporte o fingerprint."
    )
    return _finalize(
        event, store, OUTCOME_NOT_FIXED, None, source, tried,
        layer=layer,
        note="todas as opcoes esgotadas sem sucesso",
    )


def _tally(db, event: dict, option: dict, outcome: str, source: str) -> None:
    """Grava o desfecho na base local, se houver base aberta."""
    if db is None:
        return
    db.record(event, option, outcome=outcome, source=source)


def _finalize(
    event: dict,
    store: EventStore,
    outcome: str,
    option_index: int | None,
    source: str,
    tried: int,
    *,
    layer: int = 0,
    note: str = "",
) -> TutorOutcome:
    """Escreve a linha `resolution` ligada ao evento e o status final."""
    event_id = event.get("id", "")
    if event_id:
        status = STATUS_DISMISSED if outcome in (
            OUTCOME_DISMISSED,
            OUTCOME_NOT_FIXED,
        ) else STATUS_RESOLVED
        store.append_resolution(
            ref=event_id,
            outcome=outcome,
            option_index=option_index,
            source=source,
            note=note,
            set_status_to=status,
        )
    return TutorOutcome(
        outcome=outcome,
        option_index=option_index,
        source=source,
        tried=tried,
        detail=note,
        layer=layer,
    )

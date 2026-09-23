from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

from sentinel import __version__, api, daemon, settings
from sentinel.events import EventStore
from sentinel.sensor import Sensor


HELP_EPILOG = r"""
REQUISITOS
    Python 3.10+
    psutil (pip install psutil) — unica dependencia de runtime; le as
    metricas localmente.
    Motor de modelo local OPCIONAL (Ollama, ou qualquer endpoint
    OpenAI-compativel em loopback): so melhora os tutoriais de correcao.
    Sem motor, o Sentinel usa a base curada (.sentinel/kb.db) e diz de onde
    veio. Ele nao instala nem baixa nada — quem prove o motor e voce;
    `sentinel model status` diz o que encontrou.

COMANDOS
    start                Inicia o daemon de vigilancia em background
                         (pidfile em .sentinel/daemon.pid).
    stop                 Encerra o daemon.
    status               Diz se o daemon esta vivo, a ultima amostra, se a
                         vigilancia esta pausada e quantos eventos abertos.
                         --json responde pra maquina, sem medir nada.
    metrics              Leitura unica do painel: amostra medida agora, serie
                         do daemon.log, limiares, processos com as travas
                         marcadas, anomalias, resolucoes, intervencoes e o
                         fim do log. --json e o que a GUI lee.
    pause / resume       Kill-switch sem GUI: para/retoma o registro de
                         anomalias gravando/apagando .sentinel/paused. Vale
                         mesmo com o daemon morto (sobrevive a reboot).
    watch                Roda o loop de vigilancia em PRIMEIRO PLANO
                         (Ctrl+C para). Util pra debug; --once = 1 tick.
    events               Lista anomalias registradas. --open-only,
                         --limit N, --json.
    fix [ID]             Ciclo de tutoria sobre uma anomalia (padrao: a
                         mais recente aberta). Gera ate 3 solucoes, vo
                         valida cada uma; se nao resolveu, passa pra
                         proxima. --explain-source mostra a camada da base
                         que respondeu.
                         Em modo maquina: --plan --json devolve as opcoes
                         (com a 'key' de cada uma) sem dialogo, e --resolve
                         <fixed|not_fixed|dismissed> --option N --key K --json
                         grava a decisao que voce tomou na interface.
    kb                   Inventario da base local: tipos conhecidos, opcoes,
                         o que foi aprendido do modelo e os desfechos que
                         voce registrou. --json.
    model status         Sonda o motor local: esta vivo? fala que dialeto?
                         anuncia o modelo pedido? So leitura — nao instala,
                         nao baixa. --json.
    kill <PID>           Encerra um processo problema com protecao de
                         lista do sistema + confirmacao. --tree inclui
                         descendentes. --yes diz que a confirmacao ja
                         aconteceu (foi a GUI, nao o terminal); sem ela numa
                         sessao sem tty o kill recusa do mesmo jeito.
    orders               O que o Sentinel pode fazer sem pedir, e o modo
                         sombra: `orders shadow --on|--off` decide se o
                         degrau 1 age ou so grava o que faria.
    relief <PID>         Rebaixa (ou devolve, com --restore) a prioridade de
                         um processo, agora, porque VOCE pediu — sem as
                         guardas de autonomia. Use numa janela elevada para
                         um processo que o daemon nao alcanca.
    prune                Apaga eventos antigos (--older-than DIAS).
    config               Mostra limiares ativos e caminhos (--show-source).

PRIVACIDADE
    100% local, menos telemetria. A unica saida de rede e a pergunta a um
    motor de IA nesta mesma maquina (loopback), disparada so quando VOCE
    roda 'sentinel fix'; o daemon nunca chama IA. Um endereco que nao seja o
    desta maquina e recusado no codigo, nao na config — sem excecao para IA
    paga.

EXEMPLOS
    python sentinel.py start
    python sentinel.py status
    python sentinel.py events --open-only
    python sentinel.py fix
    python sentinel.py kill 4321 --tree
    python sentinel.py --help
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sentinel.py",
        description=(
            "Satelite de monitoramento e autocorrecao guiada do "
            "Theroverse: vigia CPU/RAM/disco/rede, detecta picos e "
            "monta mini tutoriais de correcao (locais, sem telemetria)."
        ),
        epilog=HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"sentinel {__version__}",
    )
    parser.add_argument(
        "--dir",
        default=".",
        metavar="PASTA",
        help=(
            "Raiz onde o Sentinel cria/le a pasta .sentinel/ (eventos, "
            "pidfile, log). Padrao: pasta atual."
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="So imprime o essencial (usado por scripts/agente).",
    )

    sub = parser.add_subparsers(dest="command")

    metrics = sub.add_parser(
        "metrics",
        help="Leitura única do painel (amostra, série, processos, eventos) em JSON.",
    )
    metrics.add_argument(
        "--json", action="store_true", help="Resposta de máquina (o que a GUI lê)."
    )
    metrics.add_argument(
        "--history",
        type=int,
        default=60,
        metavar="N",
        help="Batimentos do daemon.log que viram série de gráfico.",
    )
    metrics.add_argument(
        "--limit", type=int, default=60, metavar="N", help="Máximo de anomalias."
    )
    metrics.add_argument(
        "--log", type=int, default=60, metavar="N", help="Linhas do fim do log."
    )

    start_p = sub.add_parser("start", help="Inicia o daemon em background.")
    start_p.add_argument("--json", action="store_true", help="Resposta de máquina.")
    stop_p = sub.add_parser("stop", help="Encerra o daemon.")
    stop_p.add_argument("--json", action="store_true", help="Resposta de máquina.")

    status_p = sub.add_parser("status", help="Estado do daemon + resumo.")
    status_p.add_argument("--json", action="store_true", help="Resposta de máquina.")

    pause_p = sub.add_parser(
        "pause",
        help="Pausa o registro de anomalias (kill-switch em .sentinel/paused).",
    )
    pause_p.add_argument("--json", action="store_true", help="Resposta de máquina.")
    resume_p = sub.add_parser("resume", help="Retoma o que o 'pause' pausou.")
    resume_p.add_argument("--json", action="store_true", help="Resposta de máquina.")

    watch_p = sub.add_parser("watch", help="Roda a vigilancia em 1o plano.")
    watch_p.add_argument(
        "--once",
        action="store_true",
        help="Faz um unico tick e sai (debug/monitor pontual).",
    )

    events_p = sub.add_parser("events", help="Lista anomalias.")
    events_p.add_argument(
        "--open-only", action="store_true", help="So as ainda abertas."
    )
    events_p.add_argument(
        "--limit", type=int, default=20, metavar="N", help="Maximo de linhas."
    )
    events_p.add_argument(
        "--json", action="store_true", help="Saida JSON crua (uma linha por evento)."
    )
    events_p.add_argument(
        "--interventions",
        action="store_true",
        help="Em vez das anomalias, o que o Sentinel fez por conta propria "
        "(o historico do degrau 1: aplicado, recusado ou so sombra).",
    )

    fix_p = sub.add_parser("fix", help="Tutorial de correcao guiado.")
    fix_p.add_argument(
        "event_id", nargs="?", default=None, help="ID da anomalia (opcional)."
    )
    fix_p.add_argument(
        "--explain-source",
        action="store_true",
        help="Antes do tutorial, diz de qual camada da base veio a sugestao "
        "e o que pesou no ranking.",
    )
    fix_p.add_argument(
        "--plan",
        action="store_true",
        help="So as opcoes, sem ciclo de validacao (modo maquina: --json).",
    )
    fix_p.add_argument(
        "--resolve",
        choices=("fixed", "not_fixed", "dismissed"),
        default=None,
        metavar="DESFEOCHO",
        help="Grava a sua decisao sobre a anomalia: fixed, not_fixed ou "
        "dismissed. com --option e um passo do ciclo; sem ele, a fila acabou.",
    )
    fix_p.add_argument(
        "--option",
        type=int,
        default=None,
        metavar="N",
        help="Qual opcao do plano foi validada (1 = a primeira).",
    )
    fix_p.add_argument(
        "--key",
        default="",
        metavar="CHAVE",
        help="key da opcao (vem do --plan); e o que liga o desfecho a base local.",
    )
    fix_p.add_argument(
        "--source",
        default="",
        metavar="FONTE",
        help="De onde veio a opcao (campo 'fonte' do --plan).",
    )
    fix_p.add_argument("--note", default="", help="Nota opcional na linha de resolucao.")
    fix_p.add_argument("--json", action="store_true", help="Resposta de maquina.")

    kb_p = sub.add_parser(
        "kb", help="O que a base local (.sentinel/kb.db) ja sabe desta maquina."
    )
    kb_p.add_argument(
        "--json", action="store_true", help="Saida em JSON (pra GUI e agentes)."
    )

    model_p = sub.add_parser(
        "model",
        help="Motor de modelo local (Ollama / endpoint OpenAI em loopback).",
    )
    model_sub = model_p.add_subparsers(dest="model_command")
    model_status_p = model_sub.add_parser(
        "status",
        help="Sonda o motor: vivo? dialecto? modelo anunciado? (nao instala nada)",
    )
    model_status_p.add_argument(
        "--json", action="store_true", help="Saida em JSON (pra GUI e agentes)."
    )

    kill_p = sub.add_parser("kill", help="Encerra um processo problema.")
    kill_p.add_argument("pid", type=int, help="PID do processo alvo.")
    kill_p.add_argument(
        "--tree",
        action="store_true",
        help="Inclui processos descendentes na arvore a encerrar.",
    )
    kill_p.add_argument(
        "--yes",
        action="store_true",
        help="A confirmacao ja aconteceu do lado de quem pediu (a GUI pergunta "
        "antes de chamar). Sem --yes numa sessao sem tty o kill recusa, igual.",
    )
    kill_p.add_argument("--json", action="store_true", help="Resposta de maquina.")

    relief_p = sub.add_parser(
        "relief",
        help="Rebaixar/devolver a prioridade de um processo, por pedido explicito.",
    )
    relief_p.add_argument("pid", type=int, help="PID do processo alvo.")
    relief_p.add_argument(
        "--restore",
        action="store_true",
        help="Devolve o valor que o processo tinha antes da ultima intervencao "
        "do Sentinel, em vez de rebaixar.",
    )

    orders_p = sub.add_parser(
        "orders",
        help="O que o Sentinel faz sem pedir (degraus ligados, guardas, modo sombra).",
    )
    orders_sub = orders_p.add_subparsers(dest="orders_command")
    shadow_p = orders_sub.add_parser(
        "shadow", help="Modo sombra: decide e grava, sem tocar em processo nenhum."
    )
    shadow_g = shadow_p.add_mutually_exclusive_group()
    shadow_g.add_argument(
        "--on", action="store_true", dest="on", help="Liga o modo sombra."
    )
    shadow_g.add_argument(
        "--off", action="store_true", dest="off", help="Desliga (o padrao: age)."
    )

    prune_p = sub.add_parser("prune", help="Apaga eventos antigos.")
    prune_p.add_argument(
        "--older-than", type=int, default=30, metavar="DIAS", dest="days"
    )

    config_p = sub.add_parser("config", help="Mostra limiares e caminhos.")
    config_p.add_argument(
        "--show-source",
        action="store_true",
        help="Marca cada limiar como padrao ou sobrescrito (por config.json).",
    )

    # Subcomando oculto: o processo filho do daemon. Nao aparece no help.
    daemon_run = sub.add_parser("__daemon-run")
    daemon_run.add_argument("--dir", default=".")

    return parser


def _store(paths: settings.Paths) -> EventStore:
    return EventStore(paths.events)


def _machine(args: argparse.Namespace) -> bool:
    """O pedido veio de uma maquina (`--json`)?"""
    return bool(getattr(args, "json", False))


def _answered(args: argparse.Namespace, build, human) -> int:
    """A mesma resposta, dois publicos.

    Com `--json` o texto formatado nao existe: quem chama quer o dado, e uma
    resposta que so sai bonita no terminal obrigaria a GUI a fazer parse de
    prosa. No caminho do JSON o stdout e sagrado (so o payload sai nele),
    entao qualquer sussurro do motor — como o aviso do `local_model` de que
    nao ha motor na maquina — e trancado no stderr durante a construcao.
    """
    if not _machine(args):
        human()
        return 0
    with contextlib.redirect_stdout(sys.stderr):
        payload = build()
    print(api.dump(payload))
    return 1 if isinstance(payload, dict) and payload.get("ok") is False else 0


def cmd_start(paths: settings.Paths, args: argparse.Namespace) -> int:
    def build():
        try:
            pid = daemon.start(paths)
        except daemon.AlreadyRunning as exc:
            return {"ok": True, "started": False, "pid": None, "warning": str(exc)}
        return {"ok": True, "started": True, "pid": pid, "log": str(paths.daemon_log)}

    def human():
        try:
            pid = daemon.start(paths)
        except daemon.AlreadyRunning as exc:
            print(f"[WARN] {exc}")
            return
        print(f"Daemon iniciado (pid {pid}). Logs em {paths.daemon_log}")

    return _answered(args, build, human)


def cmd_stop(paths: settings.Paths, args: argparse.Namespace) -> int:
    def build():
        try:
            pid = daemon.stop(paths)
        except daemon.NotRunning:
            _clear_stale_pidfile(paths)
            return {"ok": True, "stopped": False, "pid": None}
        return {"ok": True, "stopped": True, "pid": pid}

    def human():
        try:
            pid = daemon.stop(paths)
        except daemon.NotRunning:
            _clear_stale_pidfile(paths)
            print("Daemon nao estava rodando.")
            return
        print(f"Daemon encerrado (pid {pid}).")

    return _answered(args, build, human)


def _clear_stale_pidfile(paths: settings.Paths) -> None:
    """pidfile obsoleto: limpa pra proximo start nao esbarrar."""
    try:
        paths.pid.unlink()
    except OSError:
        pass


def cmd_status(paths: settings.Paths, args: argparse.Namespace) -> int:
    st = daemon.status(paths)
    opens = _store(paths).open_anomalies()

    def human():
        if st.running:
            print(f"Daemon: VIVO (pid {st.pid})")
            if st.last_heartbeat:
                print(f"Ultimo batimento: {st.last_heartbeat.isoformat()}")
        else:
            if st.pid:
                print(
                    f"Daemon: MORTO (pidfile obsoleto: {st.pid}; rode 'stop' p/ limpar)"
                )
            else:
                print("Daemon: parado")

        _print_pause_state(paths, st.paused)
        _print_shadow_state(paths)

        print(f"Eventos abertos: {len(opens)}")
        for finding in opens[-5:]:
            print(f"  - {_event_line(finding)}")

    return _answered(args, lambda: api.status(paths), human)


def cmd_metrics(paths: settings.Paths, args: argparse.Namespace) -> int:
    """A resposta única do painel: a GUI inteira cabe numa chamada.

    Cinco chamadas de processo filho a cada atualizacao custariam mais que o
    monitoramento que elas mostram, e ainda entregariam cinco instantes
    diferentes na mesma tela.
    """

    def build():
        return api.dashboard(
            paths,
            events_limit=args.limit,
            log_lines_limit=args.log,
            history=args.history,
        )

    def human():
        sample = api.live_sample()
        print(f"Amostra {sample['ts']}")
        print(f"  cpu {sample['cpu_percent']}%   ram {sample['ram_percent']}%")
        print(
            f"  disco {sample['disk_percent']}% ({sample['disk_path']})   "
            f"io {sample['io_busy_percent']}%"
        )
        print(
            f"  rede {sample['net_recv_bps']:.0f} down / "
            f"{sample['net_sent_bps']:.0f} up bps"
        )
        print("  topo:")
        for proc in sample["top_cpu"]:
            print(
                f"    {proc['pid']:<8} {proc['name']:<28} "
                f"cpu {proc['cpu']:.1f}%  rss {proc['rss_mb']:.0f} MB"
            )
        print("\nUse --json pra resposta de maquina (painel completo).")

    try:
        Sensor()
    except Exception as exc:  # sem psutil nao ha o que medir — e dito, nao fingido
        if _machine(args):
            print(api.dump({"ok": False, "error": f"sem sensor: {exc}"}))
        else:
            print(f"[ERRO] metricas indisponiveis: {exc}", file=sys.stderr)
        return 1
    return _answered(args, build, human)


def _print_pause_state(paths: settings.Paths, paused: bool) -> None:
    if not paused:
        print("Vigilancia automatica: ATIVA")
        return
    since = daemon.paused_since(paths)
    note = f" desde {since.isoformat()}" if since else ""
    print(
        f"Vigilancia automatica: PAUSADA{note} — nada novo e registrado; "
        "retome com 'sentinel resume'"
    )


def _print_shadow_state(paths: settings.Paths) -> None:
    """So quando esta ligado: DESLIGADO e o estado padrao, e uma linha por
    nada mudado seria o log dizendo 'mudei o comportamento' sem mudança."""
    from sentinel import orders as orders_mod

    if not orders_mod.load(paths).shadow:
        return
    decided = len(_store(paths).interventions())
    note = f" ({decided} decisoes no historico)" if decided else ""
    print(
        "Acoes automaticas: MODO SOMBRA — o Sentinel decide e grava o que "
        "faria, sem tocar em processo nenhum" + note
    )


def cmd_pause(paths: settings.Paths, args: argparse.Namespace) -> int:
    daemon.pause(paths)
    st = daemon.status(paths)

    def human():
        if st.running:
            print(
                f"Vigilancia pausada (daemon pid {st.pid} segue amostrando; para de "
                "registrar anomalia no proximo batimento)."
            )
        else:
            print(
                "Vigilancia pausada. O daemon nao esta rodando agora — quando "
                "subir, ja sobe pausado (e assim que sobrevive a reboot)."
            )
        print(f"Arquivo: {paths.paused}")

    return _answered(
        args,
        lambda: {"ok": True, "paused": True, "file": str(paths.paused)},
        human,
    )


def cmd_resume(paths: settings.Paths, args: argparse.Namespace) -> int:
    resumed = daemon.resume(paths)
    st = daemon.status(paths)

    def human():
        if not resumed:
            print("Nada estava pausado.")
            return
        state = (
            f"no proximo batimento (pid {st.pid})"
            if st.running
            else "quando o daemon subir"
        )
        print(f"Vigilancia retomada {state}.")

    return _answered(
        args,
        lambda: {
            "ok": True,
            "paused": False,
            "was_paused": resumed,
            "running": st.running,
        },
        human,
    )


def cmd_watch(paths: settings.Paths, args: argparse.Namespace) -> int:
    sensor = Sensor()
    stop_after = 1 if args.once else None
    # `--once` e diagnostico, e um tick avulso nao pode sair rebaixando apps
    # enquanto o daemon faz o mesmo: com um tick so, o degrau fica desligado
    # e dito — vigia quem quiser, age quem fica.
    relief = None if args.once else daemon.build_relief_agent(paths)
    ticks = daemon.run_watch_loop(
        paths,
        sensor=sensor,
        store=_store(paths),
        incident_sources=daemon.build_incident_sources(),
        relief=relief,
        stop_after=stop_after,
    )
    if not args.quiet:
        print(f"watch encerrado apos {ticks} tick(s). Eventos em {paths.events}")
    return 0


def _event_line(event: dict) -> str:
    """Uma linha de anomalia no terminal.

    Dois formatos, porque duas naturezas: a finding de limiar tem numero e
    teto (`value=`/`thr=`); o incidente (arvore órfã, queda de app) não tem
    valor nenhum — o que se mostra é o `label` que o motor escreveu.
    """
    ts = str(event.get("ts", ""))[:19]
    metric = str(event.get("metric", "?"))
    severity = str(event.get("severity", "?"))
    status = str(event.get("status", "open"))
    occ = event.get("occurrences", 1)
    occ_note = f" x{occ}" if occ and occ > 1 else ""
    head = f"{ts}  {metric:<12} {severity:<8} {status:<10}"

    if event.get("label"):
        return f"{head}{event['label']}{occ_note}  id={event.get('id')}"

    procs = event.get("top_processes") or []
    top = procs[0]["name"] if procs and "name" in procs[0] else "-"
    return (
        f"{head}value={event.get('value')} thr={event.get('threshold')} "
        f"top={top}{occ_note}  id={event.get('id')}"
    )


def cmd_events(paths: settings.Paths, args: argparse.Namespace) -> int:
    store = _store(paths)
    if args.interventions:
        rows = store.interventions()
        events = rows[-args.limit :] if args.limit else rows
        if args.json:
            for event in events:
                print(json.dumps(event, ensure_ascii=False))
            return 0
        if not events:
            print("Nenhuma intervencao registrada.")
            return 0
        for event in events:
            print(_intervention_line(event))
        return 0

    events = store.anomalies()
    if args.open_only:
        events = [e for e in events if e.get("status", "open") == "open"]
    events = events[-args.limit :] if args.limit else events

    if args.json:
        for event in events:
            print(json.dumps(event, ensure_ascii=False))
        return 0

    if not events:
        print("Nenhum evento." if not args.open_only else "Nenhuma anomalia aberta.")
        return 0

    for event in events:
        print(_event_line(event))
    return 0


def _intervention_line(event: dict) -> str:
    """Uma linha do que o Sentinel fez, nao do que ele viu.

    Sem `severity` nem `status`, porque nao e anomalia: o que importa aqui e
    quem recebeu a intervencao, se ela foi aplicada, e o motivo quando nao
    foi.
    """
    ts = str(event.get("ts", ""))[:19]
    detail = event.get("detail") or {}
    mark = " [sombra]" if detail.get("shadow") else ""
    metric = str(event.get("metric", "?"))
    return f"{ts}  {metric:<24} {event.get('label', '')}{mark}  id={event.get('id')}"


def _kbstore(paths: settings.Paths):
    """Abre a base de conhecimento local (`.sentinel/kb.db`), ou None.

    A base e memoria, nao requisito: se o arquivo nao abrir (disco cheio,
    db corrompido, `.sentinel/` em pasta somente leitura), o `fix` segue
    exatamente como antes, com `kb.py` em memoria e o modelo respondendo. O
    Sentinel nunca para de ajudar por causa do proprio cache.
    """
    from sentinel import kbstore

    try:
        paths.ensure_output_dir()
        return kbstore.open_store(paths.kb_db)
    except OSError:
        return None


def _explain_source(db, event: dict) -> None:
    """Camada que respondeu, causa reconhecida e o que pesou no ranking."""
    from sentinel import kbstore

    info = db.explain(event)
    print(f"Fonte da sugestao: {info['camada']}")
    print(f"  causa reconhecida: {info['causa'] or '(nenhuma)'}")
    print(f"  fingerprint:       {info['fingerprint']}")
    print(f"  opcoes na base:    {info['respostas']}")
    ranked = [
        (key, tally["fixed"], tally["not_fixed"], tally["origem"])
        for key, tally in info["ranked_by"].items()
    ]
    tried = [row for row in ranked if row[1] or row[2]]
    if tried:
        print("  o que pesou no ranking (deste fingerprint):")
        for key, fixed, not_fixed, origin in tried:
            print(f"    {key}: {fixed} x resolveu, {not_fixed} x nao — {origin}")
    else:
        print("  ninguém tentou nada aqui ainda; a ordem é a do catálogo curado.")
    learned = db.stats()["aprendidas"]
    if learned:
        print(f"  opcoes aprendidas de modelo nesta maquina: {learned}")
    print()


def _fix_target(store: EventStore, event_id: str | None):
    """A anomalia do pedido, ou None. Sem id, a mais recente aberta — a mesma
    regra do ciclo de terminal, pra GUI e mao pedirem a mesma coisa."""
    if event_id:
        event = store.find(event_id)
        return event if event and event.get("kind") == "anomaly" else None
    return store.latest_open()


def _fix_missing(args: argparse.Namespace, *, event_id: str | None) -> int:
    """Sem alvo, dois casos que nao se confundem: um id errado e uma historia
    sem anomalia aberta. O primeiro e erro de quem pediu; o segundo e o
    estado mais saudavel que existe."""
    if event_id:
        message = f"anomalia nao encontrada: {event_id}"
        if _machine(args):
            print(api.dump({"ok": False, "error": message}))
        else:
            print(f"[ERROR] {message}")
        return 1
    if _machine(args):
        print(
            api.dump(
                {
                    "ok": True,
                    "event_id": None,
                    "options": [],
                    "fonte": "",
                    "camada": 0,
                    "motivo": "nenhuma anomalia aberta",
                }
            )
        )
    else:
        print("Nenhuma anomalia aberta pra corrigir. Rode 'sentinel status'.")
    return 0


def _print_plan(payload: dict) -> None:
    from sentinel.tutor import render_option

    options = payload.get("options") or []
    total = len(options)
    if not total:
        print("A base local nao tem opcao para esta anomalia.")
        return
    for i, option in enumerate(options, start=1):
        print(render_option(option, i, total))
        print()
    print(f"Fonte: {payload.get('fonte', '')} (camada {payload.get('camada', 0)})")


def cmd_fix(paths: settings.Paths, args: argparse.Namespace) -> int:
    from sentinel.system.prompt import is_interactive
    from sentinel.tutor import run_cycle

    store = _store(paths)

    if args.plan:
        event = _fix_target(store, args.event_id)
        if event is None:
            return _fix_missing(args, event_id=args.event_id)
        with contextlib.redirect_stdout(sys.stderr):
            payload = api.plan(paths, event)
        if _machine(args):
            payload["ok"] = True
            print(api.dump(payload))
        else:
            _print_plan(payload)
        return 0

    if args.resolve:
        event = _fix_target(store, args.event_id)
        if event is None:
            return _fix_missing(args, event_id=args.event_id)
        index = None if args.option is None else max(0, args.option - 1)
        return _answered(
            args,
            lambda: api.resolve(
                paths,
                event,
                outcome=args.resolve,
                option_index=index,
                key=args.key,
                source=args.source,
                note=args.note,
            ),
            lambda: print(
                f"Resolucao gravada em {event.get('id')}: {args.resolve}"
                + (f" (opcao {args.option})" if args.option else "")
            ),
        )

    if _machine(args):
        # Sem --plan nem --resolve o `fix` e um dialogo, e dialogo nao tem
        # resposta de maquina: melhor dizer isto do que imprimir prosa no
        # stdout de quem espera JSON.
        print(
            api.dump(
                {
                    "ok": False,
                    "error": "fix em modo maquina exige --plan ou --resolve "
                    "<desfecho>; sem flag ele e o ciclo de validacao no terminal",
                }
            )
        )
        return 1

    overrides = settings.load_overrides(paths)
    db = _kbstore(paths)

    event = _fix_target(store, args.event_id)
    if event is None:
        return _fix_missing(args, event_id=args.event_id)

    headline = event.get("label") or (
        f"{event.get('metric')}/{event.get('severity')} "
        f"(valor {event.get('value')}, limiar {event.get('threshold')})"
    )
    print(f"Anomalia {event.get('id')} — {headline}")
    if args.explain_source and db is not None:
        _explain_source(db, event)
    try:
        outcome = run_cycle(
            event,
            store,
            interactive=is_interactive(),
            overrides=overrides,
            db=db,
        )
    finally:
        if db is not None:
            db.close()
    if outcome.outcome:
        print(
            f"\nResolvido: outcome={outcome.outcome} "
            f"source={outcome.source} tentativas={outcome.tried}"
        )
    return 0


def cmd_kb(paths: settings.Paths, args: argparse.Namespace) -> int:
    """Inventario da base local: o que ja foi aprendido, testado, e quanto
    de cada anomalia a camada 4 ainda precisa responder.

    Sao os numeros da meta declarada no design: com uso, o modelo quase nunca
    roda. Sem eles, 'a base aprende' seria uma frase de marketing.
    """
    db = _kbstore(paths)
    if db is None:
        print("[ERRO] base indisponivel: .sentinel/kb.db nao abriu.")
        return 1
    try:
        stats = db.stats()
    finally:
        db.close()
    if args.json:
        print(json.dumps(stats, ensure_ascii=False))
        return 0
    print(f"Base de conhecimento: {paths.kb_db}")
    print(f"  anomalias conhecidas: {stats['tipos']}")
    print(f"  opcoes na base:       {stats['opcoes']}")
    print(f"    - aprendidas:       {stats['aprendidas']}")
    print(f"  desfechos registrados: {stats['desfechos']}")
    for outcome, total in sorted(stats["por_desfecho"].items()):
        print(f"    {outcome}: {total}")
    return 0


def cmd_model(paths: settings.Paths, args: argparse.Namespace) -> int:
    """`sentinel model status`: o que ha do outro lado do endereco do motor.

    So sonda. Este projeto nao instala runtime, nao baixa modelo e nao abre
    excecao pra IA paga — entao o maximo que o comando pode fazer e dizer o
    que encontrou, e o que o Sentinel faz sem motor (que e: nada muda, a base
    curada responde).
    """
    if args.model_command != "status":
        print("Uso: sentinel model status [--json]")
        return 1

    from sentinel import local_model

    report = local_model.probe(overrides=settings.load_overrides(paths))
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
        return 0

    print(f"Motor local: {report['base']}")
    print(f"Modelo pedido: {report['model']}")
    if report["transport"] is None:
        print(f"  estado: indisponivel — {report['reason']}")
    else:
        version = f" (versao {report['version']})" if report["version"] else ""
        print(f"  estado: vivo, dialeto {report['transport']}{version}")
        present = {True: "anunciado", False: "NAO anunciado", None: "sem como confirmar"}
        print(f"  modelo: {present[report['model_present']]}"
              + (f" — {report['reason']}" if report["reason"] else ""))
    if report["usable"]:
        print("  efeito: `sentinel fix` pode chamar o motor (camada 4 da base).")
    else:
        print("  efeito: os tutoriais saem da base curada (.sentinel/kb.db).")
        print("  Isso e estado normal, nao erro: o Sentinel nao instala nem baixa nada.")
    return 0


def cmd_kill(paths: settings.Paths, args: argparse.Namespace) -> int:
    from sentinel.processctl import ProcessCtl
    from sentinel.system.prompt import is_interactive

    ctl = ProcessCtl()
    # `--yes` nao fura guarda nenhuma: quem decide se o alvo pode morrer e a
    # lista de protecao do Python, e ela vale com e sem confirmacao. O que o
    # --yes substitui e a tecla — a interface ja perguntou antes de chamar.
    interactive = is_interactive() or args.yes
    result = ctl.kill_tree(
        args.pid, interactive=interactive, include_children=args.tree
    )

    def build():
        return {
            "ok": result.ok,
            "pid": args.pid,
            "killed": result.killed,
            "failed": result.failed,
            "refused": result.refused_reason,
            "tree": bool(args.tree),
        }

    def human():
        if result.refused:
            print(f"[RECUSADO] {result.refused_reason}")
        elif result.ok:
            print(f"Encerrado: pid(s) {', '.join(map(str, result.killed))}")
        else:
            print(f"[PARCIAL] encerrados {result.killed}; falharam {result.failed}")

    rc = _answered(args, build, human)
    return rc if result.ok else 1


def cmd_relief(paths: settings.Paths, args: argparse.Namespace) -> int:
    """O degrau 1 na mao de alguem, e a saida prevista pro processo que o
    daemon nao alcanca porque pertence a outra sessao (spec 5).

    Sem as guardas de autonomia — teto por hora e cooldown existem pra conter
    uma decisao que ninguem revisa, e aqui a revisao foi digitar o comando.
    """
    from sentinel import relief as relief_mod

    agent = daemon.build_relief_agent(paths)
    if agent is None:
        print(
            "[SEM ALAVANCA] sem psutil nao ha como mexer na prioridade de nada. "
            "Instale-o (pip install psutil) e rode de novo."
        )
        return 1

    store = _store(paths)
    if args.restore:
        result = agent.restore_manual(args.pid, _previous_priority(store, args.pid))
    else:
        result = agent.apply_manual(args.pid)

    event = store.record_intervention(result)
    if result.applied:
        if args.restore:
            print(
                f"[DEVOLVIDO] {result.name} (pid {result.pid}): "
                f"prioridade {result.from_level} -> {result.to_level}"
            )
        else:
            print(
                f"[REBAIXADO] {result.name} (pid {result.pid}): "
                f"{result.from_level} -> {result.to_level}"
            )
            print(
                f"            Devolver: python sentinel.py relief "
                f"{result.pid} --restore"
            )
        print(f"            Registrado como id={event.get('id')} em {paths.events}")
        return 0

    return _relief_refusal(result, args)


def _previous_priority(store: EventStore, pid: int):
    """O valor que o processo tinha antes da ultima intervencao APLICADA do
    Sentinel nele.

    Le do `events.jsonl`, nao do journal do daemon: os dois processos
    escrevendo o mesmo journal fariam um dos dois perder historico, e o
    evento ja carrega o numero cru (`detail.priority.from_raw`) pra isso.
    """
    from sentinel.relief import ACTION_LOWER

    for event in reversed(store.interventions()):
        detail = event.get("detail") or {}
        target = detail.get("target") or {}
        if target.get("pid") != pid:
            continue
        if detail.get("action") != ACTION_LOWER or not event.get("applied"):
            continue
        return (detail.get("priority") or {}).get("from_raw")
    return None


def _relief_refusal(result, args: argparse.Namespace) -> int:
    """Por que nao, dito com a palavra que decide o proximo passo.

    O caso que importa e o `sem-alcance`: a interface declara o limite em vez
    de fingir que tentou, e oferece o caminho (janela elevada). Sem prompt,
    sem fallback silencioso.
    """
    from sentinel import relief as relief_mod

    reason = result.reason
    if reason == relief_mod.SKIP_DENIED:
        print(
            f"[NAO ALCANCADO] o pid {args.pid} pertence a outra sessao (elevada "
            "ou de outro usuario); o Sentinel nao o alcanca sem admin."
        )
        print(
            "                Rode o MESMO comando numa janela elevada — e o "
            "caminho previsto, nao uma gambiarra."
        )
    elif reason == relief_mod.SKIP_PROTECTED:
        print(
            f"[RECUSADO] {result.name} esta na lista do sistema: o Sentinel nao "
            "mexe em servico do Windows nem em si mesmo, nem por pedido."
        )
    elif reason == relief_mod.SKIP_GONE:
        print(f"[NAO ENCONTRADO] nao ha processo vivo com o pid {args.pid}.")
    elif reason == relief_mod.SKIP_NO_PREVIOUS:
        print(
            f"[SEM VALOR ANTERIOR] o historico nao registra intervencao do "
            f"Sentinel no pid {args.pid}, entao nao ha para onde devolver."
        )
        print(
            "                     Chutar 'normal' poderia SUBIR a prioridade de "
            "algo que ja estava rebaixado; escolha voce, no Gerenciador de Tarefas."
        )
    elif reason == relief_mod.SKIP_NO_ACTUATOR:
        print("[SEM ALAVANCA] o psutil sumiu do caminho no meio da execucao.")
    elif reason == relief_mod.NOTHING:
        print(
            f"[JA ESTAVA ASSIM] {result.name} (pid {result.pid}) ja estava em "
            f"{result.to_level}."
        )
        return 0
    else:
        print(f"[{reason}] {result.label()}")
    return 1


def cmd_orders(paths: settings.Paths, args: argparse.Namespace) -> int:
    from sentinel import orders as orders_mod

    if getattr(args, "orders_command", None) == "shadow" and (args.on or args.off):
        orders_mod.save(paths, orders_mod.Orders(shadow=args.on))
        if args.on:
            print("Modo sombra: LIGADO.")
            print(
                "  O Sentinel segue decidindo e gravando cada decisao como"
                " `SERIA ...` (`shadow: true`, `applied: false`), sem tocar em"
                " processo nenhum."
            )
            print(
                "  O que ja foi rebaixado continua sendo devolvido no fim do "
                "episodio: sombra segura o proximo passo, nao desfaz o ultimo."
            )
        else:
            print("Modo sombra: DESLIGADO — o degrau 1 volta a agir no proximo ciclo.")
        print(f"Arquivo: {paths.orders}")
        return 0

    _print_orders(paths)
    return 0


def _print_orders(paths: settings.Paths) -> None:
    from sentinel import orders as orders_mod

    state = orders_mod.load(paths)
    overrides = settings.load_overrides(paths)
    hour = settings.threshold(
        "RELIEF_HOUR_LIMIT", overrides, float(settings.RELIEF_HOUR_LIMIT)
    )
    cooldown = settings.threshold(
        "RELIEF_APP_COOLDOWN_S", overrides, float(settings.RELIEF_APP_COOLDOWN_S)
    )
    shadow = (
        "LIGADO — decide e grava, nao toca em nada"
        if state.shadow
        else "DESLIGADO — o degrau 1 age"
    )
    print("O que o Sentinel faz sem pedir:")
    print("  degrau 1  rebaixar prioridade em estagnacao .. LIGADO (desde o inicio)")
    print("  degrau 2  teto de CPU por job ................ exige ordem por app (fase E)")
    print("  degrau 3  encerrar arvore .................... exige ordem por app (fase E)")
    print("  teto de RAM ................................. nunca automatico; so no tutorial")
    print(f"  modo sombra ................................ {shadow}")
    print(
        f"  guardas ...................................... {hour:.0f} intervencoes/hora, "
        f"cooldown de {cooldown:.0f} s por app"
    )
    print("  elevacao .................................... nenhuma, em nenhum caminho")
    print(f"\nArquivo: {paths.orders}")
    print("Mudar o modo sombra: python sentinel.py orders shadow --on|--off")


def cmd_prune(paths: settings.Paths, args: argparse.Namespace) -> int:
    store = _store(paths)
    dropped = store.prune(older_than_days=args.days)
    print(f"Removidos {dropped} evento(s) mais antigos que {args.days} dia(s).")
    return 0


def cmd_config(paths: settings.Paths, args: argparse.Namespace) -> int:
    overrides = settings.load_overrides(paths)
    print(f"Territorio: {paths.output_dir}")
    print(f"Eventos:    {paths.events}")
    print(f"Pidfile:    {paths.pid}")
    print(f"Log daemon: {paths.daemon_log}")
    print("\nLimiares:")
    keys = [
        "CPU_WARNING", "CPU_CRITICAL", "CPU_SUSTAINED",
        "RAM_WARNING", "RAM_CRITICAL", "RAM_SUSTAINED",
        "DISK_WARNING", "DISK_CRITICAL",
        "IO_WARNING", "IO_CRITICAL", "IO_SUSTAINED",
        "NET_WARNING_RATIO", "NET_SUSTAINED",
    ]
    for key in keys:
        default = getattr(settings, key)
        if args.show_source:
            mark = "sobrescrito" if key in overrides else "padrao"
            value = settings.threshold(key, overrides, default)
            print(f"  {key:<18} = {value}  [{mark}]")
        else:
            print(f"  {key:<18} = {settings.threshold(key, overrides, default)}")
    return 0


def cmd_daemon_run(paths: settings.Paths, args: argparse.Namespace) -> int:
    """Corpo do processo filho do daemon: grava o proprio pid (ja gravado
    pelo pai, mas reafirma) e roda o loop ate SIGTERM/KeyboardInterrupt."""
    try:
        import os

        paths.ensure_output_dir()
        paths.pid.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass
    daemon.run_watch_loop(
        paths,
        sensor=Sensor(),
        store=_store(paths),
        incident_sources=daemon.build_incident_sources(),
        # O daemon e o unico que age: `build_relief_agent` devolve None quando
        # o ambiente nao permite (sem psutil), e ai o Sentinel vira so
        # registro — vigilancia que nao derruba o resto por um degrau ausente.
        relief=daemon.build_relief_agent(paths),
    )
    return 0


_COMMANDS = {
    "start": cmd_start,
    "stop": cmd_stop,
    "status": cmd_status,
    "metrics": cmd_metrics,
    "pause": cmd_pause,
    "resume": cmd_resume,
    "watch": cmd_watch,
    "events": cmd_events,
    "fix": cmd_fix,
    "kb": cmd_kb,
    "model": cmd_model,
    "kill": cmd_kill,
    "relief": cmd_relief,
    "orders": cmd_orders,
    "prune": cmd_prune,
    "config": cmd_config,
    "__daemon-run": cmd_daemon_run,
}


def main(entry_path: Path) -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # __daemon-run tem seu proprio --dir (path do filho); unifica com o
    # global resolvendo o Path adequado.
    root = getattr(args, "dir", None) or "."
    paths = settings.paths_for(root)

    handler = _COMMANDS[args.command]
    try:
        rc = handler(paths, args)
    except KeyboardInterrupt:
        print()
        rc = 130
    sys.exit(rc)

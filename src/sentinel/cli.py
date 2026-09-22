from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sentinel import __version__, daemon, settings
from sentinel.events import EventStore
from sentinel.sensor import Sensor


HELP_EPILOG = r"""
REQUISITOS
    Python 3.10+
    psutil (pip install psutil) — unica dependencia de runtime; le as
    metricas localmente. O Sentinel nao faz rede por conta propria.
    Claude Code ("claude -p") OPCIONAL: so melhora os tutoriais de
    correcao. Sem ele, o Sentinel usa a base offline (kb).

COMANDOS
    start                Inicia o daemon de vigilancia em background
                         (pidfile em .sentinel/daemon.pid).
    stop                 Encerra o daemon.
    status               Diz se o daemon esta vivo, a ultima amostra, se a
                         vigilancia esta pausada e quantos eventos abertos.
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
                         proxima.
    kill <PID>           Encerra um processo problema com protecao de
                         lista do sistema + confirmacao. --tree inclui
                         descendentes.
    prune                Apaga eventos antigos (--older-than DIAS).
    config               Mostra limiares ativos e caminhos (--show-source).

PRIVACIDADE
    100% local. Nada sai da maquina, menos telemetria. A unica saida de
    rede e 'claude -p', disparada so quando VOCE roda 'sentinel fix'; o
    daemon nunca chama IA. Sem Claude, cai na base offline.

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

    sub.add_parser("start", help="Inicia o daemon em background.")
    sub.add_parser("stop", help="Encerra o daemon.")
    sub.add_parser("status", help="Estado do daemon + resumo.")

    sub.add_parser(
        "pause",
        help="Pausa o registro de anomalias (kill-switch em .sentinel/paused).",
    )
    sub.add_parser("resume", help="Retoma o que o 'pause' pausou.")

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

    kb_p = sub.add_parser(
        "kb", help="O que a base local (.sentinel/kb.db) ja sabe desta maquina."
    )
    kb_p.add_argument(
        "--json", action="store_true", help="Saida em JSON (pra GUI e agentes)."
    )

    kill_p = sub.add_parser("kill", help="Encerra um processo problema.")
    kill_p.add_argument("pid", type=int, help="PID do processo alvo.")
    kill_p.add_argument(
        "--tree",
        action="store_true",
        help="Inclui processos descendentes na arvore a encerrar.",
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


def cmd_start(paths: settings.Paths, args: argparse.Namespace) -> int:
    try:
        pid = daemon.start(paths)
    except daemon.AlreadyRunning as exc:
        print(f"[WARN] {exc}")
        return 0
    print(f"Daemon iniciado (pid {pid}). Logs em {paths.daemon_log}")
    return 0


def cmd_stop(paths: settings.Paths, args: argparse.Namespace) -> int:
    try:
        pid = daemon.stop(paths)
    except daemon.NotRunning:
        # pidfile obsoleto: limpa pra proximo start nao esbarrar.
        try:
            paths.pid.unlink()
        except OSError:
            pass
        print("Daemon nao estava rodando.")
        return 0
    print(f"Daemon encerrado (pid {pid}).")
    return 0


def cmd_status(paths: settings.Paths, args: argparse.Namespace) -> int:
    st = daemon.status(paths)
    if st.running:
        print(f"Daemon: VIVO (pid {st.pid})")
        if st.last_heartbeat:
            print(f"Ultimo batimento: {st.last_heartbeat.isoformat()}")
    else:
        if st.pid:
            print(f"Daemon: MORTO (pidfile obsoleto: {st.pid}; rode 'stop' p/ limpar)")
        else:
            print("Daemon: parado")

    _print_pause_state(paths, st.paused)

    store = _store(paths)
    opens = store.open_anomalies()
    print(f"Eventos abertos: {len(opens)}")
    for finding in opens[-5:]:
        print(f"  - {_event_line(finding)}")
    return 0


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


def cmd_pause(paths: settings.Paths, args: argparse.Namespace) -> int:
    daemon.pause(paths)
    st = daemon.status(paths)
    if st.running:
        print(
            f"Vigilancia pausada (daemon pid {st.pid} segue amostrando; para de "
            "registrar anomalias no proximo batimento)."
        )
    else:
        print(
            "Vigilancia pausada. O daemon nao esta rodando agora — quando "
            "subir, ja sobe pausado (e assim que sobrevive a reboot)."
        )
    print(f"Arquivo: {paths.paused}")
    return 0


def cmd_resume(paths: settings.Paths, args: argparse.Namespace) -> int:
    if not daemon.resume(paths):
        print("Nada estava pausado.")
        return 0
    st = daemon.status(paths)
    state = f"no proximo batimento (pid {st.pid})" if st.running else "quando o daemon subir"
    print(f"Vigilancia retomada {state}.")
    return 0


def cmd_watch(paths: settings.Paths, args: argparse.Namespace) -> int:
    sensor = Sensor()
    stop_after = 1 if args.once else None
    ticks = daemon.run_watch_loop(
        paths,
        sensor=sensor,
        store=_store(paths),
        incident_sources=daemon.build_incident_sources(),
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


def cmd_fix(paths: settings.Paths, args: argparse.Namespace) -> int:
    from sentinel.system.prompt import is_interactive
    from sentinel.tutor import run_cycle

    store = _store(paths)
    overrides = settings.load_overrides(paths)
    db = _kbstore(paths)

    if args.event_id:
        event = store.find(args.event_id)
        if event is None or event.get("kind") != "anomaly":
            print(f"[ERROR] anomalia nao encontrada: {args.event_id}")
            return 1
    else:
        event = store.latest_open()
        if event is None:
            print("Nenhuma anomalia aberta pra corrigir. Rode 'sentinel status'.")
            return 0

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


def cmd_kill(paths: settings.Paths, args: argparse.Namespace) -> int:
    from sentinel.processctl import ProcessCtl
    from sentinel.system.prompt import is_interactive

    ctl = ProcessCtl()
    result = ctl.kill_tree(args.pid, interactive=is_interactive(), include_children=args.tree)

    if result.refused:
        print(f"[RECUSADO] {result.refused_reason}")
        return 1
    if result.ok:
        print(f"Encerrado: pid(s) {', '.join(map(str, result.killed))}")
        return 0
    print(
        f"[PARCIAL] encerrados {result.killed}; falharam {result.failed}"
    )
    return 1


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
    )
    return 0


_COMMANDS = {
    "start": cmd_start,
    "stop": cmd_stop,
    "status": cmd_status,
    "pause": cmd_pause,
    "resume": cmd_resume,
    "watch": cmd_watch,
    "events": cmd_events,
    "fix": cmd_fix,
    "kb": cmd_kb,
    "kill": cmd_kill,
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

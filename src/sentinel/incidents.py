from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from sentinel import settings
from sentinel.detector import SEV_INFO, SEV_WARNING
from sentinel.processctl import is_protected, is_self


# Métricas que não nascem de limiar, e sim de um incidente observado. Vivem
# aqui (e não em `detector`) porque o detector é só de série temporal; o
# contrato no JSONL é o mesmo de qualquer `metric`: string estável.
METRIC_ORPHAN_TREE = "orphan_tree"
METRIC_APP_FAILURE = "app_failure"


@dataclass
class Incident:
    """Anomalia sem `value`/`threshold`: o que importa é o `detail` (quem,
    onde, quando) e a `label` de uma linha pro log/CLI.

    `events.EventStore.record_incident` transforma isto numa linha
    `kind: anomaly` de schema 2, com o mesmo dedupe por fingerprint das
    finding de limiar.
    """

    metric: str
    severity: str
    detail: dict
    fingerprint: str
    label: str = ""

    def to_dict(self) -> dict:
        return {
            "metric": self.metric,
            "severity": self.severity,
            "label": self.label,
            "detail": self.detail,
            "fingerprint": self.fingerprint,
        }


def _skip_name(name: str) -> bool:
    """Núcleo do Windows, o próprio Sentinel e o Idle não são matéria-prima
    de árvore órfã: sem esse filtro cada boot geraria eventos falsos."""
    low = (name or "").lower()
    return (
        is_protected(low)
        or is_self(low)
        or low in settings.NON_CULPRIT_PROCESS_NAMES
    )


@dataclass
class _Entry:
    pid: int
    ppid: int | None
    name: str
    create_time: float


@dataclass
class TreeMonitor:
    """Vigia a árvore de processos e anuncia quem ficou órfão.

    Por que histórico: no Windows não há reparente — quando um pai morre, o
    filho continua apontando `ppid` pro PID morto (ou, pior, pro processo
    que reusou aquele PID). Olhar o snapshot atual sozinho não distingue
    "órfão de agora" de "deram um pai morto pra ele em algum momento do
    boot". Então a regra é de TRANSIÇÃO: o pai estava vivo no ciclo
    anterior, sumiu neste, e ao menos um descendente sobreviveu.

    Consequência honesta: o primeiro ciclo é aquecimento e nunca emite — o
    Sentinel não pode lamentar a morte de um processo que nunca viu vivo.

    psutil injetável, como no resto do pacote (testes sem processos reais).
    """

    psutil_module: object = None
    _prev: dict | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.psutil_module is None:
            import psutil as psutil_module  # type: ignore[no-redef]

            self.psutil_module = psutil_module

    # -- snapshot ------------------------------------------------------

    def snapshot(self) -> dict:
        """{pid: _Entry} de todos os processos visíveis ao usuário.

        Não filtra aqui: o mapa completo é o que permite saber que o pai era
        um svchost (e portanto ignorar o caso) em vez de adivinhar por nome
        do filho. `create_time` entra porque PID é recyclável: mesmo número,
        outra vida.
        """
        ps = self.psutil_module
        entries: dict = {}
        for proc in ps.process_iter():
            try:
                with proc.oneshot():
                    entries[proc.pid] = _Entry(
                        pid=int(proc.pid),
                        ppid=proc.ppid(),
                        name=proc.name(),
                        create_time=float(proc.create_time()),
                    )
            except Exception:
                # Processos somem entre listar e ler (race normal no
                # Windows); perder uma entrada num tick nao e perder a
                # vigilancia.
                continue
        return entries

    # -- regra ---------------------------------------------------------

    def observe(self, now: datetime.datetime | None = None) -> list[Incident]:
        """Um ciclo: tira o snapshot e devolve as árvores órfãs novas.

        `now` existe pra assinar o mesmo contrato dos outros monitores de
        incidente (o daemon chama todos do mesmo jeito); a árvore não usa
        relógio — a ordem dos snapshots já é o tempo.
        """
        current = self.snapshot()
        previous = self._prev
        self._prev = current

        found: list[Incident] = []
        if previous is None:
            return found

        children_of: dict = {}
        for entry in previous.values():
            if entry.ppid is not None:
                children_of.setdefault(entry.ppid, []).append(entry.pid)

        # Quem morreu (ou teve o PID reciclado) neste ciclo.
        dead: dict = {}
        for pid, old in previous.items():
            alive = current.get(pid)
            if alive is None or alive.create_time != old.create_time:
                dead[pid] = old

        for pid, old in dead.items():
            if _has_dead_ancestor(pid, previous, dead):
                continue  # o antepassado mais alto ja conta este estrago
            subtree = _surviving_subtree(pid, previous, current, children_of)
            if not subtree:
                continue  # morreu levando a árvore junto: saida limpa
            if _skip_name(old.name):
                continue

            found.append(_orphan_incident(old, subtree))
        return found


def _has_dead_ancestor(pid: int, previous: dict, dead: dict) -> bool:
    """O pai (ou avô) deste morto também morreu? Então este incidente já é
    coberto pelo antepassado: sem isso, uma queda em cascata viria como duas
    anomalias da mesma árvore."""
    seen = {pid}
    entry = previous.get(pid)
    while entry is not None and entry.ppid is not None:
        if entry.ppid in seen:
            return False  # ciclo de ppid (dados corrompidos): para de subir
        if entry.ppid in dead:
            return True
        seen.add(entry.ppid)
        entry = previous.get(entry.ppid)
    return False


def _surviving_subtree(
    dead_pid: int,
    previous: dict,
    current: dict,
    children_of: dict,
) -> list:
    """Descendentes do pai morto que ainda estão vivos AGORA, com profundidade.

    Devolve listas de `(entry_atual, depth)` ordenadas por profundidade e
    depois por PID — ordem estável pra UI indentar e pra fingerprint não
    depender de acaso.
    """
    out: list = []
    seen: set = set()
    # (pid_do_pai_morto_como_raiz) -> pilha de (pid, depth)
    stack = [(child, 1) for child in reversed(children_of.get(dead_pid, []))]
    while stack:
        pid, depth = stack.pop()
        if pid in seen or pid not in previous:
            continue
        seen.add(pid)
        entry = previous[pid]
        if entry.name and _skip_name(entry.name):
            continue  # sobra de sistema/autoproclamado: nao e nossa arvore
        alive = current.get(pid)
        if alive is not None and alive.create_time == entry.create_time:
            out.append((alive, depth))
        for child in reversed(children_of.get(pid, [])):
            stack.append((child, depth + 1))
    out.sort(key=lambda item: (item[1], item[0].pid))
    return out


def _orphan_incident(dead: _Entry, subtree: list) -> Incident:
    direct = [entry for entry, depth in subtree if depth == 1]
    rows = [
        {
            "pid": entry.pid,
            "ppid": entry.ppid,
            "name": entry.name,
            "depth": depth,
        }
        for entry, depth in subtree
    ]
    # 1 sobrevivente costuma ser desapego proposital (daemoniza, solta o
    # filho); a partir de 2 é a assinatura de vazamento de árvore.
    severity = SEV_WARNING if len(subtree) >= 2 else SEV_INFO
    detail = {
        "parent": {"pid": dead.pid, "name": dead.name},
        "orphans": [row for row in rows if row["depth"] == 1],
        "orphan_count": len(direct),
        "tree": rows,
        "tree_size": len(rows),
    }
    label = (
        f"{dead.name} (pid {dead.pid}) saiu deixando "
        f"{len(rows)} processo(s) vivo(s) na árvore"
    )
    return Incident(
        metric=METRIC_ORPHAN_TREE,
        severity=severity,
        detail=detail,
        fingerprint=f"{METRIC_ORPHAN_TREE}:{severity}:{dead.name}",
        label=label,
    )

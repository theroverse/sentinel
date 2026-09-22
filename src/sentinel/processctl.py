from __future__ import annotations

import os
from dataclasses import dataclass, field

from sentinel import settings


@dataclass
class ProcInfo:
    pid: int
    name: str
    ppid: int | None = None
    cpu: float = 0.0
    rss_mb: float = 0.0

    @property
    def base_name(self) -> str:
        return self.name.lower()


@dataclass
class KillResult:
    killed: list[int] = field(default_factory=list)
    failed: list[int] = field(default_factory=list)
    refused_reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.refused_reason is None and not self.failed

    @property
    def refused(self) -> bool:
        return self.refused_reason is not None


def is_protected(name: str) -> bool:
    """Nome esta na lista de nucleos do Windows que nunca podem morrer?

    Comparacao pela base minuscula (com e sem '.exe'), porque o usuario/
    evento pode reportar 'csrss' ou 'csrss.exe'.
    """
    low = name.lower()
    base = low.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
    if base in settings.PROTECTED_PROCESS_NAMES:
        return True
    if f"{base}.exe" in settings.PROTECTED_PROCESS_NAMES:
        return True
    return False


def is_self(name: str) -> bool:
    """Processo do proprio Sentinel/interpretador Python: nunca alvo."""
    low = name.lower()
    return any(hint in low for hint in settings.SELF_PROCESS_HINTS)


def service_recommendation(service_name: str) -> str:
    """Um servico do Windows NUNCA deve ser morto por PID (deixa o SCM em
    estado estranho). Em vez disso, devolve o comando pronto pro usuario
    rodar por conta propria, com um degrau de consciencia."""
    return f'net stop "{service_name}"'


class ProcessCtl:
    """Operacoes de processo seguras, com lista protegida + confirmacao.

    psutil injetavel p/ teste sem processos reais nem privilégios.
    """

    def __init__(self, psutil_module=None) -> None:
        if psutil_module is None:
            import psutil as psutil_module  # type: ignore[no-redef]
        self._ps = psutil_module

    def info(self, pid: int) -> ProcInfo | None:
        try:
            proc = self._ps.Process(pid)
            with proc.oneshot():
                return ProcInfo(
                    pid=proc.pid,
                    name=proc.name(),
                    ppid=proc.ppid(),
                    cpu=float(proc.cpu_percent(interval=None)),
                    rss_mb=float(proc.memory_info().rss) / (1024 * 1024),
                )
        except Exception:
            return None

    def suspects(self, *, sort: str = "cpu", n: int | None = None) -> list[ProcInfo]:
        """Top N processos por cpu|mem, JA FILTRADOS dos protegidos e de
        si mesmo — pra `status`/listagem nunca sugerirem matar algo que o
        kill recusaria depois."""
        n = n if n is not None else settings.TOP_PROCESSES
        found: list[ProcInfo] = []
        for proc in self._ps.process_iter(attrs=None):
            try:
                with proc.oneshot():
                    name = proc.name()
                    item = ProcInfo(
                        pid=proc.pid,
                        name=name,
                        ppid=proc.ppid(),
                        cpu=float(proc.cpu_percent(interval=None)),
                        rss_mb=float(proc.memory_info().rss) / (1024 * 1024),
                    )
            except Exception:
                continue
            if is_protected(name) or is_self(name):
                continue
            found.append(item)

        key = (lambda p: p.cpu) if sort == "cpu" else (lambda p: p.rss_mb)
        found.sort(key=key, reverse=True)
        return found[:n]

    def descendants(self, pid: int) -> list[int]:
        """pid + todos os descendentes, em ordem folhas-primeiro (matar
        filho antes do pai, pra nao orfa-los no meio)."""
        try:
            proc = self._ps.Process(pid)
            kids = proc.children(recursive=True)
        except Exception:
            return []
        ordered = [k.pid for k in kids]
        ordered.append(pid)  # alvo por ultimo
        return ordered

    def kill_tree(
        self,
        pid: int,
        *,
        interactive: bool,
        include_children: bool = False,
    ) -> KillResult:
        """Encerra `pid` (e opcionalmente a arvore) com dupla protecao:
        lista protegida/self + confirmacao explicita.

        - Alvo protegido ou self -> refused, nada roda.
        - Sessao nao-interativa -> refused (kill e destrutivo; nunca roda
          sem um humano confirmando, por design do Theroverse).
        - Confirmacao negativa -> refused.
        """
        target = self.info(pid)
        if target is None:
            return KillResult(refused_reason=f"processo {pid} nao existe")

        if is_protected(target.name):
            return KillResult(
                refused_reason=(
                    f"'{target.name}' (pid {pid}) e processo protegido do "
                    "sistema; o Sentinel nunca o encerra."
                )
            )

        if is_self(target.name):
            return KillResult(
                refused_reason=(
                    f"'{target.name}' (pid {pid}) parece ser o proprio "
                    "Sentinel/Python; recuso encerrar a si mesmo."
                )
            )

        if not interactive:
            return KillResult(
                refused_reason=(
                    "sessao nao-interativa: encerrar processo exige "
                    "confirmacao humana."
                )
            )

        from sentinel.system.prompt import confirm

        targets = self.descendants(pid) if include_children else [pid]
        if include_children and len(targets) > 1:
            preview = ", ".join(str(t) for t in targets)
            question = (
                f"Encerrar o processo {pid} e seus descendentes "
                f"[{preview}]?"
            )
        else:
            question = (
                f"Encerrar '{target.name}' (pid {pid}, "
                f"{target.rss_mb:.0f} MB RSS)?"
            )

        if not confirm(question, default=False):
            return KillResult(refused_reason="usuario cancelou")

        return self._terminate(targets)

    def _terminate(self, pids: list[int]) -> KillResult:
        result = KillResult()
        procs: list = []
        for pid in pids:
            try:
                procs.append(self._ps.Process(pid))
            except Exception:
                result.failed.append(pid)

        # terminate gracioso primeiro...
        for proc in procs:
            try:
                proc.terminate()
            except Exception:
                if proc.pid not in result.failed:
                    result.failed.append(proc.pid)

        gone, alive = self._ps.wait_procs(procs, timeout=3)
        for proc in gone:
            result.killed.append(proc.pid)

        # ...kill forçado só nos que resistiram.
        for proc in alive:
            try:
                proc.kill()
                proc.wait(timeout=3)
                result.killed.append(proc.pid)
            except Exception:
                if proc.pid not in result.failed:
                    result.failed.append(proc.pid)

        return result


def current_pid() -> int:
    return os.getpid()

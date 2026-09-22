from __future__ import annotations

import pytest

from conftest import FakeProcess, FakePsutil, tree_proc

from sentinel.detector import SEV_INFO, SEV_WARNING
from sentinel.incidents import METRIC_ORPHAN_TREE, TreeMonitor


# A árvore é reconstruída por `ppid`, não pela lista de `children` do
# FakeProcess: é assim que o psutil real funciona e é o que o Windows
# entrega quando um pai morre (o filho segue apontando pro PID morto).
def _ps(*procs) -> FakePsutil:
    return FakePsutil(processes=list(procs))


def _setup_dies(*, survivors=1, depth=1):
    """Cenário: `setup.exe` (pid 100) com filhos; some entre os dois ticks.

    O neto existe nos dois snapshots (só muda o pai dele): é assim que a
    árvore é reconstruída de verdade — histórico + estado atual.
    """
    before = [
        tree_proc(1, "explorer"),
        tree_proc(100, "setup.exe", ppid=1),
    ]
    kids = [tree_proc(200 + i, "helper.exe", ppid=100) for i in range(survivors)]
    before.extend(kids)
    after = [before[0], *kids]
    if depth > 1 and kids:
        grand = tree_proc(300, "grandchild.exe", ppid=kids[0].pid)
        before.append(grand)
        after.append(grand)
    return before, after


def test_first_observe_is_warmup_and_never_fires():
    # Sem histórico não há como saber quem morreu: o primeiro ciclo só
    # aprende a árvore, mesmo com pais ausentes no snapshot.
    ps = _ps(
        tree_proc(200, "helper.exe", ppid=999),  # pai inexistente de saida
        tree_proc(201, "helper2.exe", ppid=None),
    )
    monitor = TreeMonitor(psutil_module=ps)
    assert monitor.observe() == []


def test_parent_death_with_one_survivor_is_info_orphan():
    before, after = _setup_dies(survivors=1)
    ps = _ps(*before)
    monitor = TreeMonitor(psutil_module=ps)
    assert monitor.observe() == []

    ps.set_processes(after)
    found = monitor.observe()

    assert len(found) == 1
    inc = found[0]
    assert inc.metric == METRIC_ORPHAN_TREE
    assert inc.severity == SEV_INFO
    assert inc.detail["parent"] == {"pid": 100, "name": "setup.exe"}
    assert [o["pid"] for o in inc.detail["orphans"]] == [200]
    assert inc.detail["orphan_count"] == 1
    assert "setup.exe" in inc.label and "100" in inc.label


def test_surviving_subtree_is_mapped_with_depth_and_escalates_to_warning():
    before, after = _setup_dies(survivors=2, depth=2)
    ps = _ps(*before)
    monitor = TreeMonitor(psutil_module=ps)
    monitor.observe()

    ps.set_processes(after)
    inc = monitor.observe()[0]

    assert inc.severity == SEV_WARNING  # >=2 processos vivos na arvo órfã
    assert inc.detail["orphan_count"] == 2
    # Mapa completo da descendencia viva, com o pai morto como raiz (depth 0).
    by_pid = {row["pid"]: row for row in inc.detail["tree"]}
    assert by_pid[200]["depth"] == 1 and by_pid[200]["name"] == "helper.exe"
    assert by_pid[201]["depth"] == 1
    assert by_pid[300]["depth"] == 2 and by_pid[300]["ppid"] == 200


def test_clean_exit_leaves_no_incident():
    before, after = _setup_dies(survivors=1)
    ps = _ps(*before)
    monitor = TreeMonitor(psutil_module=ps)
    monitor.observe()

    # setup.exe saiu E o filho saiu junto: nada órfão, nada a registrar.
    ps.set_processes([tree_proc(1, "explorer")])
    assert monitor.observe() == []


def test_protected_parent_death_is_not_reported():
    # Filho de um svchost que reiniciou: núcleo do Windows, fora de escopo.
    ps = _ps(
        tree_proc(50, "svchost.exe", ppid=1),
        tree_proc(60, "task.exe", ppid=50),
    )
    monitor = TreeMonitor(psutil_module=ps)
    monitor.observe()

    ps.set_processes([tree_proc(60, "task.exe", ppid=50)])
    assert monitor.observe() == []


def test_protected_or_self_survivors_are_skipped():
    # O pai morto é um app comum, mas quem sobrou é sistema/Python: não é
    # árvore órfã do Sentinel (seria falso-positivo permanente).
    ps = _ps(
        tree_proc(100, "launcher.exe", ppid=1),
        tree_proc(60, "svchost.exe", ppid=100),
        tree_proc(61, "python.exe", ppid=100),
    )
    monitor = TreeMonitor(psutil_module=ps)
    monitor.observe()

    ps.set_processes(
        [
            tree_proc(60, "svchost.exe", ppid=100),
            tree_proc(61, "python.exe", ppid=100),
        ]
    )
    assert monitor.observe() == []


def test_reused_pid_counts_as_death_of_the_old_parent():
    # O Windows não reparenta: se o PID volta com outro create_time, o pai
    # de verdade morreu e os filhos dele ficaram órfãos.
    ps = _ps(
        tree_proc(100, "installer.exe", ppid=1, create_time=1000.0),
        tree_proc(200, "worker.exe", ppid=100),
    )
    monitor = TreeMonitor(psutil_module=ps)
    monitor.observe()

    ps.set_processes(
        [
            tree_proc(100, "other-app.exe", ppid=1, create_time=2000.0),
            tree_proc(200, "worker.exe", ppid=100),
        ]
    )
    found = monitor.observe()
    assert len(found) == 1
    assert found[0].detail["parent"]["name"] == "installer.exe"


def test_fingerprint_is_stable_so_the_store_can_dedupe():
    # Duas mortes iguais de app têm que colapsar numa linha só de evento.
    incidents = []
    for _ in range(2):
        before, after = _setup_dies(survivors=1)
        ps = _ps(*before)
        monitor = TreeMonitor(psutil_module=ps)
        monitor.observe()
        ps.set_processes(after)
        incidents.append(monitor.observe()[0])

    assert incidents[0].fingerprint == incidents[1].fingerprint
    assert incidents[0].fingerprint == "orphan_tree:info:setup.exe"


def test_snapshot_tolerates_processes_that_vanish_mid_read():
    class Dying(FakeProcess):
        def create_time(self):
            raise OSError("processo sumiu entre listar e ler")

    ps = _ps(
        tree_proc(100, "installer.exe", ppid=1),
        Dying(101, "worker.exe", ppid=100),
    )
    monitor = TreeMonitor(psutil_module=ps)
    assert monitor.observe() == []  # nao explode; o sumido so sai do snapshot


def test_grandchild_of_dead_parent_is_reported_even_when_child_died_too():
    # child morreu junto, mas o neto sobreviveu: ainda é árvore órfã, e o
    # mapa precisa mostrar o elo quebrado (ppid aponta pro filho morto).
    ps = _ps(
        tree_proc(100, "installer.exe", ppid=1),
        tree_proc(200, "mid.exe", ppid=100),
        tree_proc(300, "leaf.exe", ppid=200),
    )
    monitor = TreeMonitor(psutil_module=ps)
    monitor.observe()

    ps.set_processes([tree_proc(300, "leaf.exe", ppid=200)])
    found = monitor.observe()
    assert len(found) == 1
    by_pid = {row["pid"]: row for row in found[0].detail["tree"]}
    assert by_pid[300]["depth"] == 2
    assert by_pid[300]["ppid"] == 200  # elo quebrado, preservado no mapa


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

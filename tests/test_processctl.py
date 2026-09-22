from __future__ import annotations

from unittest.mock import patch

from conftest import FakeProcess, FakePsutil

from sentinel.processctl import ProcessCtl, is_protected, is_self, service_recommendation


def test_is_protected_matches_with_and_without_exe():
    assert is_protected("csrss.exe")
    assert is_protected("csrss")
    assert is_protected("C:\\Windows\\System32\\lsass.exe")
    assert not is_protected("chrome")


def test_is_self_detects_python_and_sentinel():
    assert is_self("python.exe")
    assert is_self("sentinel")
    assert not is_self("firefox")


def test_service_recommendation_is_command_string():
    cmd = service_recommendation("Spooler")
    assert "net stop" in cmd
    assert "Spooler" in cmd


def _ctl(procs):
    return ProcessCtl(psutil_module=FakePsutil(processes=procs))


def test_kill_refuses_protected():
    procs = [FakeProcess(100, "csrss.exe")]
    result = _ctl(procs).kill_tree(100, interactive=True)
    assert result.refused
    assert "protegido" in result.refused_reason


def test_kill_refuses_self():
    procs = [FakeProcess(200, "python.exe")]
    result = _ctl(procs).kill_tree(200, interactive=True)
    assert result.refused
    assert "Sentinel/Python" in result.refused_reason


def test_kill_refuses_when_missing():
    result = _ctl([]).kill_tree(999, interactive=True)
    assert result.refused
    assert "nao existe" in result.refused_reason


def test_kill_refuses_non_interactive():
    procs = [FakeProcess(300, "hogapp")]
    result = _ctl(procs).kill_tree(300, interactive=False)
    assert result.refused
    assert "nao-interativa" in result.refused_reason


def test_kill_cancelled_by_user():
    procs = [FakeProcess(301, "hogapp")]
    with patch("sentinel.system.prompt.confirm", return_value=False):
        result = _ctl(procs).kill_tree(301, interactive=True)
    assert result.refused
    assert result.refused_reason == "usuario cancelou"
    assert not procs[0].terminated


def test_kill_success_terminates():
    procs = [FakeProcess(302, "hogapp", rss=10 * 1024 * 1024)]
    with patch("sentinel.system.prompt.confirm", return_value=True):
        result = _ctl(procs).kill_tree(302, interactive=True)
    assert result.ok
    assert result.killed == [302]
    assert procs[0].terminated


def test_kill_tree_includes_descendants():
    child = FakeProcess(401, "child")
    parent = FakeProcess(400, "parent", children=[child])
    with patch("sentinel.system.prompt.confirm", return_value=True):
        result = _ctl([parent, child]).kill_tree(
            400, interactive=True, include_children=True
        )
    assert result.ok
    assert set(result.killed) == {401, 400}
    assert child.terminated and parent.terminated


def test_suspects_filter_protected_and_self():
    procs = [
        FakeProcess(1, "csrss.exe", cpu=99),
        FakeProcess(2, "python.exe", cpu=98),
        FakeProcess(3, "chrome", cpu=50, rss=200 * 1024 * 1024),
        FakeProcess(4, "notepad", cpu=10),
    ]
    suspects = _ctl(procs).suspects(sort="cpu", n=5)
    names = [p.name for p in suspects]
    assert "csrss.exe" not in names
    assert "python.exe" not in names
    assert names == ["chrome", "notepad"]

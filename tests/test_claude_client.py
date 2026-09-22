from __future__ import annotations

from unittest.mock import MagicMock, patch

from sentinel.claude_client import call_claude, parse_options


# -- call_claude (bridge igual ao do Zeus) -------------------------------
def test_call_claude_none_when_missing():
    with patch("sentinel.claude_client.command_exists", return_value=False), \
         patch("sentinel.claude_client.run_command") as mock_run:
        assert call_claude("p") is None
    mock_run.assert_not_called()


def test_call_claude_none_on_error():
    fake = MagicMock(returncode=1, stdout="", stderr="boom")
    with patch("sentinel.claude_client.command_exists", return_value=True), \
         patch("sentinel.claude_client.run_command", return_value=fake):
        assert call_claude("p") is None


def test_call_claude_returns_stdout():
    fake = MagicMock(returncode=0, stdout="  [{}]  \n", stderr="")
    with patch("sentinel.claude_client.command_exists", return_value=True), \
         patch("sentinel.claude_client.run_command", return_value=fake):
        assert call_claude("p") == "[{}]"


# -- parse_options (tolerante a cerca de codigo / prosa) -----------------
def test_parse_plain_json_array():
    text = '[{"title": "A", "steps": ["um", "dois"]}]'
    options = parse_options(text, max_options=3)
    assert options == [{"title": "A", "steps": ["um", "dois"]}]


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
    text = '[{"title": "%d", "steps": ["a"]}]'
    import json

    arr = [{"title": str(i), "steps": ["x"]} for i in range(10)]
    options = parse_options(json.dumps(arr), max_options=3)
    assert len(options) == 3


def test_parse_returns_none_on_garbage():
    assert parse_options("sem json aqui", max_options=3) is None
    assert parse_options("", max_options=3) is None

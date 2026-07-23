from __future__ import annotations

import sys
from pathlib import Path

import pytest

from automation.wb_mcp_client import MCPClientError, MCPToolError, WBMCPClient


FAKE_SERVER = r"""
import json
import sys
import time

mode = sys.argv[1]

def send(message):
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()

for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    if method == "initialize":
        if mode == "malformed":
            sys.stdout.write("not-json\n")
            sys.stdout.flush()
            continue
        send({
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake-wb", "version": "1"},
            },
        })
    elif method == "notifications/initialized":
        continue
    elif method == "tools/call":
        if mode == "stderr":
            sys.stderr.write("SERVER_LOG_MARKER\n")
            sys.stderr.flush()
        if mode == "exit":
            raise SystemExit(7)
        if mode == "timeout":
            time.sleep(60)
            continue
        if mode == "error":
            send({
                "jsonrpc": "2.0",
                "id": request["id"],
                "error": {"code": -32603, "message": "SECRET_MARKER"},
            })
            continue
        if mode == "business_error":
            send({
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": {
                    "content": [{
                        "type": "text",
                        "text": (
                            '{"ok":false,"error":{"kind":"rate_limited",'
                            '"message":"SECRET_MARKER","retryable":true}}'
                        ),
                    }],
                    "structuredContent": {
                        "ok": False,
                        "error": {
                            "kind": "rate_limited",
                            "message": "SECRET_MARKER",
                            "retryable": True,
                        },
                    },
                    "isError": False,
                },
            })
            continue
        send({
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {
                "content": [{"type": "text", "text": "{\"ok\": true}"}],
                "structuredContent": {
                    "tool": request["params"]["name"],
                    "arguments": request["params"]["arguments"],
                },
                "isError": False,
            },
        })
"""


@pytest.fixture
def fake_server(tmp_path: Path) -> Path:
    path = tmp_path / "fake_mcp.py"
    path.write_text(FAKE_SERVER, encoding="utf-8")
    return path


def test_client_initializes_once_and_returns_structured_content(
    fake_server: Path,
) -> None:
    with WBMCPClient(
        command=[sys.executable, str(fake_server), "ok"],
        timeout=1,
    ) as client:
        first = client.call_tool("wb_list_campaigns", {"payload": {"statuses": [9]}})
        second = client.call_tool("wb_get_balance")

    assert first == {
        "tool": "wb_list_campaigns",
        "arguments": {"payload": {"statuses": [9]}},
    }
    assert second == {"tool": "wb_get_balance", "arguments": {}}
    assert client.is_running is False


def test_client_never_echoes_remote_error_or_arguments(fake_server: Path) -> None:
    with WBMCPClient(
        command=[sys.executable, str(fake_server), "error"],
        timeout=1,
    ) as client:
        with pytest.raises(MCPClientError) as caught:
            client.call_tool(
                "wb_list_campaigns",
                {"payload": {"secret": "SECRET_ARGUMENT"}},
            )

    rendered = str(caught.value)
    assert "SECRET_MARKER" not in rendered
    assert "SECRET_ARGUMENT" not in rendered


def test_client_raises_typed_safe_business_error(fake_server: Path) -> None:
    with WBMCPClient(
        command=[sys.executable, str(fake_server), "business_error"],
        timeout=1,
    ) as client:
        with pytest.raises(MCPToolError) as caught:
            client.call_tool("wb_get_campaign_stats")

    assert caught.value.kind == "rate_limited"
    assert caught.value.retryable is True
    assert "SECRET_MARKER" not in str(caught.value)


def test_client_rejects_malformed_stdout_without_echoing_it(fake_server: Path) -> None:
    with pytest.raises(MCPClientError) as caught:
        WBMCPClient(
            command=[sys.executable, str(fake_server), "malformed"],
            timeout=1,
        ).start()

    assert "not-json" not in str(caught.value)


def test_client_reports_child_exit_without_raw_process_output(
    fake_server: Path,
) -> None:
    with WBMCPClient(
        command=[sys.executable, str(fake_server), "exit"],
        timeout=1,
    ) as client:
        with pytest.raises(MCPClientError) as caught:
            client.call_tool("wb_get_balance")

    assert "7" not in str(caught.value)


def test_client_times_out_and_closes_the_child(fake_server: Path) -> None:
    client = WBMCPClient(
        command=[sys.executable, str(fake_server), "timeout"],
        timeout=0.05,
    )

    with pytest.raises(MCPClientError) as caught:
        with client:
            client.call_tool("wb_get_balance")

    assert "timed out" in str(caught.value).lower()
    assert client.is_running is False


def test_client_does_not_pollute_script_stderr_with_server_logs(
    fake_server: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    with WBMCPClient(
        command=[sys.executable, str(fake_server), "stderr"],
        timeout=1,
    ) as client:
        client.call_tool("wb_get_balance")

    assert "SERVER_LOG_MARKER" not in capfd.readouterr().err


def test_client_requires_a_nonempty_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WB_MCP_COMMAND", " ")

    with pytest.raises(MCPClientError):
        WBMCPClient().start()

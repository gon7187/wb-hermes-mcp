"""Small synchronous stdio client for Hermes WB automation scripts."""

from __future__ import annotations

import json
import os
import re
import selectors
import shlex
import subprocess
import time
from collections.abc import Mapping, Sequence
from typing import Any

DEFAULT_COMMAND = "/opt/wb-hermes-mcp/run-wb-mcp"
PROTOCOL_VERSION = "2025-11-25"


class MCPClientError(RuntimeError):
    """A transport error safe to show without request or process details."""


class MCPToolError(MCPClientError):
    """A sanitized WB business error returned inside a successful MCP response."""

    def __init__(self, *, kind: object, retryable: object) -> None:
        rendered_kind = kind if isinstance(kind, str) else ""
        if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", rendered_kind) is None:
            rendered_kind = "unknown"
        self.kind = rendered_kind
        self.retryable = retryable is True
        super().__init__("WB MCP tool returned a business error.")


def _check_business_error(result: Mapping[str, object]) -> None:
    if result.get("ok") is not False:
        return
    error = result.get("error")
    details = error if isinstance(error, Mapping) else {}
    raise MCPToolError(
        kind=details.get("kind"),
        retryable=details.get("retryable"),
    )


class WBMCPClient:
    """Keep one WB MCP subprocess alive for all calls in a script run."""

    def __init__(
        self,
        *,
        command: Sequence[str] | None = None,
        timeout: float = 120,
    ) -> None:
        self._command = list(command) if command is not None else None
        self._timeout = timeout
        self._next_id = 1
        self._process: subprocess.Popen[bytes] | None = None
        self._selector: selectors.BaseSelector | None = None

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def __enter__(self) -> WBMCPClient:
        return self.start()

    def __exit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        self.close()

    def start(self) -> WBMCPClient:
        if self.is_running:
            return self
        command = self._command
        if command is None:
            command = shlex.split(os.getenv("WB_MCP_COMMAND", DEFAULT_COMMAND))
        if not command:
            raise MCPClientError("WB MCP command is not configured.")
        if self._timeout <= 0:
            raise MCPClientError("WB MCP timeout is invalid.")

        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except OSError as error:
            raise MCPClientError("WB MCP process could not be started.") from error

        if process.stdin is None or process.stdout is None:
            process.terminate()
            raise MCPClientError("WB MCP process pipes are unavailable.")

        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        self._process = process
        self._selector = selector
        try:
            self._request(
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {
                        "name": "hermes-wb-automation",
                        "version": "1",
                    },
                },
            )
            self._send("notifications/initialized", {})
        except MCPClientError:
            self.close()
            raise
        return self

    def call_tool(
        self,
        name: str,
        arguments: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        if not name:
            raise MCPClientError("WB MCP tool name is invalid.")
        if not self.is_running:
            self.start()
        result = self._request(
            "tools/call",
            {"name": name, "arguments": dict(arguments or {})},
        )
        if result.get("isError") is True:
            raise MCPClientError("WB MCP tool returned an error.")

        structured = result.get("structuredContent")
        if isinstance(structured, Mapping):
            _check_business_error(structured)
            return dict(structured)

        content = result.get("content")
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, Mapping) or not isinstance(
                    item.get("text"), str
                ):
                    continue
                try:
                    decoded = json.loads(item["text"])
                except (TypeError, json.JSONDecodeError):
                    continue
                if isinstance(decoded, Mapping):
                    _check_business_error(decoded)
                    return dict(decoded)
        raise MCPClientError("WB MCP tool returned no structured result.")

    def close(self) -> None:
        process = self._process
        selector = self._selector
        self._process = None
        self._selector = None

        if selector is not None:
            selector.close()
        if process is None:
            return
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=0.5)
        if process.stdout is not None:
            process.stdout.close()

    def restart(self) -> WBMCPClient:
        """Replace a failed child process before retrying a read-only call."""

        self.close()
        return self.start()

    def _request(
        self,
        method: str,
        params: Mapping[str, object],
    ) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        self._send(method, params, request_id=request_id)
        return self._receive(request_id)

    def _send(
        self,
        method: str,
        params: Mapping[str, object],
        *,
        request_id: int | None = None,
    ) -> None:
        process = self._process
        if process is None or process.stdin is None or process.poll() is not None:
            raise MCPClientError("WB MCP process is not running.")
        message: dict[str, object] = {
            "jsonrpc": "2.0",
            "method": method,
            "params": dict(params),
        }
        if request_id is not None:
            message["id"] = request_id
        try:
            process.stdin.write(
                json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode()
                + b"\n"
            )
            process.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            raise MCPClientError("WB MCP request could not be sent.") from error

    def _receive(self, request_id: int) -> dict[str, Any]:
        process = self._process
        selector = self._selector
        if process is None or process.stdout is None or selector is None:
            raise MCPClientError("WB MCP process is not running.")

        deadline = time.monotonic() + self._timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MCPClientError("WB MCP request timed out.")
            if process.poll() is not None:
                raise MCPClientError("WB MCP process exited unexpectedly.")
            if not selector.select(remaining):
                raise MCPClientError("WB MCP request timed out.")

            line = process.stdout.readline()
            if not line:
                raise MCPClientError("WB MCP process exited unexpectedly.")
            try:
                message = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise MCPClientError(
                    "WB MCP returned malformed protocol data."
                ) from error
            if not isinstance(message, Mapping) or message.get("id") != request_id:
                continue
            if "error" in message:
                raise MCPClientError("WB MCP returned a protocol error.")
            result = message.get("result")
            if not isinstance(result, Mapping):
                raise MCPClientError("WB MCP returned malformed protocol data.")
            return dict(result)

import pytest

from wb_mcp import server


def test_server_has_wb_name() -> None:
    assert server.create_server(token="test-token").name == "wb_mcp"


def test_main_uses_stdio_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    class RecordingServer:
        transport: str | None = None

        def run(self, *, transport: str) -> None:
            self.transport = transport

    recording_server = RecordingServer()
    monkeypatch.setattr(server, "create_server", lambda: recording_server)

    server.main()

    assert recording_server.transport == "stdio"

from wb_mcp.server import create_server


def test_server_has_wb_name() -> None:
    assert create_server(token="test-token").name == "wb_mcp"

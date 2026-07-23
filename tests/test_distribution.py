import anyio
import json
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TextIO, cast

import pytest
from mcp import ClientSession, StdioServerParameters, stdio_client


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_stdio_entrypoint_performs_mcp_handshake_and_advertises_tools() -> None:
    """The installed module must speak clean MCP over an actual subprocess pipe."""

    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "wb_mcp"],
        cwd=PROJECT_ROOT,
        env={"WB_API_TOKEN": "test-token"},
    )
    with NamedTemporaryFile(mode="w+", encoding="utf-8") as stderr:
        async with stdio_client(parameters, errlog=cast(TextIO, stderr)) as (
            read,
            write,
        ):
            async with ClientSession(read, write) as client:
                with anyio.fail_after(10):
                    await client.initialize()
                    tools = await client.list_tools()

        stderr.seek(0)
        stderr_output = stderr.read()

    names = {tool.name for tool in tools.tools}
    assert len(names) == 50
    assert {
        "wb_get_seller_profile",
        "wb_list_cards",
        "wb_get_campaign_stats",
        "wb_get_balance",
        "wb_list_feedbacks",
        "wb_plan_set_prices",
        "wb_plan_update_bids",
        "wb_apply_change",
    } <= names
    # FastMCP may log normal protocol activity to stderr; stdout still completed
    # a valid MCP handshake above.  Neither errors nor the runtime credential may leak.
    assert "Traceback" not in stderr_output
    assert "test-token" not in stderr_output


def test_deploy_assets_describe_a_secret_safe_hermes_registration() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    wrapper = (PROJECT_ROOT / "deploy" / "run-wb-mcp.sh").read_text(encoding="utf-8")
    hermes_example = (PROJECT_ROOT / "deploy" / "hermes-wb-mcp.yaml.example").read_text(
        encoding="utf-8"
    )

    assert "hermes mcp add wb --command /opt/wb-hermes-mcp/run-wb-mcp" in readme
    assert "WB_API_TOKEN" in readme
    assert "WB_API_TOKEN=<" not in readme
    assert "set -euo pipefail" in wrapper
    assert "wb.env" in wrapper
    assert "exec" in wrapper
    assert "/opt/wb-hermes-mcp/run-wb-mcp" in hermes_example
    assert "WB_API_TOKEN" not in hermes_example


def test_glm_routing_eval_covers_core_workflows_with_advertised_tools() -> None:
    cases = json.loads(
        (PROJECT_ROOT / "evals" / "glm-tool-routing.json").read_text(encoding="utf-8")
    )

    assert len(cases) >= 10
    expected_tools = {case["expected_tool"] for case in cases}
    assert {
        "wb_get_seller_profile",
        "wb_list_cards",
        "wb_get_stocks",
        "wb_get_campaign_stats",
        "wb_plan_update_bids",
        "wb_get_balance",
        "wb_plan_reply_feedback",
        "wb_plan_cancel_order",
        "wb_plan_start_report",
        "wb_plan_deposit_campaign_budget",
    } <= expected_tools


def test_tool_reference_lists_every_public_mcp_tool() -> None:
    from wb_mcp import server

    reference = (PROJECT_ROOT / "docs" / "tools.md").read_text(encoding="utf-8")

    assert not [tool for tool in server._PUBLIC_OPERATION_HELP if tool not in reference]

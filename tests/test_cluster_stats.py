import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from wb_mcp import server, gateway
from test_server import RecordingGateway

@pytest.fixture
def anyio_backend():
    return 'asyncio'

@pytest.mark.anyio
async def test_cluster_stats_read_only_contract():
    g = RecordingGateway()
    s = server.create_server(token='test-token', gateway=g)
    payload = {'date_from':'2026-09-21','date_to':'2026-09-22','items':[{'campaign_id':123,'nm_id':456}]}
    async with create_connected_server_and_client_session(s, raise_exceptions=True) as c:
        tools = {t.name:t for t in (await c.list_tools()).tools}
        assert 'wb_get_search_cluster_stats' in tools
        assert tools['wb_get_search_cluster_stats'].annotations.readOnlyHint is True
        result = await c.call_tool('wb_get_search_cluster_stats', {'payload':payload})
        assert result.isError is False
    from datetime import date
    expected = {**payload, 'date_from':date(2026,9,21), 'date_to':date(2026,9,22)}
    assert g.calls == [('read','search_cluster_stats',expected)]
    adapted = gateway._adapt_search_cluster_stats(g.calls[0][2])
    assert adapted['v1_get_norm_query_stats_request'].items[0].advert_id == 123

@pytest.mark.parametrize('change', [
    {'items':[]},
    {'items':[{'campaign_id':1,'nm_id':2}]*101},
    {'items':[{'campaign_id':1,'nm_id':2}]*2},
    {'date_from':'2026-09-23','date_to':'2026-09-22'},
    {'items':[{'campaign_id':'1','nm_id':2}]},
    {'unexpected':True},
])
def test_invalid_input_rejected(change):
    from pydantic import ValidationError
    payload={'date_from':'2026-09-21','date_to':'2026-09-22','items':[{'campaign_id':1,'nm_id':2}]}
    with pytest.raises(ValidationError):
        server.SearchClusterStatsPayload.model_validate({**payload,**change})


def test_sdk_cluster_stats_adapter():
    parsed = server.SearchClusterStatsPayload.model_validate({'date_from':'2026-09-21','date_to':'2026-09-22','items':[{'campaign_id':123,'nm_id':456}]})
    r = gateway._adapt_search_cluster_stats(parsed.model_dump())
    body = r['v1_get_norm_query_stats_request'].model_dump(mode='json',by_alias=True)
    assert body == {'from':'2026-09-21','to':'2026-09-22','items':[{'advertId':123,'nmId':456}]}

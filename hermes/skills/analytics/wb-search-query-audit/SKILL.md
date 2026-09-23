---
name: wb-search-query-audit
description: Use when auditing WB ad search queries and exclusions.
---

# WB search-cluster audit

Work personally unless user explicitly authorizes delegation. Load `wb-seller-analytics` first. This is read-only analysis until an exact exclusion diff is approved.

## Working MCP tool

`wb_get_search_cluster_stats` is implemented in `/opt/wb-hermes-mcp` using existing `wildberries-sdk==0.1.130` method `adv_v1_normquery_stats_post`, endpoint `POST /adv/v1/normquery/stats`. Source docs: https://dev.wildberries.ru/openapi/promotion . The docs site may be WAF-blocked; distinguish SDK contract + successful live response from a fresh official-doc verification.

Request:
```json
{"payload":{"date_from":"2026-09-21","date_to":"2026-09-22","items":[{"campaign_id":40326950,"nm_id":420897745}]}}
```
1–100 unique campaign/product pairs; strict IDs, ascending inclusive dates. CPM/CPC supported. Read-only despite POST. Existing public `wb_get_search_clusters` returns active/excluded/archived phrases, NOT their statistics. `wb_get_search_queries` is product search analytics, NOT advertising query statistics.

If current Hermes tool catalog predates the new method, use a fresh `WBMCPClient` process from `/root/.hermes/scripts/wb_mcp_client.py`, calling the same explicit MCP tool with `payload`. Do not bypass MCP or print tokens. New stdio processes load the deployed source immediately; old connected processes may need reconnect. Do not restart the whole gateway during a user request just to refresh tools.

## Collection and interpretation

1. Read live campaign listing to bind exact campaign_id/nm_id, placements and created date. Resolve 'yesterday' with actual MSK dates, not name suffix alone.
2. Fetch current cluster lists and stats for requested pairs; chunk at 100 pairs. Save each batch to disk. No parallel calls for same endpoint. Installed SDK documents 6-second interval for personal/service tokens but 30-minute interval for basic token: token class matters; respect rate limits and bounded read-only retries, never hammer 429.
3. Parse `items[].advertId`, `nmId`, `dailyStats[].date`, `dailyStats[].stat`. A returned pair may OMIT `dailyStats` entirely (observed for a campaign with search disabled); treat missing/null/empty as unknown coverage, not zero, and report it separately. Real fields: `normQuery`, `views`, `clicks`, `atbs`, `orders`, `spend`, `ctr`, `cpc`, `cpm`, `avgPos`, `shks`. These are normalized clusters, not every literal user search. No revenue in verified response: do not invent query DRR.
4. Aggregate by campaign/product/exact normQuery; dedupe day keys and flag conflicts. Sum counts/spend; recompute CTR/CPC/CPM from totals, never average daily rates. Missing data is unknown, not zero. Verify requested vs returned pairs. Do not equate query spend with entire campaign spend (recommendations and coverage differ).
5. Join active/excluded states and product facts: title, description, characteristics, images where relevant. Broad terms are not automatically irrelevant; cross-use can be valid. Preserve exact phrase strings in proposed writes.
6. FIRST apply >=100 query impressions eligibility gate, THEN semantic/performance evaluation. Lower-volume phrases remain monitor-only, including obviously suspicious ones. Report confirmed mismatch vs uncertain intent separately. Orders/ATB lag; new 1–2-day campaigns deserve observation. Never manufacture a profitable CPC/DRR target without margin/user input. Zero orders alone does not prove waste.
7. Deliver table per campaign ID: phrase, views, clicks, spend, ATB, orders, decision (exclude/keep/observe), evidence/reason. Separate semantic mismatch from expensive but relevant traffic. Export CSV plus clear summary.
8. Before mutation load `wb-seller-analytics/references/wb-advert-write-api.md`, read live exclusions again, show COMPLETE old/new minus-phrase sets, seek exact approval. Plan/apply once and read back. Never overwrite existing exclusions with only new additions. Log actual changes in tracker as source 'менеджер'.

## Implementation checks

Tests: `/opt/wb-hermes-mcp/tests/test_cluster_stats.py`. Include MCP read-only registration, strict public payload, SDK alias mapping (`from`, `to`, `advertId`, `nmId`), duplicates/empty/>100/reversed dates/string IDs rejected. Public help and docs inventory must include tool. Verify with actual live MCP, not just SDK mocks. Archived baseline of server/gateway: `/opt/wb-hermes-mcp/backup-cluster-stats-20260923/`.

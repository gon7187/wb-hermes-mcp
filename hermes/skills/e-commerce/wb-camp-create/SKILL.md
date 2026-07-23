---
name: wb-camp-create
description: Безопасная подготовка manual CPM кампаний WB с проверкой дублей.
---

# WB campaign creation

```bash
python3 /root/.hermes/scripts/wb_create_camp.py <nmId> [nmId...]
python3 /root/.hermes/scripts/wb_create_camp.py --from-detector
```

Скрипт:

1. получает карточки через `wb_list_cards`;
2. проверяет дубли среди статусов `4, 9, 11` и в локальном реестре;
3. готовит read-only payload для manual CPM с зонами `search` и
   `recommendations`;
4. сохраняет proposal в `/tmp/wb_campaign_proposals.json`.

Скрипт не создаёт MCP-план: confirmation ID хранится только в памяти живого
процесса MCP и после выхода отдельного stdio-скрипта был бы недействителен.

Покажи proposal пользователю. В живой сессии Hermes вызови
`wb_plan_update_campaign` с этим payload, покажи summary, получи явное
подтверждение и в той же MCP-сессии вызови `wb_apply_change`. После применения
перечитай кампанию. Не пополняй и не запускай автоматически.

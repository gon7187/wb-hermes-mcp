# WB advertising write paths

Все суммы пополнения задаются в рублях. Ставки `bid_kopecks` задаются в
разменных единицах: `100` означает 1 рубль.

| Задача | Инструмент |
| --- | --- |
| Создать manual CPM кампанию | `wb_plan_update_campaign`, `action=create` |
| Запустить | `wb_plan_update_campaign`, `action=start` |
| Поставить на паузу | `wb_plan_update_campaign`, `action=pause` |
| Остановить | `wb_plan_update_campaign`, `action=stop` |
| Удалить остановленную | `wb_plan_update_campaign`, `action=delete` |
| Переименовать | `wb_plan_update_campaign`, `action=rename` |
| Минимальные ставки | `wb_get_minimum_campaign_bids` |
| Изменить ставки | `wb_plan_update_bids` |
| Пополнить бюджет | `wb_plan_deposit_campaign_budget` |

## Безопасная последовательность

### Создание

1. `wb_list_campaigns` со статусами `4, 9, 11`, проверить дубли по `nm_id`.
2. `wb_plan_update_campaign`:

```json
{
  "action": "create",
  "name": "SKU_Название/23.07",
  "nm_ids": [123456789],
  "bid_type": "manual",
  "payment_type": "cpm",
  "placement_types": ["search", "recommendations"]
}
```

3. Показать confirmation ID и применить только после подтверждения в той же
   живой MCP-сессии: confirmation хранится только в памяти процесса.
4. Перечитать кампанию. Не пополнять и не запускать автоматически.

### Пополнение и запуск

1. Прочитать `wb_get_campaign_budget`.
2. Создать план пополнения с `amount >= 1000`, обычно `source_type=1`.
3. После явного подтверждения применить один раз.
4. Дождаться отражения бюджета. Задержка не является сигналом для повтора.
5. Только затем отдельно спланировать запуск.

### Пауза и удаление

Пауза допустима только после показа списка campaign ID и подтверждения.
Удалять можно только остановленную кампанию; перед применением перечитать её
статус.

# WB tool map

| Данные | Инструмент |
| --- | --- |
| Профиль продавца | `wb_get_seller_profile` |
| Карточки | `wb_list_cards` |
| Продажи/возвраты | `wb_list_sales` |
| Текущие остатки по складам WB | `wb_get_wb_warehouse_stocks` |
| Товарный отчёт остатков | `wb_get_stock_products` |
| FBS-заказы | `wb_list_orders`, `wb_list_new_orders` |
| FBS-поставки | `wb_list_supplies`, `wb_get_supply` |
| Кампании | `wb_list_campaigns`, `wb_get_campaign` |
| Статистика кампаний | `wb_get_campaign_stats` |
| Бюджет кампании | `wb_get_campaign_budget` |
| Движения рекламного бюджета | `wb_get_campaign_spend_history` |

Все бизнес-параметры передаются в `payload`. Для точной схемы вызови
`wb_describe_operation`.

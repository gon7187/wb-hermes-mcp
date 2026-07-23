"""Explicit FastMCP tools for the safe Wildberries seller workflows."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, Protocol, cast

from mcp import types as mcp_types
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    ValidationError,
    model_validator,
)

from .changes import ChangePlan, ChangeStore, ConfirmationError
from .gateway import WBError, WildberriesGateway


class Gateway(Protocol):
    """The small gateway surface used by public MCP tools."""

    def read(self, operation: str, payload: dict[str, object]) -> dict[str, object]: ...

    def write(
        self, operation: str, payload: dict[str, object]
    ) -> dict[str, object]: ...


class PayloadModel(BaseModel):
    """Reject accidental endpoint and transport fields in every MCP payload."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class EmptyPayload(PayloadModel):
    """Explicit empty payload for SDK operations without public parameters."""


class CardListSort(PayloadModel):
    ascending: StrictBool = Field(
        default=False,
        description="Сортировать карточки по дате изменения по возрастанию.",
        examples=[False],
    )


class CardListCursor(PayloadModel):
    limit: StrictInt = Field(
        default=10,
        ge=1,
        le=100,
        description="Размер страницы карточек, не более 100.",
        examples=[10],
    )
    updated_at: StrictStr | None = Field(
        default=None,
        alias="updatedAt",
        description="Курсор: дата изменения из предыдущего ответа ISO 8601.",
        examples=["2026-07-23T10:15:00Z"],
    )
    nm_id: StrictInt | None = Field(
        default=None,
        alias="nmID",
        description="Курсор: артикул WB из предыдущего ответа.",
        examples=[123456789],
    )


class CardListFilter(PayloadModel):
    with_photo: StrictInt | None = Field(
        default=None,
        alias="withPhoto",
        description="Фильтр фото: -1 любые, 1 с фото, 2 без фото.",
        examples=[-1],
    )
    text_search: StrictStr | None = Field(
        default=None,
        alias="textSearch",
        description="Поиск по артикулу продавца, WB или баркоду.",
        examples=["SKU-42"],
    )
    tag_ids: list[StrictInt] | None = Field(
        default=None,
        alias="tagIDs",
        description="ID ярлыков для фильтра карточек.",
        examples=[[12, 34]],
    )
    allowed_categories_only: StrictBool | None = Field(
        default=None,
        alias="allowedCategoriesOnly",
        description="Ограничить разрешёнными категориями.",
        examples=[True],
    )
    object_ids: list[StrictInt] | None = Field(
        default=None,
        alias="objectIDs",
        description="ID предметов WB для фильтра.",
        examples=[[105]],
    )
    brands: list[StrictStr] | None = Field(
        default=None,
        description="Бренды для фильтра.",
        examples=[["YIT"]],
    )
    imt_id: StrictInt | None = Field(
        default=None,
        alias="imtID",
        description="ID объединённой карточки для фильтра.",
        examples=[987654],
    )


class CardListSettings(PayloadModel):
    sort: CardListSort | None = Field(default=None, description="Порядок сортировки.")
    filter: CardListFilter | None = Field(default=None, description="Фильтры списка.")
    cursor: CardListCursor = Field(
        default_factory=CardListCursor,
        description="Курсор постраничной выдачи.",
    )


class ListCardsPayload(PayloadModel):
    settings: CardListSettings = Field(
        default_factory=CardListSettings,
        description="Настройки фильтра, сортировки и курсора карточек.",
    )
    locale: Literal["ru", "en", "zh"] | None = Field(
        default="ru",
        description="Язык названий и значений в ответе.",
        examples=["ru"],
    )


class CardSchemaPayload(PayloadModel):
    locale: Literal["ru", "en", "zh"] | None = Field(
        default="ru",
        description="Язык названий категорий и характеристик.",
        examples=["ru"],
    )
    subject_id: StrictInt | None = Field(
        default=None,
        description="ID предмета: при передаче возвращаются его характеристики.",
        examples=[105],
    )
    parent_id: StrictInt | None = Field(
        default=None,
        description="ID родительской категории для списка предметов.",
        examples=[694],
    )
    name: StrictStr | None = Field(
        default=None,
        description="Подстрока названия предмета для поиска.",
        examples=["Носки"],
    )
    limit: StrictInt | None = Field(
        default=None,
        ge=1,
        le=1000,
        description="Размер страницы предметов.",
        examples=[100],
    )
    offset: StrictInt | None = Field(
        default=None,
        ge=0,
        description="Смещение страницы предметов.",
        examples=[0],
    )

    @model_validator(mode="after")
    def subject_id_cannot_be_combined_with_subject_list_filters(
        self,
    ) -> CardSchemaPayload:
        if self.subject_id is not None and any(
            value is not None
            for value in (self.parent_id, self.name, self.limit, self.offset)
        ):
            raise ValueError("subject_id cannot be combined with category list filters")
        return self


class CardErrorsCursor(PayloadModel):
    limit: StrictInt = Field(
        default=100,
        ge=1,
        le=100,
        description="Количество пакетов ошибок, не более 100.",
        examples=[100],
    )
    updated_at: StrictStr | None = Field(
        default=None,
        alias="updatedAt",
        description="Дата курсора из предыдущего ответа.",
        examples=["2026-07-23T10:15:00Z"],
    )
    batch_uuid: StrictStr | None = Field(
        default=None,
        alias="batchUUID",
        description="ID последнего пакета ошибок из предыдущего ответа.",
        examples=["68f04a7b-a3cb-4f01-a1ce-3fd5c6cad011"],
    )


class CardErrorsOrder(PayloadModel):
    ascending: StrictBool = Field(
        default=True,
        description="Выдавать пакеты ошибок по возрастанию.",
        examples=[True],
    )


class CardErrorsPayload(PayloadModel):
    cursor: CardErrorsCursor = Field(default_factory=CardErrorsCursor)
    order: CardErrorsOrder = Field(default_factory=CardErrorsOrder)
    locale: Literal["ru", "en", "zh"] | None = Field(
        default="ru",
        description="Язык названий предметов в ошибках.",
        examples=["ru"],
    )


class PricesPayload(PayloadModel):
    limit: StrictInt = Field(
        default=100,
        ge=1,
        le=1000,
        description="Количество товаров с ценами на странице.",
        examples=[100],
    )
    offset: StrictInt = Field(
        default=0,
        ge=0,
        description="Смещение для пагинации цен.",
        examples=[0],
    )
    filter_nm_id: StrictInt | None = Field(
        default=None,
        description="Артикул WB для точечного поиска цены.",
        examples=[123456789],
    )


class StocksPayload(PayloadModel):
    warehouse_id: StrictInt = Field(
        description="ID склада продавца.",
        examples=[12345],
    )
    chrt_ids: list[StrictInt] = Field(
        min_length=1,
        max_length=1000,
        description="ID размеров товаров для запроса остатков.",
        examples=[[987654321]],
    )


class OrdersPayload(PayloadModel):
    limit: StrictInt = Field(
        default=100,
        ge=1,
        le=1000,
        description="Количество FBS заказов на странице.",
        examples=[100],
    )
    next: StrictInt = Field(
        default=0,
        ge=0,
        description="Курсор FBS-заказов; для первой страницы 0.",
        examples=[0],
    )
    date_from: StrictInt | None = Field(
        default=None,
        description="Начало периода UNIX timestamp UTC.",
        examples=[1_700_000_000],
    )
    date_to: StrictInt | None = Field(
        default=None,
        description="Конец периода UNIX timestamp UTC.",
        examples=[1_700_086_400],
    )

    @model_validator(mode="after")
    def dates_must_be_in_order(self) -> OrdersPayload:
        if (
            self.date_from is not None
            and self.date_to is not None
            and self.date_to < self.date_from
        ):
            raise ValueError("date_to must not precede date_from")
        return self


class OrderStickersPayload(PayloadModel):
    sticker_type: Literal["png", "svg", "zplv", "zplh"] = Field(
        alias="type",
        description="Формат стикеров: png, svg, zplv или zplh.",
        examples=["png"],
    )
    width: StrictInt = Field(
        ge=1,
        description="Ширина стикера в миллиметрах.",
        examples=[58],
    )
    height: StrictInt = Field(
        ge=1,
        description="Высота стикера в миллиметрах.",
        examples=[40],
    )
    order_ids: list[StrictInt] = Field(
        min_length=1,
        max_length=100,
        description="До 100 ID сборочных заданий для печати.",
        examples=[[12345678]],
    )


class SuppliesPayload(PayloadModel):
    limit: StrictInt = Field(
        default=100,
        ge=1,
        le=1000,
        description="Количество FBS поставок на странице.",
        examples=[100],
    )
    next: StrictInt = Field(
        default=0,
        ge=0,
        description="Курсор поставок; для первой страницы 0.",
        examples=[0],
    )


class SupplyIdPayload(PayloadModel):
    supply_id: StrictStr = Field(
        min_length=1,
        description="ID FBS поставки.",
        examples=["WB-GI-123456"],
    )


class SupplyBarcodePayload(SupplyIdPayload):
    sticker_type: Literal["png", "svg", "zplv", "zplh"] = Field(
        alias="type",
        description="Формат QR/стикера поставки.",
        examples=["png"],
    )


class CardSize(PayloadModel):
    chrt_id: StrictInt = Field(
        alias="chrtID",
        description="ID существующего размера товара.",
        examples=[987654321],
    )
    skus: list[StrictStr] = Field(
        min_length=1,
        description="Баркоды этого размера.",
        examples=[["2000000000012"]],
    )
    tech_size: StrictStr | None = Field(
        default=None,
        alias="techSize",
        description="Технический размер, например XL.",
        examples=["XL"],
    )
    wb_size: StrictStr | None = Field(
        default=None,
        alias="wbSize",
        description="Российский размер товара.",
        examples=["50"],
    )
    price: StrictInt | None = Field(
        default=None,
        ge=0,
        description="Цена для добавляемого размера в рублях.",
        examples=[999],
    )


class CardDimensions(PayloadModel):
    length: StrictInt | None = Field(default=None, ge=1, description="Длина, см.")
    width: StrictInt | None = Field(default=None, ge=1, description="Ширина, см.")
    height: StrictInt | None = Field(default=None, ge=1, description="Высота, см.")
    weight_brutto: StrictFloat | StrictInt | None = Field(
        default=None,
        alias="weightBrutto",
        ge=0,
        description="Вес с упаковкой, кг.",
        examples=[0.25],
    )


class CardCharacteristic(PayloadModel):
    id: StrictInt = Field(description="ID характеристики.", examples=[12])
    value: StrictStr | StrictInt | StrictFloat | list[StrictStr] = Field(
        description="Значение характеристики согласно её типу.",
        examples=[["хлопок"]],
    )


class CardUpdate(PayloadModel):
    nm_id: StrictInt = Field(
        alias="nmID", description="Артикул WB.", examples=[123456789]
    )
    vendor_code: StrictStr = Field(
        alias="vendorCode",
        min_length=1,
        description="Артикул продавца.",
        examples=["SKU-42"],
    )
    sizes: list[CardSize] = Field(
        min_length=1,
        description="Размеры и баркоды карточки, обязательные для API обновления.",
    )
    kiz_marked: StrictBool | None = Field(
        default=None,
        alias="kizMarked",
        description="Передавайте true только для явного подтверждения маркировки.",
        examples=[True],
    )
    brand: StrictStr | None = Field(
        default=None, description="Бренд.", examples=["YIT"]
    )
    title: StrictStr | None = Field(
        default=None,
        max_length=60,
        description="Новое название товара, максимум 60 символов.",
        examples=["Носки хлопковые"],
    )
    description: StrictStr | None = Field(
        default=None,
        description="Новое описание товара.",
        examples=["Хлопковые носки для повседневной носки."],
    )
    dimensions: CardDimensions | None = Field(
        default=None, description="Габариты с упаковкой."
    )
    characteristics: list[CardCharacteristic] | None = Field(
        default=None,
        description="Характеристики по схеме предмета.",
    )


class UpdateCardsPayload(PayloadModel):
    cards: list[CardUpdate] = Field(
        min_length=1,
        max_length=3000,
        description="Карточки для обновления; API требует nmID, vendorCode и sizes.",
    )


class SaveMediaPayload(PayloadModel):
    nm_id: StrictInt = Field(
        description="Артикул WB карточки.",
        examples=[123456789],
    )
    media_urls: list[StrictStr] = Field(
        min_length=1,
        alias="mediaUrls",
        description=(
            "Полный упорядоченный список URL изображений/видео. Он заменит все "
            "существующие медиа карточки."
        ),
        examples=[["https://cdn.example.invalid/card-1.jpg"]],
    )


class PriceItem(PayloadModel):
    nm_id: StrictInt = Field(
        alias="nmID", description="Артикул WB.", examples=[123456789]
    )
    price: StrictInt | None = Field(
        default=None,
        ge=0,
        description="Новая цена в рублях.",
        examples=[999],
    )
    discount: StrictInt | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Новая скидка, проценты.",
        examples=[10],
    )

    @model_validator(mode="after")
    def price_or_discount_is_required(self) -> PriceItem:
        if self.price is None and self.discount is None:
            raise ValueError("price or discount is required")
        return self


class SetPricesPayload(PayloadModel):
    items: list[PriceItem] = Field(
        max_length=1000,
        description="До 1000 цен или скидок; пустой список допустим для dry confirmation flow.",
        examples=[[{"nmID": 123456789, "price": 999, "discount": 10}]],
    )


class StockItem(PayloadModel):
    chrt_id: StrictInt = Field(
        alias="chrtId", description="ID размера.", examples=[987654321]
    )
    amount: StrictInt = Field(
        ge=0,
        le=100000,
        description="Новый остаток размера.",
        examples=[10],
    )


class SetStocksPayload(PayloadModel):
    warehouse_id: StrictInt = Field(description="ID склада продавца.", examples=[12345])
    stocks: list[StockItem] = Field(
        min_length=1,
        max_length=1000,
        description="Остатки по размерам для записи.",
        examples=[[{"chrtId": 987654321, "amount": 10}]],
    )


class ManageWarehousePayload(PayloadModel):
    action: Literal["create", "update", "delete"] = Field(
        description="Операция со складом: create, update или delete.",
        examples=["update"],
    )
    warehouse_id: StrictInt | None = Field(
        default=None,
        description="ID существующего склада для update/delete.",
        examples=[12345],
    )
    name: StrictStr | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        description="Название склада для create/update.",
        examples=["Склад Коледино"],
    )
    office_id: StrictInt | None = Field(
        default=None,
        ge=1,
        description="ID склада WB для create/update.",
        examples=[15],
    )

    @model_validator(mode="after")
    def require_fields_for_selected_action(self) -> ManageWarehousePayload:
        if self.action == "create" and (self.name is None or self.office_id is None):
            raise ValueError("create requires name and office_id")
        if self.action == "update" and (
            self.warehouse_id is None or self.name is None or self.office_id is None
        ):
            raise ValueError("update requires warehouse_id, name and office_id")
        if self.action == "delete" and self.warehouse_id is None:
            raise ValueError("delete requires warehouse_id")
        return self


class OrderStatusesPayload(PayloadModel):
    order_ids: list[StrictInt] = Field(
        min_length=1,
        max_length=1000,
        description="ID FBS сборочных заданий для получения их текущих статусов.",
        examples=[[12345678]],
    )


class CancelOrderPayload(PayloadModel):
    order_id: StrictInt = Field(
        description="ID отменяемого FBS сборочного задания.",
        examples=[12345678],
    )


class CreateSupplyPayload(PayloadModel):
    name: StrictStr = Field(
        min_length=1,
        max_length=128,
        description="Название новой FBS поставки.",
        examples=["Поставка 2026-07-23"],
    )


class UpdateSupplyPayload(PayloadModel):
    action: Literal["attach_orders", "deliver", "delete"] = Field(
        description=(
            "Допустимое действие: attach_orders добавляет/перемещает заказы; "
            "deliver необратимо переводит поставку в доставку; delete удаляет поставку."
        ),
        examples=["attach_orders"],
    )
    supply_id: StrictStr = Field(
        min_length=1,
        description="ID FBS поставки.",
        examples=["WB-GI-123456"],
    )
    order_ids: list[StrictInt] | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="ID заказов только для action=attach_orders.",
        examples=[[12345678]],
    )

    @model_validator(mode="after")
    def require_orders_only_when_attaching(self) -> UpdateSupplyPayload:
        if self.action == "attach_orders" and not self.order_ids:
            raise ValueError("attach_orders requires order_ids")
        if self.action != "attach_orders" and self.order_ids is not None:
            raise ValueError("order_ids are only valid for attach_orders")
        return self


class ApplyChangeInput(PayloadModel):
    confirmation_id: StrictStr = Field(
        description="Одноразовый ID подтверждаемого плана.",
        examples=["f0f4b2d2-6b4b-4cc4-8df2-f8bd8416dc3a"],
    )


class TariffsPayload(PayloadModel):
    kind: Literal["commission", "box", "pallet", "return", "acceptance"] = Field(
        default="commission",
        description="Тип тарифа: комиссия, короб, паллета, возврат или коэффициенты приёмки.",
        examples=["commission"],
    )
    locale: Literal["ru", "en", "zh"] | None = Field(
        default="ru",
        description="Язык комиссионного тарифа.",
    )
    date: StrictStr | None = Field(
        default=None,
        description="Дата YYYY-MM-DD для тарифов box/pallet/return.",
        examples=["2026-07-23"],
    )
    warehouse_ids: list[StrictInt] | None = Field(
        default=None,
        max_length=50,
        description="ID складов только для kind=acceptance.",
    )

    @model_validator(mode="after")
    def require_valid_tariff_filter(self) -> TariffsPayload:
        if self.kind in {"box", "pallet", "return"} and not self.date:
            raise ValueError("date is required for the selected tariff kind")
        if self.kind != "acceptance" and self.warehouse_ids is not None:
            raise ValueError("warehouse_ids are only valid for acceptance tariffs")
        return self


class CampaignListPayload(PayloadModel):
    campaign_ids: list[StrictInt] | None = Field(
        default=None,
        min_length=1,
        max_length=50,
        description="До 50 ID кампаний для точечной выборки.",
    )
    statuses: list[StrictInt] | None = Field(
        default=None,
        min_length=1,
        max_length=6,
        description="Фильтр статусов кампаний WB.",
    )
    payment_type: Literal["cpm", "cpc"] | None = Field(
        default=None,
        description="Фильтр типа оплаты кампаний.",
    )


class CampaignIdPayload(PayloadModel):
    campaign_id: StrictInt = Field(description="ID кампании WB.", examples=[123456])


class CampaignStatsPayload(PayloadModel):
    campaign_ids: list[StrictInt] = Field(
        min_length=1,
        max_length=50,
        description="До 50 ID кампаний.",
        examples=[[123456]],
    )
    date_from: date = Field(
        description="Начало периода статистики.", examples=["2026-07-01"]
    )
    date_to: date = Field(
        description="Конец периода статистики.", examples=["2026-07-02"]
    )

    @model_validator(mode="after")
    def check_period(self) -> CampaignStatsPayload:
        if self.date_from > self.date_to:
            raise ValueError("date_from must not be after date_to")
        return self


class CampaignBidsPayload(CampaignIdPayload):
    nm_id: StrictInt = Field(description="Артикул WB в кампании.", examples=[987654321])


class MinimumCampaignBidsPayload(CampaignIdPayload):
    nm_ids: list[StrictInt] = Field(
        min_length=1,
        max_length=50,
        description="Артикулы WB, для которых нужны минимальные ставки.",
        examples=[[987654321]],
    )
    payment_type: Literal["cpm", "cpc"] = Field(
        default="cpm",
        description="Модель оплаты кампании.",
    )
    placement_types: list[Literal["search", "recommendation", "combined"]] = Field(
        min_length=1,
        max_length=3,
        description="Зоны размещения в терминологии WB minimum-bids API.",
        examples=[["search"]],
    )


class SearchClustersPayload(CampaignBidsPayload):
    """Input for normalized search clusters of one campaign product."""


class DateRangePayload(PayloadModel):
    date_from: date = Field(description="Начало периода.", examples=["2026-07-01"])
    date_to: date = Field(description="Конец периода.", examples=["2026-07-02"])

    @model_validator(mode="after")
    def check_date_range(self) -> DateRangePayload:
        if self.date_from > self.date_to:
            raise ValueError("date_from must not be after date_to")
        return self


class NmDateRangePayload(DateRangePayload):
    nm_ids: list[StrictInt] = Field(
        min_length=1,
        max_length=1000,
        description="Артикулы WB для фильтра аналитики.",
        examples=[[987654321]],
    )


class SearchQueriesPayload(NmDateRangePayload):
    limit: StrictInt = Field(default=100, ge=1, le=1000, description="Размер страницы.")
    offset: StrictInt = Field(default=0, ge=0, description="Смещение страницы.")


class StockAnalyticsPayload(NmDateRangePayload):
    stock_type: Literal["", "wb", "mp"] = Field(
        default="",
        description="Тип остатков: все, WB или продавец.",
    )


class SalesPayload(PayloadModel):
    date_from: StrictStr = Field(
        min_length=10,
        description="Дата или дата-время RFC3339, начиная с которой вернуть продажи.",
        examples=["2026-07-01T00:00:00"],
    )
    flag: Literal[0, 1] = Field(
        default=0,
        description="0 — изменения с date_from, 1 — продажи ровно за указанную дату.",
    )


class StockProductsPayload(DateRangePayload):
    nm_ids: list[StrictInt] | None = Field(
        default=None,
        max_length=1000,
        description="Необязательный фильтр по артикулам WB.",
    )
    subject_id: StrictInt | None = Field(default=None)
    brand_name: StrictStr | None = Field(default=None)
    tag_id: StrictInt | None = Field(default=None)
    stock_type: Literal["", "wb", "mp"] = Field(default="")
    skip_deleted_nm: StrictBool = Field(default=True)
    order_field: Literal[
        "ordersCount",
        "ordersSum",
        "avgOrders",
        "buyoutCount",
        "buyoutSum",
        "buyoutPercent",
        "stockCount",
        "stockSum",
        "saleRate",
        "avgStockTurnover",
        "toClientCount",
        "fromClientCount",
        "minPrice",
        "maxPrice",
        "officeMissingTime",
        "lostOrdersCount",
        "lostOrdersSum",
        "lostBuyoutsCount",
        "lostBuyoutsSum",
    ] = Field(default="stockCount")
    order_mode: Literal["asc", "desc"] = Field(default="asc")
    availability_filters: list[
        Literal[
            "deficient",
            "actual",
            "balanced",
            "nonActual",
            "nonLiquid",
            "invalidData",
        ]
    ] = Field(default_factory=list)
    limit: StrictInt = Field(default=1000, ge=1, le=1000)
    offset: StrictInt = Field(default=0, ge=0)


class WbWarehouseStocksPayload(PayloadModel):
    nm_ids: list[StrictInt] | None = Field(default=None, max_length=1000)
    chrt_ids: list[StrictInt] | None = Field(default=None)
    limit: StrictInt = Field(default=250_000, ge=1, le=250_000)
    offset: StrictInt = Field(default=0, ge=0)


class ReportStatusPayload(PayloadModel):
    download_ids: list[StrictStr] | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="UUID сформированных аналитических отчётов для точечной проверки.",
    )


class FinancialDocumentsPayload(PayloadModel):
    locale: Literal["ru", "en", "zh"] | None = Field(default="ru")
    begin_date: date | None = Field(
        default=None, description="Начало периода документов."
    )
    end_date: date | None = Field(default=None, description="Конец периода документов.")
    sort: Literal["date", "category"] | None = Field(default=None)
    order: Literal["asc", "desc"] | None = Field(default=None)
    category: StrictStr | None = Field(default=None)
    limit: StrictInt | None = Field(default=50, ge=1, le=50)
    offset: StrictInt | None = Field(default=0, ge=0)

    @model_validator(mode="after")
    def check_document_filters(self) -> FinancialDocumentsPayload:
        if (self.begin_date is None) != (self.end_date is None):
            raise ValueError("begin_date and end_date must be supplied together")
        if (self.sort is None) != (self.order is None):
            raise ValueError("sort and order must be supplied together")
        if self.begin_date and self.end_date and self.begin_date > self.end_date:
            raise ValueError("begin_date must not be after end_date")
        return self


class CommunicationListPayload(PayloadModel):
    is_answered: StrictBool = Field(
        default=False, description="Получить отвеченные или неотвеченные записи."
    )
    take: StrictInt = Field(default=100, ge=1, le=5000, description="Размер страницы.")
    skip: StrictInt = Field(default=0, ge=0, description="Смещение страницы.")
    nm_id: StrictInt | None = Field(default=None, description="Фильтр по артикулу WB.")
    order: Literal["dateAsc", "dateDesc"] | None = Field(default="dateDesc")
    date_from: StrictInt | None = Field(
        default=None, ge=0, description="Unix timestamp начала периода."
    )
    date_to: StrictInt | None = Field(
        default=None, ge=0, description="Unix timestamp конца периода."
    )

    @model_validator(mode="after")
    def check_communication_dates(self) -> CommunicationListPayload:
        if (
            self.date_from is not None
            and self.date_to is not None
            and self.date_from > self.date_to
        ):
            raise ValueError("date_from must not be after date_to")
        return self


class ChatEventsPayload(PayloadModel):
    next: StrictInt | None = Field(
        default=None,
        ge=0,
        description="Unix timestamp в миллисекундах для следующего пакета событий.",
    )


class CampaignUpdatePayload(PayloadModel):
    action: Literal["create", "start", "pause", "stop", "delete", "rename"] = Field(
        description=(
            "Действие над кампанией: создание, запуск, пауза, остановка, удаление "
            "остановленной кампании или переименование."
        ),
        examples=["pause"],
    )
    campaign_id: StrictInt | None = Field(
        default=None, description="ID существующей кампании."
    )
    name: StrictStr | None = Field(default=None, min_length=1, max_length=100)
    nm_ids: list[StrictInt] | None = Field(default=None, min_length=1, max_length=50)
    bid_type: Literal["manual", "unified"] = Field(default="manual")
    payment_type: Literal["cpm", "cpc"] = Field(default="cpm")
    placement_types: list[Literal["search", "recommendations"]] | None = Field(
        default=None,
        min_length=1,
        max_length=2,
    )

    @model_validator(mode="after")
    def check_campaign_action(self) -> CampaignUpdatePayload:
        if self.action == "create":
            if not self.name:
                raise ValueError("name is required for campaign creation")
            if self.campaign_id is not None:
                raise ValueError("campaign_id is not valid for campaign creation")
            return self
        if self.campaign_id is None:
            raise ValueError("campaign_id is required for this campaign action")
        if self.action == "rename" and not self.name:
            raise ValueError("name is required for campaign rename")
        if self.action != "rename" and any(
            value is not None
            for value in (self.name, self.nm_ids, self.placement_types)
        ):
            raise ValueError(
                "extra campaign fields are only valid for create or rename"
            )
        return self


class CampaignBid(PayloadModel):
    nm_id: StrictInt = Field(description="Артикул WB.")
    bid_kopecks: StrictInt = Field(ge=0, description="Ставка в копейках.")
    placement: Literal["search", "recommendations", "combined"] = Field(
        description="Место показа ставки."
    )


class UpdateBidsPayload(CampaignIdPayload):
    bids: list[CampaignBid] = Field(
        min_length=1, max_length=100, description="Новые ставки товаров."
    )


class MinusPhrasesPayload(CampaignBidsPayload):
    phrases: list[StrictStr] = Field(
        max_length=1000,
        description="Минус-фразы кампании; пустой список полностью очищает их.",
    )


class StartReportPayload(NmDateRangePayload):
    name: StrictStr | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Необязательное имя отчёта.",
    )


class FeedbackReplyPayload(PayloadModel):
    feedback_id: StrictStr = Field(min_length=1, description="ID отзыва.")
    text: StrictStr = Field(
        min_length=1, max_length=5000, description="Текст ответа на отзыв."
    )


class QuestionReplyPayload(PayloadModel):
    question_id: StrictStr = Field(min_length=1, description="ID вопроса.")
    text: StrictStr = Field(
        min_length=1, max_length=5000, description="Текст ответа на вопрос."
    )


class ChatMessagePayload(PayloadModel):
    reply_sign: StrictStr = Field(
        min_length=1,
        max_length=255,
        description="Подпись чата из списка чатов или событий.",
    )
    message: StrictStr = Field(
        min_length=1, max_length=1000, description="Текст сообщения покупателю."
    )


class CampaignBudgetDepositPayload(CampaignIdPayload):
    amount: StrictInt = Field(
        ge=1000,
        description="Сумма пополнения в рублях, не меньше 1000.",
        examples=[3000],
    )
    source_type: Literal[0, 1, 3] = Field(
        default=1,
        description="Источник: 0 — счёт, 1 — баланс, 3 — бонусы.",
    )


class DescribeOperationInput(PayloadModel):
    tool_name: StrictStr = Field(description="Имя публичного инструмента wb_*.")


READ_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)
PLAN_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)
APPLY_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=True,
)


_VALIDATION_MESSAGE = (
    "Некорректные параметры инструмента. Проверьте структуру и обязательные поля."
)


def _validation_error() -> dict[str, object]:
    return {
        "ok": False,
        "error": {
            "kind": "validation_error",
            "message": _VALIDATION_MESSAGE,
            "retryable": False,
        },
    }


def _execution_error() -> dict[str, object]:
    return {
        "ok": False,
        "error": {
            "kind": "tool_error",
            "message": "Инструмент не удалось выполнить безопасно.",
            "retryable": False,
        },
    }


def _safe_call_result(error: dict[str, object]) -> mcp_types.CallToolResult:
    return mcp_types.CallToolResult(
        content=[
            mcp_types.TextContent(
                type="text",
                text=json.dumps(error, ensure_ascii=False),
            )
        ],
        structuredContent=error,
        isError=True,
    )


@dataclass(frozen=True)
class ToolInputSpec:
    allowed_root_fields: frozenset[str]
    required_root_fields: frozenset[str]
    schema: dict[str, Any]
    model: type[PayloadModel]
    payload_wrapped: bool
    payload_optional: bool


def _payload_input_schema(
    model: type[PayloadModel], *, required: bool
) -> dict[str, Any]:
    payload_schema = model.model_json_schema(by_alias=True)
    definitions = payload_schema.pop("$defs", None)
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {"payload": payload_schema},
        "additionalProperties": False,
    }
    if required:
        schema["required"] = ["payload"]
    if definitions:
        schema["$defs"] = definitions
    return schema


class SafeFastMCP(FastMCP):
    """FastMCP with an explicit raw-input boundary before Pydantic dispatch."""

    def __init__(self, name: str) -> None:
        self._input_specs: dict[str, ToolInputSpec] = {}
        super().__init__(name)

    def register_payload_input(
        self,
        name: str,
        model: type[PayloadModel],
        *,
        required: bool,
    ) -> None:
        self._input_specs[name] = ToolInputSpec(
            allowed_root_fields=frozenset({"payload"}),
            required_root_fields=frozenset({"payload"}) if required else frozenset(),
            schema=_payload_input_schema(model, required=required),
            model=model,
            payload_wrapped=True,
            payload_optional=not required,
        )

    def register_root_input(self, name: str, model: type[PayloadModel]) -> None:
        schema = model.model_json_schema(by_alias=True)
        self._input_specs[name] = ToolInputSpec(
            allowed_root_fields=frozenset(model.model_fields),
            required_root_fields=frozenset(
                field_name
                for field_name, field in model.model_fields.items()
                if field.is_required()
            ),
            schema=schema,
            model=model,
            payload_wrapped=False,
            payload_optional=False,
        )

    async def list_tools(self) -> list[mcp_types.Tool]:
        tools = await super().list_tools()
        return [
            tool.model_copy(update={"inputSchema": self._input_specs[tool.name].schema})
            if tool.name in self._input_specs
            else tool
            for tool in tools
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        spec = self._input_specs.get(name)
        if spec is not None and (
            any(key not in spec.allowed_root_fields for key in arguments)
            or any(key not in arguments for key in spec.required_root_fields)
        ):
            return _safe_call_result(_validation_error())
        if spec is not None and not self._valid_input(spec, arguments):
            return _safe_call_result(_validation_error())
        try:
            return await super().call_tool(name, arguments)
        except Exception:
            return _safe_call_result(_execution_error())

    @staticmethod
    def _valid_input(spec: ToolInputSpec, arguments: Mapping[str, object]) -> bool:
        try:
            if spec.payload_wrapped:
                payload = arguments.get("payload")
                if payload is None:
                    if not spec.payload_optional:
                        return False
                    spec.model()
                elif isinstance(payload, Mapping):
                    spec.model.model_validate(dict(payload))
                else:
                    return False
            else:
                spec.model.model_validate(dict(arguments))
        except ValidationError:
            return False
        return True


def _parse_payload(
    raw_payload: object,
    model: type[PayloadModel],
    *,
    optional: bool,
) -> PayloadModel | None:
    if raw_payload is None:
        return model() if optional else None
    if not isinstance(raw_payload, Mapping):
        return None
    try:
        return model.model_validate(dict(raw_payload))
    except ValidationError:
        return None


_SUMMARY_TARGET_FIELDS = (
    "nm_id",
    "nmID",
    "warehouse_id",
    "order_id",
    "supply_id",
    "campaign_id",
)
_SUMMARY_SCALAR_FIELDS = frozenset(
    {
        "action",
        "amount",
        "bid_type",
        "date_from",
        "date_to",
        "office_id",
        "payment_type",
        "stock_type",
        "type",
    }
)
_SUMMARY_ID_LIST_FIELDS = frozenset(
    {"campaign_ids", "chrt_ids", "nm_ids", "order_ids", "warehouse_ids"}
)
_SUMMARY_OBJECT_LIST_FIELDS: dict[str, tuple[str, ...]] = {
    "bids": ("nm_id", "bid_kopecks", "placement"),
    "cards": ("nmID",),
    "items": ("nmID", "price", "discount"),
    "stocks": ("chrtId", "amount"),
}
_SUMMARY_COUNT_FIELDS = {
    "mediaUrls": "media_urls_count",
    "media_urls": "media_urls_count",
    "phrases": "phrases_count",
    "placement_types": "placement_types_count",
}
_SUMMARY_TEXT_FIELDS = frozenset({"message", "name", "text"})
_SUMMARY_MAX_ITEMS = 20


def _safe_summary_scalar(value: object) -> object | None:
    if isinstance(value, date):
        return value.isoformat()
    if type(value) in (bool, int, float):
        return value
    if isinstance(value, str) and value in {
        "combined",
        "cpc",
        "cpm",
        "create",
        "delete",
        "deliver",
        "manual",
        "pause",
        "recommendations",
        "rename",
        "search",
        "start",
        "stop",
        "unified",
    }:
        return value
    return None


def _safe_summary_items(
    value: object, fields: tuple[str, ...]
) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, object]] = []
    for item in value[:_SUMMARY_MAX_ITEMS]:
        if not isinstance(item, Mapping):
            continue
        safe_item = {
            field: safe_value
            for field in fields
            if (safe_value := _safe_summary_scalar(item.get(field))) is not None
        }
        if safe_item:
            result.append(safe_item)
    return result


def _safe_plan_payload(payload: Mapping[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in payload.items():
        if key in _SUMMARY_TARGET_FIELDS:
            continue
        if key in _SUMMARY_SCALAR_FIELDS:
            safe_value = _safe_summary_scalar(value)
            if safe_value is not None:
                result[key] = safe_value
            continue
        if key in _SUMMARY_ID_LIST_FIELDS:
            if isinstance(value, list) and all(type(item) is int for item in value):
                result[key] = value[:_SUMMARY_MAX_ITEMS]
                if len(value) > _SUMMARY_MAX_ITEMS:
                    result[f"{key}_count"] = len(value)
            continue
        if key in _SUMMARY_OBJECT_LIST_FIELDS:
            if isinstance(value, list):
                result[f"{key}_count"] = len(value)
                safe_items = _safe_summary_items(
                    value, _SUMMARY_OBJECT_LIST_FIELDS[key]
                )
                if safe_items:
                    result[key] = safe_items
            continue
        if key in _SUMMARY_COUNT_FIELDS:
            if isinstance(value, list):
                result[_SUMMARY_COUNT_FIELDS[key]] = len(value)
            continue
        if key in _SUMMARY_TEXT_FIELDS and isinstance(value, str):
            result[f"{key}_length"] = len(value)
    return result


def _safe_summary_target(key: str, value: object) -> dict[str, object] | None:
    if type(value) is int:
        return {key: value}
    if key == "supply_id" and isinstance(value, str) and value.startswith("WB-"):
        return {key: value[:128]}
    return None


def _plan_summary(operation: str, payload: Mapping[str, object]) -> dict[str, object]:
    targets = [
        target
        for key in _SUMMARY_TARGET_FIELDS
        if key in payload
        if (target := _safe_summary_target(key, payload[key])) is not None
    ]
    return {
        "operation": operation,
        "targets": targets,
        "payload": _safe_plan_payload(payload),
    }


def _as_payload(model: BaseModel) -> dict[str, object]:
    return cast(
        dict[str, object],
        model.model_dump(mode="python", by_alias=True, exclude_none=True),
    )


def _gateway_error(error: WBError) -> dict[str, object]:
    return {"ok": False, "error": error.as_dict()}


def _confirmation_error(error: ConfirmationError) -> dict[str, object]:
    return {
        "ok": False,
        "error": {
            "kind": "confirmation_error",
            "message": str(error),
            "retryable": False,
        },
    }


def _plan_result(plan: ChangePlan) -> dict[str, object]:
    return {
        "ok": True,
        "status": "planned",
        "confirmation_id": plan.confirmation_id,
        "operation": plan.operation,
        "summary": _plan_summary(plan.operation, plan.payload),
        "expires_at": plan.expires_at.isoformat(),
        "message": "Изменение не выполнено. Подтвердите его инструментом wb_apply_change.",
    }


_PUBLIC_OPERATION_HELP: dict[str, dict[str, object]] = {
    "wb_get_seller_profile": {
        "description": "Возвращает профиль текущего продавца WB.",
        "required_payload_keys": [],
        "example": {},
        "mutation": False,
        "plan_then_apply": False,
    },
    "wb_get_tariffs": {
        "description": "Возвращает выбранный тариф или коэффициенты приёмки WB.",
        "required_payload_keys": [],
        "example": {"payload": {"kind": "commission"}},
        "mutation": False,
        "plan_then_apply": False,
    },
    "wb_list_campaigns": {
        "description": "Возвращает кампании продвижения с необязательными фильтрами.",
        "required_payload_keys": [],
        "example": {"payload": {"statuses": [9]}},
        "mutation": False,
        "plan_then_apply": False,
    },
    "wb_get_campaign_counts": {
        "description": "Возвращает кампании, сгруппированные WB по статусу и типу.",
        "required_payload_keys": [],
        "example": {},
        "mutation": False,
        "plan_then_apply": False,
    },
    "wb_get_campaign": {
        "description": "Возвращает данные одной кампании по её ID.",
        "required_payload_keys": ["campaign_id"],
        "example": {"payload": {"campaign_id": 123456}},
        "mutation": False,
        "plan_then_apply": False,
    },
    "wb_get_campaign_stats": {
        "description": "Возвращает статистику кампаний за указанный период.",
        "required_payload_keys": ["campaign_ids", "date_from", "date_to"],
        "example": {
            "payload": {
                "campaign_ids": [123456],
                "date_from": "2026-07-01",
                "date_to": "2026-07-02",
            }
        },
        "mutation": False,
        "plan_then_apply": False,
    },
    "wb_get_campaign_bids": {
        "description": "Возвращает рекомендуемые ставки товара в кампании.",
        "required_payload_keys": ["campaign_id", "nm_id"],
        "example": {"payload": {"campaign_id": 123456, "nm_id": 987654321}},
        "mutation": False,
        "plan_then_apply": False,
    },
    "wb_get_minimum_campaign_bids": {
        "description": "Возвращает минимальные ставки товаров по зонам размещения.",
        "required_payload_keys": [
            "campaign_id",
            "nm_ids",
            "placement_types",
        ],
        "example": {
            "payload": {
                "campaign_id": 123456,
                "nm_ids": [987654321],
                "payment_type": "cpm",
                "placement_types": ["search"],
            }
        },
        "mutation": False,
        "plan_then_apply": False,
    },
    "wb_get_campaign_budget": {
        "description": "Возвращает текущий бюджет кампании.",
        "required_payload_keys": ["campaign_id"],
        "example": {"payload": {"campaign_id": 123456}},
        "mutation": False,
        "plan_then_apply": False,
    },
    "wb_get_campaign_spend_history": {
        "description": "Возвращает историю списаний и пополнений рекламного бюджета.",
        "required_payload_keys": ["date_from", "date_to"],
        "example": {
            "payload": {
                "date_from": "2026-07-01",
                "date_to": "2026-07-02",
            }
        },
        "mutation": False,
        "plan_then_apply": False,
    },
    "wb_get_search_clusters": {
        "description": "Возвращает нормализованные поисковые кластеры товара в кампании.",
        "required_payload_keys": ["campaign_id", "nm_id"],
        "example": {"payload": {"campaign_id": 123456, "nm_id": 987654321}},
        "mutation": False,
        "plan_then_apply": False,
    },
    "wb_get_sales_funnel": {
        "description": "Возвращает воронку продаж по выбранным товарам и датам.",
        "required_payload_keys": ["nm_ids", "date_from", "date_to"],
        "example": {
            "payload": {
                "nm_ids": [987654321],
                "date_from": "2026-07-01",
                "date_to": "2026-07-02",
            }
        },
        "mutation": False,
        "plan_then_apply": False,
    },
    "wb_list_sales": {
        "description": "Возвращает продажи и возвраты продавца начиная с даты-времени.",
        "required_payload_keys": ["date_from"],
        "example": {"payload": {"date_from": "2026-07-01T00:00:00", "flag": 0}},
        "mutation": False,
        "plan_then_apply": False,
    },
    "wb_get_search_queries": {
        "description": "Возвращает поисковую аналитику товаров за период.",
        "required_payload_keys": ["nm_ids", "date_from", "date_to"],
        "example": {
            "payload": {
                "nm_ids": [987654321],
                "date_from": "2026-07-01",
                "date_to": "2026-07-02",
            }
        },
        "mutation": False,
        "plan_then_apply": False,
    },
    "wb_get_stock_analytics": {
        "description": "Возвращает аналитику остатков товаров за период.",
        "required_payload_keys": ["nm_ids", "date_from", "date_to"],
        "example": {
            "payload": {
                "nm_ids": [987654321],
                "date_from": "2026-07-01",
                "date_to": "2026-07-02",
            }
        },
        "mutation": False,
        "plan_then_apply": False,
    },
    "wb_get_stock_products": {
        "description": "Возвращает постраничный товарный отчёт об остатках за период.",
        "required_payload_keys": ["date_from", "date_to"],
        "example": {
            "payload": {
                "date_from": "2026-07-01",
                "date_to": "2026-07-02",
                "limit": 1000,
                "offset": 0,
            }
        },
        "mutation": False,
        "plan_then_apply": False,
    },
    "wb_get_wb_warehouse_stocks": {
        "description": "Возвращает текущие остатки по товарам, размерам и складам WB.",
        "required_payload_keys": [],
        "example": {"payload": {"limit": 250000, "offset": 0}},
        "mutation": False,
        "plan_then_apply": False,
    },
    "wb_get_report_status": {
        "description": "Возвращает статусы сформированных аналитических отчётов.",
        "required_payload_keys": [],
        "example": {},
        "mutation": False,
        "plan_then_apply": False,
    },
    "wb_get_balance": {
        "description": "Возвращает баланс финансового аккаунта продавца.",
        "required_payload_keys": [],
        "example": {},
        "mutation": False,
        "plan_then_apply": False,
    },
    "wb_list_financial_documents": {
        "description": "Возвращает финансовые документы с фильтрами периода и категории.",
        "required_payload_keys": [],
        "example": {"payload": {"limit": 50, "offset": 0}},
        "mutation": False,
        "plan_then_apply": False,
    },
    "wb_list_feedbacks": {
        "description": "Возвращает отзывы покупателей с фильтром по обработанности.",
        "required_payload_keys": [],
        "example": {"payload": {"is_answered": False, "take": 100, "skip": 0}},
        "mutation": False,
        "plan_then_apply": False,
    },
    "wb_list_questions": {
        "description": "Возвращает вопросы покупателей с фильтром по обработанности.",
        "required_payload_keys": [],
        "example": {"payload": {"is_answered": False, "take": 100, "skip": 0}},
        "mutation": False,
        "plan_then_apply": False,
    },
    "wb_list_chats": {
        "description": "Возвращает доступные чаты с покупателями.",
        "required_payload_keys": [],
        "example": {},
        "mutation": False,
        "plan_then_apply": False,
    },
    "wb_list_chat_events": {
        "description": "Возвращает новые события чатов с покупателями.",
        "required_payload_keys": [],
        "example": {},
        "mutation": False,
        "plan_then_apply": False,
    },
    "wb_plan_update_campaign": {
        "description": (
            "Создаёт план создания, запуска, паузы, остановки, удаления "
            "или переименования кампании."
        ),
        "required_payload_keys": ["action"],
        "example": {"payload": {"action": "pause", "campaign_id": 123456}},
        "mutation": True,
        "plan_then_apply": True,
    },
    "wb_plan_update_bids": {
        "description": "Создаёт план изменения ставок кампании в копейках.",
        "required_payload_keys": ["campaign_id", "bids"],
        "example": {
            "payload": {
                "campaign_id": 123456,
                "bids": [
                    {"nm_id": 987654321, "bid_kopecks": 10000, "placement": "search"}
                ],
            }
        },
        "mutation": True,
        "plan_then_apply": True,
    },
    "wb_plan_update_minus_phrases": {
        "description": (
            "Создаёт план полной установки минус-фраз товара в кампании; "
            "пустой список очищает их все."
        ),
        "required_payload_keys": ["campaign_id", "nm_id", "phrases"],
        "example": {
            "payload": {
                "campaign_id": 123456,
                "nm_id": 987654321,
                "phrases": ["нецелевой запрос"],
            }
        },
        "mutation": True,
        "plan_then_apply": True,
    },
    "wb_plan_start_report": {
        "description": "Создаёт план запуска выгрузки отчёта воронки продаж.",
        "required_payload_keys": ["nm_ids", "date_from", "date_to"],
        "example": {
            "payload": {
                "nm_ids": [987654321],
                "date_from": "2026-07-01",
                "date_to": "2026-07-02",
            }
        },
        "mutation": True,
        "plan_then_apply": True,
    },
    "wb_plan_reply_feedback": {
        "description": "Создаёт план отправки ответа на отзыв покупателя.",
        "required_payload_keys": ["feedback_id", "text"],
        "example": {
            "payload": {"feedback_id": "feedback-id", "text": "Спасибо за отзыв"}
        },
        "mutation": True,
        "plan_then_apply": True,
    },
    "wb_plan_reply_question": {
        "description": "Создаёт план ответа на вопрос покупателя.",
        "required_payload_keys": ["question_id", "text"],
        "example": {
            "payload": {"question_id": "question-id", "text": "Да, есть в наличии"}
        },
        "mutation": True,
        "plan_then_apply": True,
    },
    "wb_plan_send_chat_message": {
        "description": "Создаёт план отправки текстового сообщения покупателю в чат.",
        "required_payload_keys": ["reply_sign", "message"],
        "example": {"payload": {"reply_sign": "chat-sign", "message": "Здравствуйте"}},
        "mutation": True,
        "plan_then_apply": True,
    },
    "wb_plan_deposit_campaign_budget": {
        "description": "Создаёт план пополнения бюджета кампании в рублях.",
        "required_payload_keys": ["campaign_id", "amount"],
        "example": {
            "payload": {
                "campaign_id": 123456,
                "amount": 3000,
                "source_type": 1,
            }
        },
        "mutation": True,
        "plan_then_apply": True,
    },
}


def _public_help(
    description: str,
    required_payload_keys: list[str],
    example: dict[str, object],
    *,
    mutation: bool = False,
) -> dict[str, object]:
    return {
        "description": description,
        "required_payload_keys": required_payload_keys,
        "example": example,
        "mutation": mutation,
        "plan_then_apply": mutation,
    }


_PUBLIC_OPERATION_HELP.update(
    {
        "wb_list_cards": _public_help(
            "Возвращает постраничный список карточек товара.",
            [],
            {"payload": {"settings": {"cursor": {"limit": 10}}}},
        ),
        "wb_get_card_schema": _public_help(
            "Возвращает категории, предметы или характеристики карточек.",
            [],
            {"payload": {"subject_id": 105}},
        ),
        "wb_list_card_errors": _public_help(
            "Возвращает постраничные ошибки карточек.",
            [],
            {"payload": {"cursor": {"limit": 100}}},
        ),
        "wb_list_tags": _public_help("Возвращает ярлыки карточек продавца.", [], {}),
        "wb_list_prices": _public_help(
            "Возвращает цены и скидки товаров.",
            [],
            {"payload": {"limit": 100, "offset": 0}},
        ),
        "wb_get_stocks": _public_help(
            "Возвращает остатки выбранных размеров на складе продавца.",
            ["warehouse_id", "chrt_ids"],
            {"payload": {"warehouse_id": 12345, "chrt_ids": [123456]}},
        ),
        "wb_list_warehouses": _public_help("Возвращает склады продавца.", [], {}),
        "wb_list_orders": _public_help(
            "Возвращает постраничные FBS-заказы.",
            [],
            {"payload": {"limit": 100, "next": 0}},
        ),
        "wb_list_new_orders": _public_help(
            "Возвращает список новых FBS-заказов.", [], {}
        ),
        "wb_get_order_statuses": _public_help(
            "Возвращает текущие статусы FBS-заказов.",
            ["order_ids"],
            {"payload": {"order_ids": [12345678]}},
        ),
        "wb_get_order_stickers": _public_help(
            "Генерирует стикеры FBS-заказов.",
            ["type", "width", "height", "order_ids"],
            {
                "payload": {
                    "type": "png",
                    "width": 58,
                    "height": 40,
                    "order_ids": [12345678],
                }
            },
        ),
        "wb_list_supplies": _public_help(
            "Возвращает постраничные FBS-поставки.",
            [],
            {"payload": {"limit": 100, "next": 0}},
        ),
        "wb_get_supply": _public_help(
            "Возвращает одну FBS-поставку.",
            ["supply_id"],
            {"payload": {"supply_id": "WB-GI-123456"}},
        ),
        "wb_get_supply_barcode": _public_help(
            "Возвращает стикер FBS-поставки.",
            ["supply_id", "type"],
            {"payload": {"supply_id": "WB-GI-123456", "type": "png"}},
        ),
        "wb_plan_update_cards": _public_help(
            "Создаёт план обновления карточек.",
            ["cards"],
            {"payload": {"cards": [{"nmID": 987654321}]}},
            mutation=True,
        ),
        "wb_plan_save_media": _public_help(
            "Создаёт план полной замены медиа карточки.",
            ["nm_id", "media_urls"],
            {
                "payload": {
                    "nm_id": 987654321,
                    "media_urls": ["https://example.invalid/image.jpg"],
                }
            },
            mutation=True,
        ),
        "wb_plan_set_prices": _public_help(
            "Создаёт план изменения цен и скидок.",
            ["items"],
            {"payload": {"items": [{"nmID": 987654321, "price": 999, "discount": 10}]}},
            mutation=True,
        ),
        "wb_plan_set_stocks": _public_help(
            "Создаёт план записи остатков на складе.",
            ["warehouse_id", "stocks"],
            {
                "payload": {
                    "warehouse_id": 12345,
                    "stocks": [{"chrtId": 123456, "amount": 10}],
                }
            },
            mutation=True,
        ),
        "wb_plan_manage_warehouse": _public_help(
            "Создаёт план создания, изменения или удаления склада.",
            ["action"],
            {"payload": {"action": "create", "name": "Основной", "office_id": 12345}},
            mutation=True,
        ),
        "wb_plan_cancel_order": _public_help(
            "Создаёт план отмены FBS-заказа.",
            ["order_id"],
            {"payload": {"order_id": 12345678}},
            mutation=True,
        ),
        "wb_plan_create_supply": _public_help(
            "Создаёт план создания FBS-поставки.",
            ["name"],
            {"payload": {"name": "Поставка 2026-07-23"}},
            mutation=True,
        ),
        "wb_plan_update_supply": _public_help(
            "Создаёт план добавления заказов, сдачи или удаления FBS-поставки.",
            ["action", "supply_id"],
            {
                "payload": {
                    "action": "attach_orders",
                    "supply_id": "WB-GI-123456",
                    "order_ids": [12345678],
                }
            },
            mutation=True,
        ),
        "wb_apply_change": _public_help(
            "Однократно применяет подтверждённый ранее план.",
            ["confirmation_id"],
            {"confirmation_id": "confirmation-id"},
            mutation=True,
        ),
        "wb_describe_operation": _public_help(
            "Возвращает публичную справку об инструменте.",
            ["tool_name"],
            {"tool_name": "wb_list_cards"},
        ),
    }
)


def _operation_help(tool_name: str) -> dict[str, object] | None:
    details = _PUBLIC_OPERATION_HELP.get(tool_name)
    if details is None:
        return None
    return {"ok": True, "tool": tool_name, **details}


def create_server(
    token: str | None = None,
    *,
    gateway: Gateway | None = None,
    change_store: ChangeStore | None = None,
) -> FastMCP:
    """Create the WB stdio MCP server without performing a network request."""

    runtime_token = token if token is not None else os.getenv("WB_API_TOKEN", "")
    wb_gateway: Gateway = (
        gateway if gateway is not None else WildberriesGateway(runtime_token)
    )
    plans = change_store if change_store is not None else ChangeStore()
    mcp = SafeFastMCP("wb_mcp")

    def read_tool(operation: str, payload: Mapping[str, object]) -> dict[str, object]:
        try:
            return wb_gateway.read(operation, dict(payload))
        except WBError as error:
            return _gateway_error(error)

    def plan_tool(operation: str, payload: Mapping[str, object]) -> dict[str, object]:
        canonical_payload = dict(payload)
        validator = getattr(wb_gateway, "validate_write", None)
        try:
            if callable(validator):
                validator(operation, canonical_payload)
            return _plan_result(plans.create(operation, canonical_payload))
        except WBError as error:
            return _gateway_error(error)

    @mcp.tool(
        name="wb_get_seller_profile",
        description="Возвращает профиль текущего продавца Wildberries.",
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_get_seller_profile(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, EmptyPayload, optional=True)
        if parsed is None:
            return _validation_error()
        return read_tool("seller_profile", _as_payload(parsed))

    @mcp.tool(
        name="wb_get_tariffs",
        description=(
            "Возвращает тариф WB: commission, box, pallet, return или acceptance. "
            "Для box/pallet/return обязательна дата YYYY-MM-DD."
        ),
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_get_tariffs(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, TariffsPayload, optional=True)
        if parsed is None:
            return _validation_error()
        tariffs = cast(TariffsPayload, parsed)
        raw = _as_payload(tariffs)
        if tariffs.kind == "commission":
            return read_tool("tariffs_commission", {"locale": raw.get("locale")})
        if tariffs.kind == "acceptance":
            return read_tool(
                "acceptance_coefficients",
                {"warehouse_ids": raw["warehouse_ids"]}
                if "warehouse_ids" in raw
                else {},
            )
        return read_tool(f"tariffs_{tariffs.kind}", {"date": raw["date"]})

    @mcp.tool(
        name="wb_list_cards",
        description=(
            "Получает постраничный список карточек WB. Передайте фильтр и курсор "
            "в payload.settings; ответ содержит следующую страницу по updatedAt/nmID."
        ),
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_list_cards(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, ListCardsPayload, optional=True)
        if parsed is None:
            return _validation_error()
        return read_tool("list_cards", _as_payload(parsed))

    @mcp.tool(
        name="wb_get_card_schema",
        description=(
            "Возвращает схему каталога WB: без фильтров — родительские категории; "
            "с parent_id/name — постраничные предметы; с subject_id — характеристики предмета."
        ),
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_get_card_schema(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, CardSchemaPayload, optional=True)
        if parsed is None:
            return _validation_error()
        card_schema = cast(CardSchemaPayload, parsed)
        raw = _as_payload(card_schema)
        if card_schema.subject_id is not None:
            selected: dict[str, object] = {"subject_id": card_schema.subject_id}
            if card_schema.locale is not None:
                selected["locale"] = card_schema.locale
            return read_tool("card_schema_characteristics", selected)
        if any(
            value is not None
            for value in (
                card_schema.parent_id,
                card_schema.name,
                card_schema.limit,
                card_schema.offset,
            )
        ):
            selected = {
                key: raw[key]
                for key in ("locale", "parent_id", "name", "limit", "offset")
                if key in raw
            }
            return read_tool("card_schema_subjects", selected)
        selected: dict[str, object] = (
            {"locale": card_schema.locale} if card_schema.locale is not None else {}
        )
        return read_tool("card_schema_parents", selected)

    @mcp.tool(
        name="wb_list_card_errors",
        description=(
            "Возвращает постраничные ошибки карточек WB. Передайте cursor.updatedAt и "
            "cursor.batchUUID из прошлого ответа для следующей страницы."
        ),
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_list_card_errors(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, CardErrorsPayload, optional=True)
        if parsed is None:
            return _validation_error()
        return read_tool("list_card_errors", _as_payload(parsed))

    @mcp.tool(
        name="wb_list_tags",
        description="Возвращает все ярлыки карточек текущего продавца WB без пагинации.",
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_list_tags(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, EmptyPayload, optional=True)
        if parsed is None:
            return _validation_error()
        return read_tool("list_tags", _as_payload(parsed))

    @mcp.tool(
        name="wb_list_prices",
        description=(
            "Возвращает постраничные цены и скидки WB. Используйте limit/offset или "
            "filter_nm_id для одного артикула WB."
        ),
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_list_prices(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, PricesPayload, optional=True)
        if parsed is None:
            return _validation_error()
        return read_tool("list_prices", _as_payload(parsed))

    @mcp.tool(
        name="wb_get_stocks",
        description=(
            "Получает остатки выбранных размеров на складе продавца WB. Нужны "
            "warehouse_id и до 1000 chrt_ids; это не общий список всех остатков."
        ),
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_get_stocks(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, StocksPayload, optional=False)
        if parsed is None:
            return _validation_error()
        return read_tool("get_stocks", _as_payload(parsed))

    @mcp.tool(
        name="wb_list_warehouses",
        description="Возвращает склады продавца WB без пагинации.",
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_list_warehouses(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, EmptyPayload, optional=True)
        if parsed is None:
            return _validation_error()
        return read_tool("list_warehouses", _as_payload(parsed))

    @mcp.tool(
        name="wb_list_orders",
        description=(
            "Возвращает постраничные FBS-заказы WB. Передайте limit, next=0 для первой "
            "страницы и при необходимости UNIX date_from/date_to в UTC."
        ),
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_list_orders(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, OrdersPayload, optional=True)
        if parsed is None:
            return _validation_error()
        return read_tool("list_orders", _as_payload(parsed))

    @mcp.tool(
        name="wb_list_new_orders",
        description=(
            "Возвращает список новых FBS-заказов WB с доступными деталями. Это не поиск "
            "одного заказа по ID; для пагинации и фильтра дат используйте wb_list_orders."
        ),
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_list_new_orders(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, EmptyPayload, optional=True)
        if parsed is None:
            return _validation_error()
        return read_tool("list_new_orders", _as_payload(parsed))

    @mcp.tool(
        name="wb_get_order_statuses",
        description=(
            "Возвращает текущие статусы до 1000 FBS-заказов WB по order_ids. "
            "Инструмент только читает статусы и не создаёт план изменения."
        ),
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_get_order_statuses(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, OrderStatusesPayload, optional=False)
        if parsed is None:
            return _validation_error()
        return read_tool("get_order_statuses", _as_payload(parsed))

    @mcp.tool(
        name="wb_get_order_stickers",
        description=(
            "Генерирует стикеры до 100 FBS-заказов WB. Передайте order_ids, формат type "
            "и размеры width/height; инструмент только читает/получает файл стикеров."
        ),
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_get_order_stickers(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, OrderStickersPayload, optional=False)
        if parsed is None:
            return _validation_error()
        return read_tool("get_order_stickers", _as_payload(parsed))

    @mcp.tool(
        name="wb_list_supplies",
        description=(
            "Возвращает постраничные FBS-поставки WB. Передайте limit и next=0 для "
            "первой страницы, затем используйте курсор из ответа."
        ),
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_list_supplies(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, SuppliesPayload, optional=True)
        if parsed is None:
            return _validation_error()
        return read_tool("list_supplies", _as_payload(parsed))

    @mcp.tool(
        name="wb_get_supply",
        description="Возвращает детали одной FBS-поставки WB по supply_id.",
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_get_supply(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, SupplyIdPayload, optional=False)
        if parsed is None:
            return _validation_error()
        return read_tool("get_supply", _as_payload(parsed))

    @mcp.tool(
        name="wb_get_supply_barcode",
        description=(
            "Возвращает QR/стикер FBS-поставки WB по supply_id и type. Стикер доступен "
            "для поставки в подходящем статусе WB."
        ),
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_get_supply_barcode(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, SupplyBarcodePayload, optional=False)
        if parsed is None:
            return _validation_error()
        return read_tool("get_supply_barcode", _as_payload(parsed))

    @mcp.tool(
        name="wb_plan_update_cards",
        description=(
            "Проверяет и создаёт подтверждаемый план обновления карточек WB. Передайте "
            "cards с nmID, vendorCode и sizes; WB не вызывается до wb_apply_change."
        ),
        annotations=PLAN_ANNOTATIONS,
        structured_output=True,
    )
    def wb_plan_update_cards(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, UpdateCardsPayload, optional=False)
        if parsed is None:
            return _validation_error()
        return plan_tool("update_cards", _as_payload(parsed))

    @mcp.tool(
        name="wb_plan_save_media",
        description=(
            "Создаёт подтверждаемый план замены медиа карточки WB. mediaUrls — полный "
            "упорядоченный список: после применения он заменит все текущие медиа."
        ),
        annotations=PLAN_ANNOTATIONS,
        structured_output=True,
    )
    def wb_plan_save_media(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, SaveMediaPayload, optional=False)
        if parsed is None:
            return _validation_error()
        return plan_tool("save_media", _as_payload(parsed))

    @mcp.tool(
        name="wb_plan_set_prices",
        description=(
            "Создаёт подтверждаемый план изменения цен и скидок WB (до 1000 items). "
            "Перед применением WB не вызывается."
        ),
        annotations=PLAN_ANNOTATIONS,
        structured_output=True,
    )
    def wb_plan_set_prices(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, SetPricesPayload, optional=False)
        if parsed is None:
            return _validation_error()
        return plan_tool("set_prices", _as_payload(parsed))

    @mcp.tool(
        name="wb_plan_set_stocks",
        description=(
            "Создаёт подтверждаемый план записи остатков WB на одном warehouse_id. "
            "Передайте stocks с chrtId и amount; WB не вызывается до подтверждения."
        ),
        annotations=PLAN_ANNOTATIONS,
        structured_output=True,
    )
    def wb_plan_set_stocks(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, SetStocksPayload, optional=False)
        if parsed is None:
            return _validation_error()
        return plan_tool("set_stocks", _as_payload(parsed))

    @mcp.tool(
        name="wb_plan_manage_warehouse",
        description=(
            "Создаёт подтверждаемый план create/update/delete склада продавца WB. "
            "Для create/update нужны name и office_id, для update/delete — warehouse_id."
        ),
        annotations=PLAN_ANNOTATIONS,
        structured_output=True,
    )
    def wb_plan_manage_warehouse(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, ManageWarehousePayload, optional=False)
        if parsed is None:
            return _validation_error()
        warehouse = cast(ManageWarehousePayload, parsed)
        raw = _as_payload(warehouse)
        if warehouse.action == "create":
            return plan_tool(
                "create_warehouse", {"name": raw["name"], "office_id": raw["office_id"]}
            )
        if warehouse.action == "update":
            return plan_tool(
                "update_warehouse",
                {
                    "warehouse_id": raw["warehouse_id"],
                    "name": raw["name"],
                    "office_id": raw["office_id"],
                },
            )
        return plan_tool("delete_warehouse", {"warehouse_id": raw["warehouse_id"]})

    @mcp.tool(
        name="wb_plan_cancel_order",
        description=(
            "Создаёт подтверждаемый план отмены одного FBS-заказа WB по order_id. "
            "WB не вызывается до wb_apply_change."
        ),
        annotations=PLAN_ANNOTATIONS,
        structured_output=True,
    )
    def wb_plan_cancel_order(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, CancelOrderPayload, optional=False)
        if parsed is None:
            return _validation_error()
        return plan_tool("cancel_order", _as_payload(parsed))

    @mcp.tool(
        name="wb_plan_create_supply",
        description=(
            "Создаёт подтверждаемый план создания FBS-поставки WB с name. WB не "
            "вызывается до wb_apply_change."
        ),
        annotations=PLAN_ANNOTATIONS,
        structured_output=True,
    )
    def wb_plan_create_supply(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, CreateSupplyPayload, optional=False)
        if parsed is None:
            return _validation_error()
        return plan_tool("create_supply", _as_payload(parsed))

    @mcp.tool(
        name="wb_plan_update_supply",
        description=(
            "Создаёт подтверждаемый план FBS-поставки WB: attach_orders добавляет "
            "заказы, deliver необратимо сдаёт поставку, delete удаляет её. "
            "Прямого безопасного обновления имени SDK не предоставляет."
        ),
        annotations=PLAN_ANNOTATIONS,
        structured_output=True,
    )
    def wb_plan_update_supply(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, UpdateSupplyPayload, optional=False)
        if parsed is None:
            return _validation_error()
        supply = cast(UpdateSupplyPayload, parsed)
        raw = _as_payload(supply)
        if supply.action == "attach_orders":
            return plan_tool(
                "attach_supply_orders",
                {"supply_id": raw["supply_id"], "order_ids": raw["order_ids"]},
            )
        if supply.action == "deliver":
            return plan_tool("deliver_supply", {"supply_id": raw["supply_id"]})
        return plan_tool("delete_supply", {"supply_id": raw["supply_id"]})

    @mcp.tool(
        name="wb_list_campaigns",
        description=(
            "Возвращает кампании продвижения WB. Можно фильтровать до 50 campaign_ids, "
            "статусами и типом оплаты."
        ),
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_list_campaigns(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, CampaignListPayload, optional=True)
        if parsed is None:
            return _validation_error()
        return read_tool("list_campaigns", _as_payload(parsed))

    @mcp.tool(
        name="wb_get_campaign_counts",
        description="Возвращает кампании WB, сгруппированные по статусу и типу.",
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_get_campaign_counts(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, EmptyPayload, optional=True)
        if parsed is None:
            return _validation_error()
        return read_tool("campaign_counts", _as_payload(parsed))

    @mcp.tool(
        name="wb_get_campaign",
        description="Возвращает данные одной кампании WB по campaign_id.",
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_get_campaign(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, CampaignIdPayload, optional=False)
        if parsed is None:
            return _validation_error()
        return read_tool("get_campaign", _as_payload(parsed))

    @mcp.tool(
        name="wb_get_campaign_stats",
        description="Возвращает дневную статистику до 50 кампаний WB за указанный период.",
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_get_campaign_stats(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, CampaignStatsPayload, optional=False)
        if parsed is None:
            return _validation_error()
        return read_tool("campaign_stats", _as_payload(parsed))

    @mcp.tool(
        name="wb_get_campaign_spend_history",
        description=(
            "Возвращает историю списаний и пополнений рекламного бюджета WB "
            "за период до 31 дня."
        ),
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_get_campaign_spend_history(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, DateRangePayload, optional=False)
        if parsed is None:
            return _validation_error()
        return read_tool("campaign_spend_history", _as_payload(parsed))

    @mcp.tool(
        name="wb_get_campaign_bids",
        description="Возвращает рекомендованные ставки одного товара в кампании WB.",
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_get_campaign_bids(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, CampaignBidsPayload, optional=False)
        if parsed is None:
            return _validation_error()
        return read_tool("campaign_bids", _as_payload(parsed))

    @mcp.tool(
        name="wb_get_minimum_campaign_bids",
        description=(
            "Возвращает минимальные ставки товаров кампании WB для выбранных "
            "зон размещения."
        ),
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_get_minimum_campaign_bids(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, MinimumCampaignBidsPayload, optional=False)
        if parsed is None:
            return _validation_error()
        return read_tool("minimum_campaign_bids", _as_payload(parsed))

    @mcp.tool(
        name="wb_get_campaign_budget",
        description="Возвращает текущий бюджет кампании WB по campaign_id.",
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_get_campaign_budget(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, CampaignIdPayload, optional=False)
        if parsed is None:
            return _validation_error()
        return read_tool("campaign_budget", _as_payload(parsed))

    @mcp.tool(
        name="wb_get_search_clusters",
        description=(
            "Возвращает нормализованные поисковые кластеры одного товара в кампании WB. "
            "Используйте результат перед изменением минус-фраз или ставок."
        ),
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_get_search_clusters(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, SearchClustersPayload, optional=False)
        if parsed is None:
            return _validation_error()
        return read_tool("search_clusters", _as_payload(parsed))

    @mcp.tool(
        name="wb_list_sales",
        description=(
            "Возвращает продажи и возвраты продавца WB начиная с даты-времени RFC3339."
        ),
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_list_sales(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, SalesPayload, optional=False)
        if parsed is None:
            return _validation_error()
        return read_tool("list_sales", _as_payload(parsed))

    @mcp.tool(
        name="wb_get_sales_funnel",
        description="Возвращает воронку продаж WB по товарам и выбранному периоду.",
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_get_sales_funnel(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, NmDateRangePayload, optional=False)
        if parsed is None:
            return _validation_error()
        return read_tool("sales_funnel", _as_payload(parsed))

    @mcp.tool(
        name="wb_get_search_queries",
        description=(
            "Возвращает поисковую аналитику WB по товарам и датам. Ответ постраничный; "
            "используйте limit и offset."
        ),
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_get_search_queries(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, SearchQueriesPayload, optional=False)
        if parsed is None:
            return _validation_error()
        return read_tool("search_queries", _as_payload(parsed))

    @mcp.tool(
        name="wb_get_stock_analytics",
        description="Возвращает аналитику остатков WB по товарам и периоду.",
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_get_stock_analytics(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, StockAnalyticsPayload, optional=False)
        if parsed is None:
            return _validation_error()
        return read_tool("stock_analytics", _as_payload(parsed))

    @mcp.tool(
        name="wb_get_stock_products",
        description=(
            "Возвращает постраничный товарный отчёт WB об остатках, заказах "
            "и оборачиваемости за период."
        ),
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_get_stock_products(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, StockProductsPayload, optional=False)
        if parsed is None:
            return _validation_error()
        return read_tool("stock_products", _as_payload(parsed))

    @mcp.tool(
        name="wb_get_wb_warehouse_stocks",
        description=(
            "Возвращает текущие остатки по товарам, размерам и складам WB; "
            "ответ поддерживает limit и offset."
        ),
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_get_wb_warehouse_stocks(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, WbWarehouseStocksPayload, optional=True)
        if parsed is None:
            return _validation_error()
        return read_tool("wb_warehouse_stocks", _as_payload(parsed))

    @mcp.tool(
        name="wb_get_report_status",
        description=(
            "Возвращает статусы асинхронных аналитических отчётов WB. Без download_ids "
            "возвращает доступные отчёты."
        ),
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_get_report_status(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, ReportStatusPayload, optional=True)
        if parsed is None:
            return _validation_error()
        return read_tool("report_status", _as_payload(parsed))

    @mcp.tool(
        name="wb_get_balance",
        description="Возвращает баланс финансового аккаунта текущего продавца WB.",
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_get_balance(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, EmptyPayload, optional=True)
        if parsed is None:
            return _validation_error()
        return read_tool("balance", _as_payload(parsed))

    @mcp.tool(
        name="wb_list_financial_documents",
        description=(
            "Возвращает финансовые документы WB. Фильтры begin_date/end_date, sort и "
            "order используются парами; limit не больше 50."
        ),
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_list_financial_documents(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, FinancialDocumentsPayload, optional=True)
        if parsed is None:
            return _validation_error()
        return read_tool("financial_documents", _as_payload(parsed))

    @mcp.tool(
        name="wb_list_feedbacks",
        description="Возвращает отзывы покупателей WB; по умолчанию неотвеченные.",
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_list_feedbacks(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, CommunicationListPayload, optional=True)
        if parsed is None:
            return _validation_error()
        return read_tool("feedbacks", _as_payload(parsed))

    @mcp.tool(
        name="wb_list_questions",
        description="Возвращает вопросы покупателей WB; по умолчанию неотвеченные.",
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_list_questions(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, CommunicationListPayload, optional=True)
        if parsed is None:
            return _validation_error()
        return read_tool("questions", _as_payload(parsed))

    @mcp.tool(
        name="wb_list_chats",
        description="Возвращает чаты текущего продавца WB с покупателями.",
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_list_chats(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, EmptyPayload, optional=True)
        if parsed is None:
            return _validation_error()
        return read_tool("chats", _as_payload(parsed))

    @mcp.tool(
        name="wb_list_chat_events",
        description=(
            "Возвращает события чатов с покупателями WB. Для следующей страницы передайте "
            "next из предыдущего ответа."
        ),
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_list_chat_events(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, ChatEventsPayload, optional=True)
        if parsed is None:
            return _validation_error()
        return read_tool("chat_events", _as_payload(parsed))

    @mcp.tool(
        name="wb_plan_update_campaign",
        description=(
            "Создаёт подтверждаемый план создания, запуска, паузы, остановки, "
            "удаления или переименования кампании WB. Для action=create по умолчанию "
            "manual CPM с размещением search/recommendations; WB не вызывается "
            "до применения."
        ),
        annotations=PLAN_ANNOTATIONS,
        structured_output=True,
    )
    def wb_plan_update_campaign(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, CampaignUpdatePayload, optional=False)
        if parsed is None:
            return _validation_error()
        campaign = cast(CampaignUpdatePayload, parsed)
        raw = _as_payload(campaign)
        if campaign.action == "create":
            return plan_tool(
                "create_campaign",
                {
                    key: raw[key]
                    for key in (
                        "name",
                        "nm_ids",
                        "bid_type",
                        "payment_type",
                        "placement_types",
                    )
                    if key in raw
                },
            )
        if campaign.action == "rename":
            return plan_tool(
                "rename_campaign",
                {"campaign_id": raw["campaign_id"], "name": raw["name"]},
            )
        return plan_tool(
            f"{campaign.action}_campaign", {"campaign_id": raw["campaign_id"]}
        )

    @mcp.tool(
        name="wb_plan_update_bids",
        description=(
            "Создаёт подтверждаемый план изменения ставок кампании WB. bid_kopecks — "
            "ставка в копейках, placement определяет зону показа."
        ),
        annotations=PLAN_ANNOTATIONS,
        structured_output=True,
    )
    def wb_plan_update_bids(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, UpdateBidsPayload, optional=False)
        if parsed is None:
            return _validation_error()
        return plan_tool("update_bids", _as_payload(parsed))

    @mcp.tool(
        name="wb_plan_update_minus_phrases",
        description=(
            "Создаёт подтверждаемый план полной установки минус-фраз одного товара в "
            "кампании WB. Пустой список очищает все минус-фразы. Перед применением "
            "сначала изучите wb_get_search_clusters."
        ),
        annotations=PLAN_ANNOTATIONS,
        structured_output=True,
    )
    def wb_plan_update_minus_phrases(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, MinusPhrasesPayload, optional=False)
        if parsed is None:
            return _validation_error()
        return plan_tool("set_minus_phrases", _as_payload(parsed))

    @mcp.tool(
        name="wb_plan_start_report",
        description=(
            "Создаёт подтверждаемый план запуска отчёта воронки продаж WB. После "
            "применения проверяйте готовность через wb_get_report_status."
        ),
        annotations=PLAN_ANNOTATIONS,
        structured_output=True,
    )
    def wb_plan_start_report(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, StartReportPayload, optional=False)
        if parsed is None:
            return _validation_error()
        return plan_tool("start_report", _as_payload(parsed))

    @mcp.tool(
        name="wb_plan_reply_feedback",
        description="Создаёт подтверждаемый план публикации ответа на отзыв покупателя WB.",
        annotations=PLAN_ANNOTATIONS,
        structured_output=True,
    )
    def wb_plan_reply_feedback(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, FeedbackReplyPayload, optional=False)
        if parsed is None:
            return _validation_error()
        return plan_tool("reply_feedback", _as_payload(parsed))

    @mcp.tool(
        name="wb_plan_reply_question",
        description="Создаёт подтверждаемый план публикации ответа на вопрос покупателя WB.",
        annotations=PLAN_ANNOTATIONS,
        structured_output=True,
    )
    def wb_plan_reply_question(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, QuestionReplyPayload, optional=False)
        if parsed is None:
            return _validation_error()
        return plan_tool("reply_question", _as_payload(parsed))

    @mcp.tool(
        name="wb_plan_send_chat_message",
        description=(
            "Создаёт подтверждаемый план отправки текстового сообщения покупателю WB. "
            "reply_sign берите из wb_list_chats или wb_list_chat_events."
        ),
        annotations=PLAN_ANNOTATIONS,
        structured_output=True,
    )
    def wb_plan_send_chat_message(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, ChatMessagePayload, optional=False)
        if parsed is None:
            return _validation_error()
        return plan_tool("send_chat_message", _as_payload(parsed))

    @mcp.tool(
        name="wb_plan_deposit_campaign_budget",
        description=(
            "Создаёт подтверждаемый финансовый план пополнения бюджета кампании WB. "
            "amount указан в рублях; перед применением проверьте wb_get_campaign_budget."
        ),
        annotations=PLAN_ANNOTATIONS,
        structured_output=True,
    )
    def wb_plan_deposit_campaign_budget(payload: object = None) -> dict[str, object]:
        parsed = _parse_payload(payload, CampaignBudgetDepositPayload, optional=False)
        if parsed is None:
            return _validation_error()
        return plan_tool("deposit_campaign_budget", _as_payload(parsed))

    @mcp.tool(
        name="wb_describe_operation",
        description=(
            "Объясняет публичный инструмент WB: обязательные ключи payload, пример и "
            "нужен ли этап plan → wb_apply_change. Не раскрывает детали SDK."
        ),
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_describe_operation(tool_name: object = None) -> dict[str, object]:
        parsed = _parse_payload(
            {"tool_name": tool_name}, DescribeOperationInput, optional=False
        )
        if parsed is None:
            return _validation_error()
        details = _operation_help(cast(DescribeOperationInput, parsed).tool_name)
        if details is not None:
            return details
        return {
            "ok": False,
            "error": {
                "kind": "unknown_tool",
                "message": "Неизвестный публичный инструмент WB.",
                "retryable": False,
            },
        }

    @mcp.tool(
        name="wb_apply_change",
        description=(
            "Однократно применяет ранее созданный план по confirmation_id. После попытки "
            "план расходуется, даже если WB вернул ошибку."
        ),
        annotations=APPLY_ANNOTATIONS,
        structured_output=True,
    )
    def wb_apply_change(confirmation_id: object = None) -> dict[str, object]:
        parsed = _parse_payload(
            {"confirmation_id": confirmation_id}, ApplyChangeInput, optional=False
        )
        if parsed is None:
            return _validation_error()
        apply_input = cast(ApplyChangeInput, parsed)
        try:
            plan = plans.consume(apply_input.confirmation_id)
        except ConfirmationError as error:
            return _confirmation_error(error)
        try:
            result = wb_gateway.write(plan.operation, plan.payload)
        except WBError as error:
            return _gateway_error(error)
        return {
            "ok": True,
            "status": "applied",
            "operation": plan.operation,
            "result": result,
        }

    mcp.register_payload_input("wb_get_seller_profile", EmptyPayload, required=False)
    mcp.register_payload_input("wb_get_tariffs", TariffsPayload, required=False)
    mcp.register_payload_input("wb_list_cards", ListCardsPayload, required=False)
    mcp.register_payload_input("wb_get_card_schema", CardSchemaPayload, required=False)
    mcp.register_payload_input("wb_list_card_errors", CardErrorsPayload, required=False)
    mcp.register_payload_input("wb_list_tags", EmptyPayload, required=False)
    mcp.register_payload_input("wb_list_prices", PricesPayload, required=False)
    mcp.register_payload_input("wb_get_stocks", StocksPayload, required=True)
    mcp.register_payload_input("wb_list_warehouses", EmptyPayload, required=False)
    mcp.register_payload_input("wb_list_orders", OrdersPayload, required=False)
    mcp.register_payload_input("wb_list_new_orders", EmptyPayload, required=False)
    mcp.register_payload_input(
        "wb_get_order_statuses", OrderStatusesPayload, required=True
    )
    mcp.register_payload_input(
        "wb_get_order_stickers", OrderStickersPayload, required=True
    )
    mcp.register_payload_input("wb_list_supplies", SuppliesPayload, required=False)
    mcp.register_payload_input("wb_get_supply", SupplyIdPayload, required=True)
    mcp.register_payload_input(
        "wb_get_supply_barcode", SupplyBarcodePayload, required=True
    )
    mcp.register_payload_input(
        "wb_plan_update_cards", UpdateCardsPayload, required=True
    )
    mcp.register_payload_input("wb_plan_save_media", SaveMediaPayload, required=True)
    mcp.register_payload_input("wb_plan_set_prices", SetPricesPayload, required=True)
    mcp.register_payload_input("wb_plan_set_stocks", SetStocksPayload, required=True)
    mcp.register_payload_input(
        "wb_plan_manage_warehouse", ManageWarehousePayload, required=True
    )
    mcp.register_payload_input(
        "wb_plan_cancel_order", CancelOrderPayload, required=True
    )
    mcp.register_payload_input(
        "wb_plan_create_supply", CreateSupplyPayload, required=True
    )
    mcp.register_payload_input(
        "wb_plan_update_supply", UpdateSupplyPayload, required=True
    )
    mcp.register_payload_input("wb_list_campaigns", CampaignListPayload, required=False)
    mcp.register_payload_input("wb_get_campaign", CampaignIdPayload, required=True)
    mcp.register_payload_input(
        "wb_get_campaign_stats", CampaignStatsPayload, required=True
    )
    mcp.register_payload_input(
        "wb_get_campaign_bids", CampaignBidsPayload, required=True
    )
    mcp.register_payload_input(
        "wb_get_campaign_budget", CampaignIdPayload, required=True
    )
    mcp.register_payload_input(
        "wb_get_search_clusters", SearchClustersPayload, required=True
    )
    mcp.register_payload_input("wb_get_sales_funnel", NmDateRangePayload, required=True)
    mcp.register_payload_input(
        "wb_get_search_queries", SearchQueriesPayload, required=True
    )
    mcp.register_payload_input(
        "wb_get_stock_analytics", StockAnalyticsPayload, required=True
    )
    mcp.register_payload_input(
        "wb_get_report_status", ReportStatusPayload, required=False
    )
    mcp.register_payload_input("wb_get_balance", EmptyPayload, required=False)
    mcp.register_payload_input(
        "wb_list_financial_documents", FinancialDocumentsPayload, required=False
    )
    mcp.register_payload_input(
        "wb_list_feedbacks", CommunicationListPayload, required=False
    )
    mcp.register_payload_input(
        "wb_list_questions", CommunicationListPayload, required=False
    )
    mcp.register_payload_input("wb_list_chats", EmptyPayload, required=False)
    mcp.register_payload_input("wb_list_chat_events", ChatEventsPayload, required=False)
    mcp.register_payload_input(
        "wb_plan_update_campaign", CampaignUpdatePayload, required=True
    )
    mcp.register_payload_input("wb_plan_update_bids", UpdateBidsPayload, required=True)
    mcp.register_payload_input(
        "wb_plan_update_minus_phrases", MinusPhrasesPayload, required=True
    )
    mcp.register_payload_input(
        "wb_plan_start_report", StartReportPayload, required=True
    )
    mcp.register_payload_input(
        "wb_plan_reply_feedback", FeedbackReplyPayload, required=True
    )
    mcp.register_payload_input(
        "wb_plan_reply_question", QuestionReplyPayload, required=True
    )
    mcp.register_payload_input(
        "wb_plan_send_chat_message", ChatMessagePayload, required=True
    )
    mcp.register_payload_input(
        "wb_plan_deposit_campaign_budget",
        CampaignBudgetDepositPayload,
        required=True,
    )
    mcp.register_root_input("wb_describe_operation", DescribeOperationInput)
    mcp.register_root_input("wb_apply_change", ApplyChangeInput)

    return mcp


def main() -> None:
    """Start the WB MCP server over standard input and output."""

    create_server().run(transport="stdio")

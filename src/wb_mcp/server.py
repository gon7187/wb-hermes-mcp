"""Explicit FastMCP tools for the safe Wildberries seller workflows."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Literal, Protocol, cast

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


class OrderDetailsPayload(PayloadModel):
    order_id: StrictInt | None = Field(
        default=None,
        description=(
            "ID сборочного задания. SDK не имеет безопасного GET по одному ID; "
            "передача ID вернёт подсказку использовать wb_list_orders."
        ),
        examples=[12345678],
    )


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


class UpdateOrderStatusPayload(PayloadModel):
    order_ids: list[StrictInt] = Field(
        min_length=1,
        max_length=1000,
        description="ID FBS сборочных заданий для перевода статуса.",
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
    idempotentHint=False,
    openWorldHint=True,
)


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
        "expires_at": plan.expires_at.isoformat(),
        "message": "Изменение не выполнено. Подтвердите его инструментом wb_apply_change.",
    }


def _unsupported_order_id() -> dict[str, object]:
    return {
        "ok": False,
        "error": {
            "kind": "validation_error",
            "message": (
                "В установленном SDK нет безопасной операции получения одного FBS "
                "заказа по order_id. Используйте wb_list_orders с курсором и датами."
            ),
            "retryable": False,
        },
    }


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
    mcp = FastMCP("wb_mcp")

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
        name="wb_list_cards",
        description=(
            "Получает постраничный список карточек WB. Передайте фильтр и курсор "
            "в payload.settings; ответ содержит следующую страницу по updatedAt/nmID."
        ),
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_list_cards(
        payload: ListCardsPayload = ListCardsPayload(),
    ) -> dict[str, object]:
        return read_tool("list_cards", _as_payload(payload))

    @mcp.tool(
        name="wb_get_card_schema",
        description=(
            "Возвращает схему каталога WB: без фильтров — родительские категории; "
            "с parent_id/name — постраничные предметы; с subject_id — характеристики предмета."
        ),
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_get_card_schema(
        payload: CardSchemaPayload = CardSchemaPayload(),
    ) -> dict[str, object]:
        raw = _as_payload(payload)
        if payload.subject_id is not None:
            selected: dict[str, object] = {"subject_id": payload.subject_id}
            if payload.locale is not None:
                selected["locale"] = payload.locale
            return read_tool("card_schema_characteristics", selected)
        if any(
            value is not None
            for value in (
                payload.parent_id,
                payload.name,
                payload.limit,
                payload.offset,
            )
        ):
            selected = {
                key: raw[key]
                for key in ("locale", "parent_id", "name", "limit", "offset")
                if key in raw
            }
            return read_tool("card_schema_subjects", selected)
        selected: dict[str, object] = (
            {"locale": payload.locale} if payload.locale is not None else {}
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
    def wb_list_card_errors(
        payload: CardErrorsPayload = CardErrorsPayload(),
    ) -> dict[str, object]:
        return read_tool("list_card_errors", _as_payload(payload))

    @mcp.tool(
        name="wb_list_tags",
        description="Возвращает все ярлыки карточек текущего продавца WB без пагинации.",
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_list_tags(payload: EmptyPayload = EmptyPayload()) -> dict[str, object]:
        return read_tool("list_tags", _as_payload(payload))

    @mcp.tool(
        name="wb_list_prices",
        description=(
            "Возвращает постраничные цены и скидки WB. Используйте limit/offset или "
            "filter_nm_id для одного артикула WB."
        ),
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_list_prices(payload: PricesPayload = PricesPayload()) -> dict[str, object]:
        return read_tool("list_prices", _as_payload(payload))

    @mcp.tool(
        name="wb_get_stocks",
        description=(
            "Получает остатки выбранных размеров на складе продавца WB. Нужны "
            "warehouse_id и до 1000 chrt_ids; это не общий список всех остатков."
        ),
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_get_stocks(payload: StocksPayload) -> dict[str, object]:
        return read_tool("get_stocks", _as_payload(payload))

    @mcp.tool(
        name="wb_list_warehouses",
        description="Возвращает склады продавца WB без пагинации.",
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_list_warehouses(payload: EmptyPayload = EmptyPayload()) -> dict[str, object]:
        return read_tool("list_warehouses", _as_payload(payload))

    @mcp.tool(
        name="wb_list_orders",
        description=(
            "Возвращает постраничные FBS-заказы WB. Передайте limit, next=0 для первой "
            "страницы и при необходимости UNIX date_from/date_to в UTC."
        ),
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_list_orders(payload: OrdersPayload = OrdersPayload()) -> dict[str, object]:
        return read_tool("list_orders", _as_payload(payload))

    @mcp.tool(
        name="wb_get_order_details",
        description=(
            "Возвращает детали новых FBS-заказов WB. Установленный SDK не даёт безопасный "
            "GET одного order_id: при его передаче инструмент вернёт подсказку для списка."
        ),
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_get_order_details(
        payload: OrderDetailsPayload = OrderDetailsPayload(),
    ) -> dict[str, object]:
        if payload.order_id is not None:
            return _unsupported_order_id()
        return read_tool("get_order_details", {})

    @mcp.tool(
        name="wb_get_order_stickers",
        description=(
            "Генерирует стикеры до 100 FBS-заказов WB. Передайте order_ids, формат type "
            "и размеры width/height; инструмент только читает/получает файл стикеров."
        ),
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_get_order_stickers(payload: OrderStickersPayload) -> dict[str, object]:
        return read_tool("get_order_stickers", _as_payload(payload))

    @mcp.tool(
        name="wb_list_supplies",
        description=(
            "Возвращает постраничные FBS-поставки WB. Передайте limit и next=0 для "
            "первой страницы, затем используйте курсор из ответа."
        ),
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_list_supplies(
        payload: SuppliesPayload = SuppliesPayload(),
    ) -> dict[str, object]:
        return read_tool("list_supplies", _as_payload(payload))

    @mcp.tool(
        name="wb_get_supply",
        description="Возвращает детали одной FBS-поставки WB по supply_id.",
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_get_supply(payload: SupplyIdPayload) -> dict[str, object]:
        return read_tool("get_supply", _as_payload(payload))

    @mcp.tool(
        name="wb_get_supply_barcode",
        description=(
            "Возвращает QR/стикер FBS-поставки WB по supply_id и type. Стикер доступен "
            "для поставки в подходящем статусе WB."
        ),
        annotations=READ_ANNOTATIONS,
        structured_output=True,
    )
    def wb_get_supply_barcode(payload: SupplyBarcodePayload) -> dict[str, object]:
        return read_tool("get_supply_barcode", _as_payload(payload))

    @mcp.tool(
        name="wb_plan_update_cards",
        description=(
            "Проверяет и создаёт подтверждаемый план обновления карточек WB. Передайте "
            "cards с nmID, vendorCode и sizes; WB не вызывается до wb_apply_change."
        ),
        annotations=PLAN_ANNOTATIONS,
        structured_output=True,
    )
    def wb_plan_update_cards(payload: UpdateCardsPayload) -> dict[str, object]:
        return plan_tool("update_cards", _as_payload(payload))

    @mcp.tool(
        name="wb_plan_save_media",
        description=(
            "Создаёт подтверждаемый план замены медиа карточки WB. mediaUrls — полный "
            "упорядоченный список: после применения он заменит все текущие медиа."
        ),
        annotations=PLAN_ANNOTATIONS,
        structured_output=True,
    )
    def wb_plan_save_media(payload: SaveMediaPayload) -> dict[str, object]:
        return plan_tool("save_media", _as_payload(payload))

    @mcp.tool(
        name="wb_plan_set_prices",
        description=(
            "Создаёт подтверждаемый план изменения цен и скидок WB (до 1000 items). "
            "Перед применением WB не вызывается."
        ),
        annotations=PLAN_ANNOTATIONS,
        structured_output=True,
    )
    def wb_plan_set_prices(payload: SetPricesPayload) -> dict[str, object]:
        return plan_tool("set_prices", _as_payload(payload))

    @mcp.tool(
        name="wb_plan_set_stocks",
        description=(
            "Создаёт подтверждаемый план записи остатков WB на одном warehouse_id. "
            "Передайте stocks с chrtId и amount; WB не вызывается до подтверждения."
        ),
        annotations=PLAN_ANNOTATIONS,
        structured_output=True,
    )
    def wb_plan_set_stocks(payload: SetStocksPayload) -> dict[str, object]:
        return plan_tool("set_stocks", _as_payload(payload))

    @mcp.tool(
        name="wb_plan_manage_warehouse",
        description=(
            "Создаёт подтверждаемый план create/update/delete склада продавца WB. "
            "Для create/update нужны name и office_id, для update/delete — warehouse_id."
        ),
        annotations=PLAN_ANNOTATIONS,
        structured_output=True,
    )
    def wb_plan_manage_warehouse(
        payload: ManageWarehousePayload,
    ) -> dict[str, object]:
        raw = _as_payload(payload)
        if payload.action == "create":
            return plan_tool(
                "create_warehouse", {"name": raw["name"], "office_id": raw["office_id"]}
            )
        if payload.action == "update":
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
        name="wb_plan_update_order_status",
        description=(
            "Создаёт подтверждаемый план перевода статуса FBS-заказов WB. Передайте "
            "до 1000 order_ids; WB не вызывается до wb_apply_change."
        ),
        annotations=PLAN_ANNOTATIONS,
        structured_output=True,
    )
    def wb_plan_update_order_status(
        payload: UpdateOrderStatusPayload,
    ) -> dict[str, object]:
        return plan_tool("update_order_status", _as_payload(payload))

    @mcp.tool(
        name="wb_plan_cancel_order",
        description=(
            "Создаёт подтверждаемый план отмены одного FBS-заказа WB по order_id. "
            "WB не вызывается до wb_apply_change."
        ),
        annotations=PLAN_ANNOTATIONS,
        structured_output=True,
    )
    def wb_plan_cancel_order(payload: CancelOrderPayload) -> dict[str, object]:
        return plan_tool("cancel_order", _as_payload(payload))

    @mcp.tool(
        name="wb_plan_create_supply",
        description=(
            "Создаёт подтверждаемый план создания FBS-поставки WB с name. WB не "
            "вызывается до wb_apply_change."
        ),
        annotations=PLAN_ANNOTATIONS,
        structured_output=True,
    )
    def wb_plan_create_supply(payload: CreateSupplyPayload) -> dict[str, object]:
        return plan_tool("create_supply", _as_payload(payload))

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
    def wb_plan_update_supply(payload: UpdateSupplyPayload) -> dict[str, object]:
        raw = _as_payload(payload)
        if payload.action == "attach_orders":
            return plan_tool(
                "attach_supply_orders",
                {"supply_id": raw["supply_id"], "order_ids": raw["order_ids"]},
            )
        if payload.action == "deliver":
            return plan_tool("deliver_supply", {"supply_id": raw["supply_id"]})
        return plan_tool("delete_supply", {"supply_id": raw["supply_id"]})

    @mcp.tool(
        name="wb_apply_change",
        description=(
            "Однократно применяет ранее созданный план по confirmation_id. После попытки "
            "план расходуется, даже если WB вернул ошибку."
        ),
        annotations=APPLY_ANNOTATIONS,
        structured_output=True,
    )
    def wb_apply_change(
        confirmation_id: StrictStr = Field(
            description="Одноразовый ID подтверждаемого плана.",
            examples=["f0f4b2d2-6b4b-4cc4-8df2-f8bd8416dc3a"],
        ),
    ) -> dict[str, object]:
        try:
            plan = plans.consume(confirmation_id)
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

    return mcp


def main() -> None:
    """Start the WB MCP server over standard input and output."""

    create_server().run(transport="stdio")

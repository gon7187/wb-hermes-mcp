"""Explicit FastMCP tools for the safe Wildberries seller workflows."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
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
_SECRET_KEY_PATTERN = re.compile(
    r"token|secret|authorization|password|api[_-]?key|cookie|credential|private",
    re.IGNORECASE,
)
_SECRET_VALUE_PATTERN = re.compile(
    r"secret|token|authorization|bearer|api[_-]?key|password|cookie|credential",
    re.IGNORECASE,
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


def _safe_summary_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _safe_summary_value(item)
            for key, item in value.items()
            if isinstance(key, str) and not _SECRET_KEY_PATTERN.search(key)
        }
    if isinstance(value, list | tuple):
        return [_safe_summary_value(item) for item in value]
    if isinstance(value, str):
        return "[redacted]" if _SECRET_VALUE_PATTERN.search(value) else value
    if value is None or isinstance(value, bool | int | float):
        return value
    return "[redacted]"


def _plan_summary(operation: str, payload: Mapping[str, object]) -> dict[str, object]:
    target_keys = ("nm_id", "nmID", "warehouse_id", "order_id", "supply_id")
    targets = [
        {key: _safe_summary_value(payload[key])}
        for key in target_keys
        if key in payload and not _SECRET_KEY_PATTERN.search(key)
    ]
    return {
        "operation": operation,
        "targets": targets,
        "payload": _safe_summary_value(payload),
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
    mcp.register_root_input("wb_apply_change", ApplyChangeInput)

    return mcp


def main() -> None:
    """Start the WB MCP server over standard input and output."""

    create_server().run(transport="stdio")

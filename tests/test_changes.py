from datetime import datetime, timedelta, timezone

import pytest

from wb_mcp.changes import (
    ChangeStore,
    ConfirmationExpired,
    ConfirmationNotFound,
    ConfirmationUsed,
)


def test_confirmation_is_single_use() -> None:
    store = ChangeStore(ttl=timedelta(minutes=15))
    plan = store.create("set_prices", {"items": []})

    assert store.consume(plan.confirmation_id).operation == "set_prices"
    with pytest.raises(ConfirmationUsed):
        store.consume(plan.confirmation_id)


def test_confirmation_default_ttl_is_fifteen_minutes() -> None:
    now = datetime(2026, 7, 23, tzinfo=timezone.utc)
    store = ChangeStore(clock=lambda: now)

    plan = store.create("set_prices", {"items": []})

    assert plan.expires_at - plan.created_at == timedelta(minutes=15)


def test_expired_confirmation_is_removed_and_reports_expiry() -> None:
    now = datetime(2026, 7, 23, tzinfo=timezone.utc)
    current_time = [now]
    store = ChangeStore(ttl=timedelta(seconds=1), clock=lambda: current_time[0])
    plan = store.create("set_prices", {"items": []})
    current_time[0] = now + timedelta(seconds=1)

    with pytest.raises(ConfirmationExpired):
        store.consume(plan.confirmation_id)
    with pytest.raises(ConfirmationExpired):
        store.consume(plan.confirmation_id)


def test_unknown_confirmation_is_actionable_without_echoing_the_id() -> None:
    store = ChangeStore()

    with pytest.raises(ConfirmationNotFound) as caught:
        store.consume("unknown-confirmation-id")

    assert "unknown-confirmation-id" not in str(caught.value)
    assert "Create a new plan" in str(caught.value)

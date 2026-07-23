"""In-memory, expiring confirmation records for write operations."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from uuid import uuid4


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ChangePlan:
    confirmation_id: str
    operation: str
    payload: dict[str, object]
    created_at: datetime
    expires_at: datetime


class ConfirmationError(Exception):
    """Base class for safe confirmation lifecycle errors."""


class ConfirmationNotFound(ConfirmationError):
    def __init__(self) -> None:
        super().__init__(
            "Confirmation plan was not found. Create a new plan and try again."
        )


class ConfirmationExpired(ConfirmationError):
    def __init__(self) -> None:
        super().__init__("Confirmation plan expired. Create a new plan and try again.")


class ConfirmationUsed(ConfirmationError):
    def __init__(self) -> None:
        super().__init__(
            "Confirmation plan was already used. Create a new plan to repeat it."
        )


class ChangeStore:
    """Store a write plan until it is used once or reaches its expiry time."""

    def __init__(
        self,
        ttl: timedelta = timedelta(minutes=15),
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._ttl = ttl
        self._clock = clock
        self._plans: dict[str, ChangePlan] = {}
        self._used: set[str] = set()
        self._expired: set[str] = set()
        self._lock = Lock()

    def create(self, operation: str, payload: dict[str, object]) -> ChangePlan:
        created_at = self._clock()
        plan = ChangePlan(
            confirmation_id=str(uuid4()),
            operation=operation,
            payload=deepcopy(payload),
            created_at=created_at,
            expires_at=created_at + self._ttl,
        )
        with self._lock:
            self._plans[plan.confirmation_id] = plan
        return plan

    def consume(self, confirmation_id: str) -> ChangePlan:
        with self._lock:
            plan = self._plans.pop(confirmation_id, None)
            if plan is None:
                if confirmation_id in self._used:
                    raise ConfirmationUsed
                if confirmation_id in self._expired:
                    raise ConfirmationExpired
                raise ConfirmationNotFound
            if self._clock() >= plan.expires_at:
                self._expired.add(confirmation_id)
                raise ConfirmationExpired
            self._used.add(confirmation_id)
            return plan

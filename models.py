from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid4())


@dataclass(slots=True)
class BaseEvent:
    event_id: str = field(default_factory=new_id)
    trace_id: str = field(default_factory=new_id)
    occurred_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class MeterReadingIngested(BaseEvent):
    household_id: str = ""
    generated_kwh: float = 0.0
    consumed_kwh: float = 0.0

    @property
    def net_kwh(self) -> float:
        return round(self.generated_kwh - self.consumed_kwh, 6)


@dataclass(slots=True)
class EnergyPositionUpdated(BaseEvent):
    household_id: str = ""
    net_kwh: float = 0.0
    side: Literal["SELL", "BUY"] = "BUY"


@dataclass(slots=True)
class TradeMatched(BaseEvent):
    trade_id: str = field(default_factory=new_id)
    seller_id: str = ""
    buyer_id: str = ""
    quantity_kwh: float = 0.0
    price_per_kwh: float = 0.0

    @property
    def total_amount(self) -> float:
        return round(self.quantity_kwh * self.price_per_kwh, 6)


@dataclass(slots=True)
class SettlementCompleted(BaseEvent):
    trade_id: str = ""
    amount: float = 0.0


@dataclass(slots=True)
class SettlementFailed(BaseEvent):
    trade_id: str = ""
    reason: str = ""


@dataclass(slots=True)
class Offer:
    household_id: str
    quantity_kwh: float
    price_per_kwh: float
    created_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class Bid:
    household_id: str
    quantity_kwh: float
    max_price_per_kwh: float
    created_at: datetime = field(default_factory=utc_now)


from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from statistics import mean
from time import perf_counter
from typing import Deque, Dict, Iterable, List, Sequence
from uuid import uuid4

from .broker import BrokerBridge, DomainBroker
from .models import (
    Bid,
    EnergyPositionUpdated,
    MeterReadingIngested,
    Offer,
    SettlementCompleted,
    SettlementFailed,
    TradeMatched,
)
from .resilience import CircuitBreaker, retry_with_backoff


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class Telemetry:
    counters: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    latencies_ms: Dict[str, List[float]] = field(default_factory=lambda: defaultdict(list))

    def inc(self, key: str, amount: int = 1) -> None:
        self.counters[key] += amount

    def observe(self, key: str, value_ms: float) -> None:
        self.latencies_ms[key].append(value_ms)

    def p99(self, key: str) -> float:
        values = sorted(self.latencies_ms.get(key, []))
        if not values:
            return 0.0
        idx = max(0, min(len(values) - 1, int(round(0.99 * (len(values) - 1)))))
        return values[idx]

    def p95(self, key: str) -> float:
        values = sorted(self.latencies_ms.get(key, []))
        if not values:
            return 0.0
        idx = max(0, min(len(values) - 1, int(round(0.95 * (len(values) - 1)))))
        return values[idx]

    def avg(self, key: str) -> float:
        values = self.latencies_ms.get(key, [])
        if not values:
            return 0.0
        return mean(values)


@dataclass(frozen=True)
class SecurityPolicy:
    """Simple API-key guard for the smart meter ingestion boundary."""

    authorized_api_keys: frozenset[str]

    @classmethod
    def from_keys(cls, api_keys: Sequence[str]) -> "SecurityPolicy":
        return cls(authorized_api_keys=frozenset(api_keys))

    def authorize_meter_ingestion(self, api_key: str | None) -> None:
        if api_key not in self.authorized_api_keys:
            raise PermissionError("Unauthorized meter ingestion request.")


class MeterIngestionService:
    """Bounded Context: Meter Ingestion."""

    def __init__(
        self,
        ingestion_broker: DomainBroker,
        telemetry: Telemetry,
        security_policy: SecurityPolicy | None = None,
    ) -> None:
        self.ingestion_broker = ingestion_broker
        self.telemetry = telemetry
        self.security_policy = security_policy

    def ingest(
        self,
        household_id: str,
        generated_kwh: float,
        consumed_kwh: float,
        trace_id: str | None = None,
        api_key: str | None = None,
    ) -> str:
        if self.security_policy:
            self.security_policy.authorize_meter_ingestion(api_key)
        if generated_kwh < 0 or consumed_kwh < 0:
            raise ValueError("Meter values must be non-negative.")
        event = MeterReadingIngested(
            trace_id=trace_id or str(uuid4()),
            household_id=household_id,
            generated_kwh=generated_kwh,
            consumed_kwh=consumed_kwh,
        )
        self.ingestion_broker.publish(event)
        self.telemetry.inc("meter_readings_ingested")
        return event.trace_id


class MarketplaceService:
    """Bounded Context: Marketplace matching engine."""

    def __init__(self, broker: DomainBroker, telemetry: Telemetry) -> None:
        self.broker = broker
        self.telemetry = telemetry
        self.sell_offers: Deque[Offer] = deque()
        self.buy_bids: Deque[Bid] = deque()
        self.latest_trades: List[TradeMatched] = []

        self.broker.subscribe(EnergyPositionUpdated, self.handle_energy_position)

    def handle_energy_position(self, event: EnergyPositionUpdated) -> None:
        start = perf_counter()
        if event.side == "SELL":
            self.sell_offers.append(
                Offer(
                    household_id=event.household_id,
                    quantity_kwh=max(event.net_kwh, 0.0),
                    price_per_kwh=0.24,
                )
            )
        elif event.side == "BUY":
            self.buy_bids.append(
                Bid(
                    household_id=event.household_id,
                    quantity_kwh=abs(min(event.net_kwh, 0.0)),
                    max_price_per_kwh=0.32,
                )
            )
        self._match_orders(trace_id=event.trace_id)
        elapsed_ms = (perf_counter() - start) * 1000
        self.telemetry.observe("marketplace_handle_ms", elapsed_ms)

    def _match_orders(self, trace_id: str) -> None:
        while self.sell_offers and self.buy_bids:
            sell = self.sell_offers[0]
            buy = self.buy_bids[0]
            if buy.max_price_per_kwh < sell.price_per_kwh:
                break

            quantity = min(sell.quantity_kwh, buy.quantity_kwh)
            if quantity <= 0:
                break
            price = round((sell.price_per_kwh + buy.max_price_per_kwh) / 2, 4)
            trade = TradeMatched(
                trace_id=trace_id,
                seller_id=sell.household_id,
                buyer_id=buy.household_id,
                quantity_kwh=round(quantity, 6),
                price_per_kwh=price,
            )
            self.latest_trades.append(trade)
            self.broker.publish(trade)
            self.telemetry.inc("trades_matched")

            sell.quantity_kwh = round(sell.quantity_kwh - quantity, 6)
            buy.quantity_kwh = round(buy.quantity_kwh - quantity, 6)
            if sell.quantity_kwh <= 0:
                self.sell_offers.popleft()
            if buy.quantity_kwh <= 0:
                self.buy_bids.popleft()


class SettlementService:
    """Bounded Context: Financial settlement with Saga-style compensation."""

    def __init__(
        self,
        broker: DomainBroker,
        telemetry: Telemetry,
        initial_wallets: Dict[str, float] | None = None,
        credit_failure_households: Sequence[str] | None = None,
    ) -> None:
        self.broker = broker
        self.telemetry = telemetry
        self.wallets: Dict[str, float] = dict(initial_wallets or {})
        self.credit_failure_households = set(credit_failure_households or [])
        self.processed_trades: set[str] = set()
        self.circuit_breaker = CircuitBreaker(failure_threshold=3, reset_timeout_s=0.1)
        self.broker.subscribe(TradeMatched, self.handle_trade)

    def handle_trade(self, trade: TradeMatched) -> None:
        if trade.trade_id in self.processed_trades:
            self.telemetry.inc("settlement_idempotent_skips")
            return

        start = perf_counter()
        if not self.circuit_breaker.allow_request():
            self.processed_trades.add(trade.trade_id)
            self.broker.publish(
                SettlementFailed(trace_id=trade.trace_id, trade_id=trade.trade_id, reason="Circuit breaker is open")
            )
            self.telemetry.inc("settlement_blocked_by_circuit")
            return

        debited = False
        amount = trade.total_amount
        try:
            self._ensure_account(trade.buyer_id, default_balance=100.0)
            self._ensure_account(trade.seller_id, default_balance=0.0)

            # Local transaction A: debit buyer.
            self._debit_wallet(trade.buyer_id, amount)
            debited = True

            # Local transaction B: credit seller (with retry).
            retry_with_backoff(lambda: self._credit_wallet(trade.seller_id, amount), attempts=3, base_delay_s=0.002)

            self.circuit_breaker.record_success()
            self.processed_trades.add(trade.trade_id)
            self.broker.publish(SettlementCompleted(trace_id=trade.trace_id, trade_id=trade.trade_id, amount=amount))
            self.telemetry.inc("settlements_completed")
        except Exception as exc:
            if debited:
                # Compensating action (Saga): refund buyer.
                self._credit_raw(trade.buyer_id, amount)
                self.telemetry.inc("saga_compensations")
            self.circuit_breaker.record_failure()
            self.processed_trades.add(trade.trade_id)
            self.broker.publish(SettlementFailed(trace_id=trade.trace_id, trade_id=trade.trade_id, reason=str(exc)))
            self.telemetry.inc("settlements_failed")
        finally:
            self.telemetry.observe("settlement_handle_ms", (perf_counter() - start) * 1000)

    def _ensure_account(self, household_id: str, default_balance: float) -> None:
        if household_id not in self.wallets:
            self.wallets[household_id] = float(default_balance)

    def _debit_wallet(self, household_id: str, amount: float) -> None:
        balance = self.wallets[household_id]
        if balance < amount:
            raise ValueError(f"Insufficient balance for {household_id}")
        self.wallets[household_id] = round(balance - amount, 6)

    def _credit_raw(self, household_id: str, amount: float) -> None:
        self.wallets[household_id] = round(self.wallets[household_id] + amount, 6)

    def _credit_wallet(self, household_id: str, amount: float) -> None:
        if household_id in self.credit_failure_households:
            raise RuntimeError(f"Credit gateway failure for {household_id}")
        self._credit_raw(household_id, amount)


class EcoGridSystem:
    """Composes bounded contexts and brokers."""

    def __init__(
        self,
        use_dual_broker: bool = True,
        initial_wallets: Dict[str, float] | None = None,
        credit_failure_households: Sequence[str] | None = None,
        authorized_api_keys: Sequence[str] | None = None,
    ) -> None:
        self.use_dual_broker = use_dual_broker
        self.architecture_mode = "dual-broker-domain-bridge" if use_dual_broker else "single-broker"
        self.telemetry = Telemetry()
        self.security_policy = (
            SecurityPolicy.from_keys(authorized_api_keys) if authorized_api_keys is not None else None
        )
        if use_dual_broker:
            self.ingestion_broker = DomainBroker("meter-domain")
            self.market_broker = DomainBroker("market-domain")
            self.bridge = BrokerBridge(source=self.ingestion_broker, target=self.market_broker)
            self.bridge.forward(MeterReadingIngested, self._map_meter_to_position)
        else:
            self.ingestion_broker = DomainBroker("shared-energy-domain")
            self.market_broker = self.ingestion_broker
            self.bridge = None
            self.ingestion_broker.subscribe(MeterReadingIngested, self._on_meter_reading)

        self.ingestion = MeterIngestionService(self.ingestion_broker, self.telemetry, self.security_policy)
        self.marketplace = MarketplaceService(self.market_broker, self.telemetry)
        self.settlement = SettlementService(
            self.market_broker,
            self.telemetry,
            initial_wallets=initial_wallets,
            credit_failure_households=credit_failure_households,
        )

        # Collect settlement events for reporting.
        self.completed: List[SettlementCompleted] = []
        self.failed: List[SettlementFailed] = []
        self.market_broker.subscribe(SettlementCompleted, self.completed.append)
        self.market_broker.subscribe(SettlementFailed, self.failed.append)

    def _on_meter_reading(self, event: MeterReadingIngested) -> None:
        self.market_broker.publish(self._map_meter_to_position(event))

    @staticmethod
    def _map_meter_to_position(event: MeterReadingIngested) -> EnergyPositionUpdated:
        net = event.net_kwh
        side = "SELL" if net > 0 else "BUY"
        return EnergyPositionUpdated(
            trace_id=event.trace_id,
            household_id=event.household_id,
            net_kwh=net,
            side=side,
            occurred_at=_now(),
        )

    def start(self) -> None:
        self.ingestion_broker.start()
        if self.market_broker is not self.ingestion_broker:
            self.market_broker.start()

    def stop(self) -> None:
        self.ingestion_broker.stop()
        if self.market_broker is not self.ingestion_broker:
            self.market_broker.stop()

    def await_idle(self) -> None:
        self.ingestion_broker.join()
        if self.market_broker is not self.ingestion_broker:
            self.market_broker.join()

    def run_batch(self, readings: Iterable[tuple[str, float, float]]) -> None:
        for household_id, generated, consumed in readings:
            self.ingestion.ingest(household_id, generated, consumed)
        self.await_idle()

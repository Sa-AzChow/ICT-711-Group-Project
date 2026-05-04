from __future__ import annotations

import unittest

from ecogrid.models import TradeMatched
from ecogrid.services import EcoGridSystem


class TestEcoGridFitnessFunctions(unittest.TestCase):
    def test_end_to_end_integrity(self) -> None:
        system = EcoGridSystem(initial_wallets={"buyer_1": 100.0})
        system.start()
        try:
            system.run_batch(
                [
                    ("seller_1", 7.0, 2.0),  # +5
                    ("buyer_1", 1.0, 4.0),   # -3
                    ("buyer_2", 1.0, 3.0),   # -2 (auto wallet 100)
                ]
            )
        finally:
            system.stop()

        self.assertGreaterEqual(system.telemetry.counters.get("trades_matched", 0), 1)
        self.assertEqual(system.telemetry.counters.get("settlements_failed", 0), 0)
        self.assertGreaterEqual(system.telemetry.counters.get("settlements_completed", 0), 1)

        for _, balance in system.settlement.wallets.items():
            self.assertGreaterEqual(balance, 0.0, "Wallet balance must never be negative.")

    def test_saga_compensation_on_credit_failure(self) -> None:
        wallets = {"buyer_fail_case": 80.0}
        system = EcoGridSystem(initial_wallets=wallets, credit_failure_households=["seller_fail_case"])
        system.start()
        try:
            system.run_batch(
                [
                    ("seller_fail_case", 6.0, 1.0),  # +5
                    ("buyer_fail_case", 0.0, 5.0),   # -5
                ]
            )
        finally:
            system.stop()

        self.assertEqual(system.telemetry.counters.get("settlements_completed", 0), 0)
        self.assertGreaterEqual(system.telemetry.counters.get("settlements_failed", 0), 1)
        self.assertGreaterEqual(system.telemetry.counters.get("saga_compensations", 0), 1)
        self.assertAlmostEqual(system.settlement.wallets["buyer_fail_case"], 80.0, places=6)
        self.assertAlmostEqual(system.settlement.wallets.get("seller_fail_case", 0.0), 0.0, places=6)

    def test_idempotency_prevents_double_settlement(self) -> None:
        system = EcoGridSystem(initial_wallets={"buyer_idem": 100.0})
        trade = TradeMatched(
            trace_id="trace-idempotent",
            trade_id="trade-1",
            seller_id="seller_idem",
            buyer_id="buyer_idem",
            quantity_kwh=2.0,
            price_per_kwh=0.25,
        )
        system.start()
        try:
            system.market_broker.publish(trade)
            system.market_broker.publish(trade)
            system.await_idle()
        finally:
            system.stop()

        self.assertEqual(system.telemetry.counters.get("settlements_completed", 0), 1)
        self.assertEqual(system.telemetry.counters.get("settlement_idempotent_skips", 0), 1)

    def test_latency_fitness_budget(self) -> None:
        readings = []
        for i in range(120):
            readings.append((f"seller_{i}", 4.0, 1.0))  # +3
            readings.append((f"buyer_{i}", 0.5, 2.5))   # -2

        system = EcoGridSystem()
        system.start()
        try:
            system.run_batch(readings)
        finally:
            system.stop()

        # Practical local thresholds for CI sanity checks.
        self.assertLess(system.telemetry.p99("marketplace_handle_ms"), 100.0)
        self.assertLess(system.telemetry.p95("settlement_handle_ms"), 100.0)

    def test_security_fitness_rejects_unauthorized_meter_ingestion(self) -> None:
        system = EcoGridSystem(authorized_api_keys=["trusted-meter-key"])

        with self.assertRaises(PermissionError):
            system.ingestion.ingest("untrusted_meter", 3.0, 1.0, api_key="unknown-key")

        self.assertEqual(system.telemetry.counters.get("meter_readings_ingested", 0), 0)

    def test_trace_correlation_is_preserved_end_to_end(self) -> None:
        trace_id = "trace-fitness-observability"
        system = EcoGridSystem(initial_wallets={"buyer_trace": 100.0})
        system.start()
        try:
            system.ingestion.ingest("seller_trace", 5.0, 1.0, trace_id="seller-trace")
            system.ingestion.ingest("buyer_trace", 0.0, 2.0, trace_id=trace_id)
            system.await_idle()
        finally:
            system.stop()

        self.assertGreaterEqual(len(system.marketplace.latest_trades), 1)
        self.assertGreaterEqual(len(system.completed), 1)
        self.assertEqual(system.marketplace.latest_trades[-1].trace_id, trace_id)
        self.assertEqual(system.completed[-1].trace_id, trace_id)


if __name__ == "__main__":
    unittest.main()

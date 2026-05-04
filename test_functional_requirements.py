from __future__ import annotations

import unittest

from ecogrid.models import TradeMatched
from ecogrid.services import EcoGridSystem


class TestEcoGridFunctionalRequirements(unittest.TestCase):
    def test_fr01_ingest_valid_reading(self) -> None:
        system = EcoGridSystem()
        system.start()
        try:
            system.ingestion.ingest("household_a", 3.0, 1.0)
            system.await_idle()
        finally:
            system.stop()
        self.assertEqual(system.telemetry.counters.get("meter_readings_ingested", 0), 1)

    def test_fr02_reject_negative_meter_values(self) -> None:
        system = EcoGridSystem()
        with self.assertRaises(ValueError):
            system.ingestion.ingest("household_invalid", -1.0, 2.0)
        with self.assertRaises(ValueError):
            system.ingestion.ingest("household_invalid", 1.0, -2.0)

    def test_fr03_classify_positions_and_match_trade(self) -> None:
        system = EcoGridSystem()
        system.start()
        try:
            system.run_batch(
                [
                    ("seller_case", 6.0, 2.0),  # +4 kWh
                    ("buyer_case", 0.0, 3.0),   # -3 kWh
                ]
            )
        finally:
            system.stop()

        self.assertGreaterEqual(system.telemetry.counters.get("trades_matched", 0), 1)
        self.assertGreaterEqual(len(system.marketplace.latest_trades), 1)

    def test_fr04_successful_settlement_transfers_funds(self) -> None:
        buyer_start = 10.0
        system = EcoGridSystem(initial_wallets={"buyer_pay": buyer_start})
        system.start()
        try:
            system.run_batch(
                [
                    ("seller_pay", 6.0, 1.0),  # +5
                    ("buyer_pay", 1.0, 4.0),   # -3, trade value: 3 * 0.28 = 0.84
                ]
            )
        finally:
            system.stop()

        self.assertEqual(system.telemetry.counters.get("settlements_failed", 0), 0)
        self.assertGreaterEqual(system.telemetry.counters.get("settlements_completed", 0), 1)
        self.assertAlmostEqual(system.settlement.wallets["buyer_pay"], 9.16, places=2)
        self.assertAlmostEqual(system.settlement.wallets["seller_pay"], 0.84, places=2)

    def test_fr05_saga_compensation_restores_buyer_balance(self) -> None:
        start_balance = 30.0
        system = EcoGridSystem(
            initial_wallets={"buyer_fail": start_balance},
            credit_failure_households=["seller_fail"],
        )
        system.start()
        try:
            system.run_batch(
                [
                    ("seller_fail", 5.0, 0.0),  # +5
                    ("buyer_fail", 0.0, 5.0),   # -5
                ]
            )
        finally:
            system.stop()

        self.assertGreaterEqual(system.telemetry.counters.get("settlements_failed", 0), 1)
        self.assertGreaterEqual(system.telemetry.counters.get("saga_compensations", 0), 1)
        self.assertAlmostEqual(system.settlement.wallets["buyer_fail"], start_balance, places=6)
        self.assertAlmostEqual(system.settlement.wallets.get("seller_fail", 0.0), 0.0, places=6)

    def test_fr06_duplicate_trade_is_processed_once(self) -> None:
        system = EcoGridSystem(initial_wallets={"buyer_idem_fr": 100.0})
        trade = TradeMatched(
            trace_id="trace-fr-06",
            trade_id="fr-06-trade",
            seller_id="seller_idem_fr",
            buyer_id="buyer_idem_fr",
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

    def test_fr07_dual_broker_mode_works(self) -> None:
        system = EcoGridSystem(use_dual_broker=True)
        system.start()
        try:
            system.run_batch(
                [
                    ("seller_dual", 4.0, 1.0),
                    ("buyer_dual", 0.0, 2.0),
                ]
            )
        finally:
            system.stop()
        self.assertEqual(system.architecture_mode, "dual-broker-domain-bridge")
        self.assertGreaterEqual(system.telemetry.counters.get("trades_matched", 0), 1)

    def test_fr08_single_broker_mode_works(self) -> None:
        system = EcoGridSystem(use_dual_broker=False)
        system.start()
        try:
            system.run_batch(
                [
                    ("seller_single", 4.0, 1.0),
                    ("buyer_single", 0.0, 2.0),
                ]
            )
        finally:
            system.stop()
        self.assertEqual(system.architecture_mode, "single-broker")
        self.assertGreaterEqual(system.telemetry.counters.get("trades_matched", 0), 1)

    def test_fr09_unauthorized_meter_ingestion_is_rejected(self) -> None:
        system = EcoGridSystem(authorized_api_keys=["meter-key-1"])

        with self.assertRaises(PermissionError):
            system.ingestion.ingest("household_secure", 2.0, 1.0, api_key="wrong-key")

        self.assertEqual(system.telemetry.counters.get("meter_readings_ingested", 0), 0)

    def test_fr10_authorized_meter_ingestion_is_accepted(self) -> None:
        system = EcoGridSystem(authorized_api_keys=["meter-key-1"])
        system.start()
        try:
            system.ingestion.ingest("household_secure", 2.0, 1.0, api_key="meter-key-1")
            system.await_idle()
        finally:
            system.stop()

        self.assertEqual(system.telemetry.counters.get("meter_readings_ingested", 0), 1)


if __name__ == "__main__":
    unittest.main()

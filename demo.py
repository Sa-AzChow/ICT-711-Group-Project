from __future__ import annotations

from ecogrid.services import EcoGridSystem


def main() -> None:
    sample_readings = [
        ("seller_a", 8.0, 3.0),   # +5.0 kWh
        ("buyer_x", 1.0, 4.0),    # -3.0 kWh
        ("buyer_y", 0.8, 2.8),    # -2.0 kWh
        ("seller_b", 6.5, 2.5),   # +4.0 kWh
        ("buyer_z", 0.5, 2.5),    # -2.0 kWh
    ]
    wallets = {"buyer_x": 50.0, "buyer_y": 50.0, "buyer_z": 50.0}
    system = EcoGridSystem(initial_wallets=wallets)
    system.start()
    try:
        system.run_batch(sample_readings)
    finally:
        system.stop()

    print("=== EcoGrid Demo Summary ===")
    print(f"Architecture mode: {system.architecture_mode}")
    print(f"Readings ingested: {system.telemetry.counters.get('meter_readings_ingested', 0)}")
    print(f"Trades matched: {system.telemetry.counters.get('trades_matched', 0)}")
    print(f"Settlements completed: {system.telemetry.counters.get('settlements_completed', 0)}")
    print(f"Settlements failed: {system.telemetry.counters.get('settlements_failed', 0)}")
    print(f"Saga compensations: {system.telemetry.counters.get('saga_compensations', 0)}")
    print("Wallet balances:")
    for household_id, balance in sorted(system.settlement.wallets.items()):
        print(f"  {household_id}: ${balance:.4f}")


if __name__ == "__main__":
    main()

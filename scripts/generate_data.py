#!/usr/bin/env python3
"""
scripts/generate_data.py – Synthetic transaction generator
===========================================================
Produces a realistic 100 k-row transaction dataset and writes it to
``data/transactions_100k.json`` (ready to POST directly to /attributes).

Usage
-----
    python scripts/generate_data.py                  # 100 k rows (default)
    python scripts/generate_data.py --rows 10000     # custom size
    python scripts/generate_data.py --rows 100000 --accounts 500

The output is a JSON object:  { "transactions": [ {...}, ... ] }

Realism controls
----------------
* Salary credits land on the 25th of each month for salaried accounts
* Grocery and utility spend is weighted toward weekdays
* Debit amounts are right-skewed (most transactions small, occasional large)
* ~0.5 % of rows are deliberate duplicates to exercise the dedup path
"""

from __future__ import annotations

import argparse
import json
import random
import uuid
from datetime import date, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MERCHANT_CATEGORIES = [
    ("GROCERY", 0.22),
    ("SALARY", 0.08),
    ("UTILITIES", 0.08),
    ("RESTAURANT", 0.12),
    ("FUEL", 0.07),
    ("HEALTHCARE", 0.06),
    ("ENTERTAINMENT", 0.07),
    ("TRAVEL", 0.05),
    ("RETAIL", 0.10),
    ("ATM_WITHDRAWAL", 0.08),
    ("TRANSFER", 0.05),
    ("UNKNOWN", 0.02),
]

CHANNELS = [
    ("POS", 0.45),
    ("ACH", 0.20),
    ("ATM", 0.12),
    ("WIRE", 0.05),
    ("MOBILE", 0.10),
    ("ONLINE", 0.08),
]

AMOUNT_RANGES: dict[str, tuple[float, float]] = {
    "SALARY": (1500, 8000),
    "ATM_WITHDRAWAL": (-500, -20),
    "UTILITIES": (-300, -30),
    "GROCERY": (-250, -5),
    "HEALTHCARE": (-800, -10),
    "TRAVEL": (-2000, -50),
    "WIRE": (500, 15000),  # can be in or out
    "TRANSFER": (-2000, 2000),
    "DEFAULT": (-400, -1),
}


def _weighted_choice(options: list[tuple[str, float]]) -> str:
    items, weights = zip(*options)
    return random.choices(items, weights=weights, k=1)[0]


def _amount_for_category(category: str) -> float:
    lo, hi = AMOUNT_RANGES.get(category, AMOUNT_RANGES["DEFAULT"])
    raw = random.triangular(lo, hi, lo + (hi - lo) * 0.25)
    return round(raw, 2)


def _random_date(start: date, end: date) -> date:
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, delta))


def generate_transactions(
    n_rows: int = 1_000_000,
    n_accounts: int = 1_000,
    start_date: date = date(2023, 1, 1),
    end_date: date = date(2024, 12, 31),
    duplicate_rate: float = 0.005,
    seed: int = 42,
) -> list[dict]:
    """
    Generate ``n_rows`` synthetic transactions.

    Parameters
    ----------
    n_rows:         Total number of rows (before duplicate injection).
    n_accounts:     Number of distinct account IDs.
    start_date:     Earliest transaction date.
    end_date:       Latest transaction date.
    duplicate_rate: Fraction of rows to duplicate (tests dedup path).
    seed:           RNG seed for reproducibility.
    """
    random.seed(seed)

    account_ids = [f"ACC-{str(i).zfill(6)}" for i in range(n_accounts)]
    transactions: list[dict] = []

    for _ in range(n_rows):
        category = _weighted_choice(MERCHANT_CATEGORIES)
        channel = _weighted_choice(CHANNELS)
        txn_date = _random_date(start_date, end_date)
        amount = _amount_for_category(category)

        # Salary: force credit + land near 25th
        if category == "SALARY":
            amount = abs(amount)
            txn_date = txn_date.replace(day=min(25, (end_date - start_date).days))

        transactions.append(
            {
                "transaction_id": str(uuid.uuid4()),
                "account_id": random.choice(account_ids),
                "amount": amount,
                "transaction_date": txn_date.isoformat(),
                "merchant_category": category,
                "channel": channel,
            }
        )

    # Inject deliberate duplicates
    n_dupes = max(1, int(n_rows * duplicate_rate))
    dupes = random.choices(transactions, k=n_dupes)
    transactions.extend(dupes)

    # Shuffle so duplicates aren't always at the end
    random.shuffle(transactions)

    return transactions


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic bank transactions")
    parser.add_argument("--rows", type=int, default=1_000_000, help="Number of rows")
    parser.add_argument(
        "--accounts", type=int, default=10_000, help="Number of accounts"
    )
    parser.add_argument("--seed", type=int, default=42, help="RNG seed")
    parser.add_argument(
        "--out",
        type=str,
        default="data/transactions_100k.json",
        help="Output file path",
    )
    args = parser.parse_args()

    print(f"Generating {args.rows:,} transactions across {args.accounts:,} accounts …")
    txns = generate_transactions(
        n_rows=args.rows,
        n_accounts=args.accounts,
        seed=args.seed,
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {"transactions": txns}
    with out_path.open("w") as fh:
        json.dump(payload, fh)

    size_mb = out_path.stat().st_size / 1_048_576
    print(f"✓ Wrote {len(txns):,} rows → {out_path}  ({size_mb:.1f} MB)")
    print()
    print("To POST this file to the running service:")
    print("  curl -s -X POST http://localhost:8000/attributes \\")
    print("       -H 'Content-Type: application/json' \\")
    print(f"       -d @{out_path} | python -m json.tool | head -80")


if __name__ == "__main__":
    main()

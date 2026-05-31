"""
app/normalizer.py - Deduplication & dtype enforcement
======================================================
Converts a list of Pydantic Transaction objects into a typed Polars
DataFrame that the engine can consume without further casting.

Guarantees
----------
* No duplicate transaction_ids (last-write-wins on deterministic sort)
* All dtypes are fixed and documented below
* Column order is stable (engine relies on this)
"""

from __future__ import annotations

import logging
from typing import Sequence

import polars as pl

from app.models import Transaction

logger = logging.getLogger(__name__)

# --- Schema contract
# These are the exact dtypes the engine expects.
# Any upstream change must  update this mapping *and* the
# corresponding engine expressions.

SCHEMA: dict[str, pl.DataType] = {
    "transaction_id": pl.Utf8(),
    "account_id": pl.Utf8(),
    "amount": pl.Float64(),
    "transaction_date": pl.Date(),
    "merchant_category": pl.Utf8(),
    "channel": pl.Utf8(),
}


def normalize(transactions: Sequence[Transaction]) -> pl.DataFrame:
    """
    Accept raw Pydantic Transaction objects and return a clean Polars
    DataFrame.

    Steps
    -----
    1. Serialise to list-of-dicts (fast path via model_dump).
    2. Build a Polars DataFrame with explicit schema.
    3. Deduplicate on transaction_id, keeping the first occurrence after
       deterministic sort (by transaction_date, then transaction_id).

    Parameters
    ----------
    transactions:
        Validated Pydantic objects from the request layer.

    Returns
    -------
    pl.DataFrame
        Clean, typed, deduplicated DataFrame.

    Raises
    ------
    ValueError
        If the resulting DataFrame is empty after deduplication.
    """
    if not transactions:
        raise ValueError("Transaction list is empty")

    # 1. Serialise
    rows = [
        {
            "transaction_id": t.transaction_id,
            "account_id": t.account_id,
            "amount": float(t.amount),  # Decimal to float
            "transaction_date": t.transaction_date,
            "merchant_category": t.merchant_category,
            "channel": t.channel,
        }
        for t in transactions
    ]

    # 2. Build DataFrame
    df = pl.DataFrame(rows, schema=SCHEMA)

    raw_count = len(df)

    # 3. Deterministic dedup
    # Sort first so that first occurence is deterministic regardless
    # of input ordering, then drop duplicate transactions_ids
    df = df.sort(["transaction_date", "transaction_id"]).unique(
        subset=["transaction_id"], keep="first", maintain_order=True
    )
    deduped_count = len(df)
    if deduped_count < raw_count:
        logger.warning(
            "Removed %d duplicate transaction_id(s) - %d rows remain",
            raw_count - deduped_count,
            deduped_count,
        )

    if deduped_count == 0:
        raise ValueError("No transactions remain after deduplication")

    return df

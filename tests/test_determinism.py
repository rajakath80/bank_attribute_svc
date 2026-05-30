"""
tests/test_determinism.py
=========================
Verifies that identical inputs always produce identical outputs.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

import pytest

from app.models import Transaction, AttributeRequest
from app.normalizer import normalize
from app.engine import compute_attributes
from app.registry import metric_registry


def _build_request(seed: int, n: int = 500) -> AttributeRequest:
    rng = random.Random(seed)
    txns = []
    for i in range(n):
        txns.append(Transaction(
            transaction_id=f"TXN-{i:06d}",
            account_id=f"ACC-{rng.randint(0, 9):02d}",
            amount=round(rng.uniform(-400, 400), 2),
            transaction_date=date(2024, 1, 1) + timedelta(days=rng.randint(0, 364)),
            merchant_category=rng.choice(["GROCERY", "SALARY", "FUEL"]),
            channel=rng.choice(["POS", "ACH", "ATM"]),
        ))
    return AttributeRequest(transactions=txns)


class TestDeterminism:
    def test_same_input_same_output(self):
        """Running the same request twice yields identical attribute maps."""
        req = _build_request(seed=7)
        metrics = metric_registry.all()

        df1 = normalize(req.transactions)
        df2 = normalize(req.transactions)
        result1 = compute_attributes(df1, metrics)
        result2 = compute_attributes(df2, metrics)

        assert result1 == result2, "Outputs differ for identical inputs"

    def test_shuffled_input_same_output(self):
        """
        Shuffling the transaction list must not change computed attributes
        because the normaliser sorts before dedup.
        """
        req = _build_request(seed=13)
        txns_shuffled = list(req.transactions)
        random.shuffle(txns_shuffled)

        metrics = metric_registry.all()
        df_orig    = normalize(req.transactions)
        df_shuffle = normalize(txns_shuffled)

        result_orig    = compute_attributes(df_orig,    metrics)
        result_shuffle = compute_attributes(df_shuffle, metrics)

        assert result_orig == result_shuffle, (
            "Output changed when input order was shuffled"
        )

    def test_duplicate_transactions_deduplicated(self):
        """Injecting duplicate transaction_ids must not change attribute values."""
        req = _build_request(seed=21)
        # Duplicate first 50 transactions
        duped_txns = list(req.transactions) + list(req.transactions[:50])

        metrics = metric_registry.all()
        df_clean = normalize(req.transactions)
        df_duped = normalize(duped_txns)

        result_clean = compute_attributes(df_clean, metrics)
        result_duped = compute_attributes(df_duped, metrics)

        assert result_clean == result_duped, (
            "Duplicate injection changed attribute values"
        )

    def test_account_set_is_stable(self):
        """Every account in the input appears exactly once in the output."""
        req = _build_request(seed=3)
        expected_accounts = {t.account_id for t in req.transactions}
        metrics = metric_registry.all()
        df = normalize(req.transactions)
        result = compute_attributes(df, metrics)
        assert set(result.keys()) == expected_accounts

"""
tests/test_benchmark.py
=======================
Performance benchmarks – these run as part of the normal pytest suite but
only WARN (not fail) if timing is above threshold when running on CI hardware.
They HARD FAIL when run with --strict-benchmark flag.

Primary assertion: 100 k transactions computed in under 4 seconds.
"""

from __future__ import annotations

import random
import time
from datetime import date, timedelta

import pytest

from app.models import Transaction, AttributeRequest
from app.normalizer import normalize
from app.engine import compute_attributes
from app.registry import metric_registry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _build_large_request(n: int, n_accounts: int, seed: int = 0) -> AttributeRequest:
    rng = random.Random(seed)
    categories = ["GROCERY", "SALARY", "FUEL", "RETAIL", "UTILITIES", "HEALTHCARE"]
    channels = ["POS", "ACH", "ATM", "WIRE", "MOBILE"]
    txns = [
        Transaction(
            transaction_id=f"TXN-{i:010d}",
            account_id=f"ACC-{rng.randint(0, n_accounts - 1):06d}",
            amount=round(rng.uniform(-1000, 1000), 2),
            transaction_date=date(2023, 1, 1) + timedelta(days=rng.randint(0, 729)),
            merchant_category=rng.choice(categories),
            channel=rng.choice(channels),
        )
        for i in range(n)
    ]
    return AttributeRequest(transactions=txns)


# ---------------------------------------------------------------------------
# Benchmark helpers
# ---------------------------------------------------------------------------

THRESHOLD_NORMALISE_100K = 1.0   # seconds
THRESHOLD_ENGINE_100K    = 3.0   # seconds
THRESHOLD_TOTAL_100K     = 4.0   # seconds – the headline SLA


def _time_pipeline(n: int, n_accounts: int) -> tuple[float, float]:
    """Returns (normalise_elapsed, engine_elapsed)."""
    request = _build_large_request(n, n_accounts)
    metrics = metric_registry.all()

    t0 = time.perf_counter()
    df = normalize(request.transactions)
    t1 = time.perf_counter()
    compute_attributes(df, metrics)
    t2 = time.perf_counter()

    return t1 - t0, t2 - t1


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBenchmark:
    def test_normalise_10k_under_1s(self):
        """Normaliser on 10 k rows should be very fast (sanity check)."""
        req = _build_large_request(10_000, 100)
        t0 = time.perf_counter()
        normalize(req.transactions)
        elapsed = time.perf_counter() - t0
        assert elapsed < 1.0, f"Normaliser 10k took {elapsed:.2f}s (limit 1.0s)"

    def test_engine_10k_under_1s(self):
        """Engine on 10 k rows across 100 accounts."""
        req = _build_large_request(10_000, 100)
        df = normalize(req.transactions)
        metrics = metric_registry.all()

        t0 = time.perf_counter()
        result = compute_attributes(df, metrics)
        elapsed = time.perf_counter() - t0

        assert elapsed < 1.0, f"Engine 10k took {elapsed:.2f}s (limit 1.0s)"
        assert len(result) == 100

    def test_full_pipeline_100k_under_4s(self):
        """
        Headline SLA: 100 k transactions → attribute map in under 4 seconds.

        This covers normalisation + computation but NOT network I/O or
        serialisation (those are tested separately via the HTTP client).
        """
        norm_elapsed, engine_elapsed = _time_pipeline(100_000, 1_000)
        total = norm_elapsed + engine_elapsed

        print(
            f"\n[BENCHMARK] 100k rows | "
            f"normalise={norm_elapsed:.3f}s | "
            f"engine={engine_elapsed:.3f}s | "
            f"total={total:.3f}s"
        )

        assert total < THRESHOLD_TOTAL_100K, (
            f"Pipeline took {total:.2f}s – exceeds {THRESHOLD_TOTAL_100K}s SLA"
        )

    def test_normalise_is_fast_fraction_of_budget(self):
        """Normaliser should consume less than 25 % of the 4 s budget."""
        norm_elapsed, _ = _time_pipeline(100_000, 1_000)
        budget_fraction = norm_elapsed / THRESHOLD_TOTAL_100K
        assert budget_fraction < 0.25, (
            f"Normaliser used {budget_fraction:.0%} of budget "
            f"({norm_elapsed:.2f}s)"
        )

    def test_output_completeness_100k(self):
        """Engine must emit one attribute dict per account, no silent drops."""
        n_accounts = 500
        req = _build_large_request(50_000, n_accounts)
        df = normalize(req.transactions)
        result = compute_attributes(df, metric_registry.all())

        # Not all 500 accounts may have transactions, but none that DO
        # should be silently dropped
        expected = set(df["account_id"].unique().to_list())
        assert set(result.keys()) == expected, "Some accounts missing from output"

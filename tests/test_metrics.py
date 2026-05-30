"""
tests/test_metrics.py
=====================
Unit tests that verify the correctness of each metric's computed values
against hand-calculated expectations.
"""

from __future__ import annotations

from datetime import date, timedelta
import math

import pytest

from app.models import Transaction
from app.normalizer import normalize
from app.engine import compute_attributes
from app.registry import (
    MetricRegistry,
    TransactionVolumeMetric,
    RecencyMetric,
    SpendCategoryMetric,
    ChannelBehaviourMetric,
    CashFlowMetric,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(txns: list[Transaction], *metrics) -> dict:
    """Normalise + compute for a given list of transactions and metrics."""
    reg = MetricRegistry()
    for m in metrics:
        reg.register(m)
    df = normalize(txns)
    return compute_attributes(df, reg.all())


def _txn(**kwargs) -> Transaction:
    defaults = dict(
        transaction_id="TX-001",
        account_id="ACC-A",
        amount=-10.0,
        transaction_date=date(2024, 3, 15),
        merchant_category="GROCERY",
        channel="POS",
    )
    defaults.update(kwargs)
    return Transaction(**defaults)


# ---------------------------------------------------------------------------
# TransactionVolumeMetric
# ---------------------------------------------------------------------------

class TestTransactionVolumeMetric:
    def test_basic_counts(self):
        txns = [
            _txn(transaction_id="T1", amount=-100.0, transaction_date=date(2024, 1, 1)),
            _txn(transaction_id="T2", amount=-200.0, transaction_date=date(2024, 1, 2)),
            _txn(transaction_id="T3", amount=500.0,  transaction_date=date(2024, 1, 3), merchant_category="SALARY"),
        ]
        result = _run(txns, TransactionVolumeMetric())["ACC-A"]

        assert result["txn_count"] == 3
        assert math.isclose(result["total_credit"], 500.0, rel_tol=1e-6)
        assert math.isclose(result["total_debit"], -300.0, rel_tol=1e-6)
        assert math.isclose(result["net_flow"], 200.0, rel_tol=1e-6)
        assert math.isclose(result["avg_txn_amount"], 200.0 / 3, rel_tol=1e-4)

    def test_all_debits(self):
        txns = [
            _txn(transaction_id="T1", amount=-50.0),
            _txn(transaction_id="T2", amount=-75.0),
        ]
        result = _run(txns, TransactionVolumeMetric())["ACC-A"]
        assert result["total_credit"] == 0.0
        assert result["net_flow"] < 0


# ---------------------------------------------------------------------------
# SpendCategoryMetric
# ---------------------------------------------------------------------------

class TestSpendCategoryMetric:
    def test_top_category(self):
        txns = [
            _txn(transaction_id="T1", merchant_category="GROCERY"),
            _txn(transaction_id="T2", merchant_category="GROCERY"),
            _txn(transaction_id="T3", merchant_category="FUEL"),
        ]
        result = _run(txns, SpendCategoryMetric())["ACC-A"]
        assert result["top_category"] == "GROCERY"
        assert result["category_count"] == 2

    def test_salary_credit_sum(self):
        txns = [
            _txn(transaction_id="T1", amount=3000.0,  merchant_category="SALARY"),
            _txn(transaction_id="T2", amount=3000.0,  merchant_category="SALARY"),
            _txn(transaction_id="T3", amount=-100.0,  merchant_category="GROCERY"),
        ]
        result = _run(txns, SpendCategoryMetric())["ACC-A"]
        assert math.isclose(result["salary_credit"], 6000.0, rel_tol=1e-6)

    def test_grocery_spend(self):
        txns = [
            _txn(transaction_id="T1", amount=-40.0,  merchant_category="GROCERY"),
            _txn(transaction_id="T2", amount=-60.0,  merchant_category="GROCERY"),
            _txn(transaction_id="T3", amount=-100.0, merchant_category="FUEL"),
        ]
        result = _run(txns, SpendCategoryMetric())["ACC-A"]
        assert math.isclose(result["grocery_spend"], -100.0, rel_tol=1e-6)


# ---------------------------------------------------------------------------
# ChannelBehaviourMetric
# ---------------------------------------------------------------------------

class TestChannelBehaviourMetric:
    def test_channel_counts(self):
        txns = [
            _txn(transaction_id="T1", channel="POS"),
            _txn(transaction_id="T2", channel="POS"),
            _txn(transaction_id="T3", channel="ACH"),
            _txn(transaction_id="T4", channel="ATM"),
        ]
        result = _run(txns, ChannelBehaviourMetric())["ACC-A"]
        assert result["pos_count"] == 2
        assert result["ach_count"] == 1
        assert result["atm_count"] == 1

    def test_digital_ratio(self):
        txns = [
            _txn(transaction_id="T1", channel="POS"),    # non-digital
            _txn(transaction_id="T2", channel="ATM"),    # non-digital
            _txn(transaction_id="T3", channel="ACH"),    # digital
            _txn(transaction_id="T4", channel="MOBILE"), # digital
        ]
        result = _run(txns, ChannelBehaviourMetric())["ACC-A"]
        assert math.isclose(result["digital_ratio"], 0.5, rel_tol=1e-6)


# ---------------------------------------------------------------------------
# CashFlowMetric
# ---------------------------------------------------------------------------

class TestCashFlowMetric:
    def test_window_filters_correctly(self):
        today_proxy = date(2024, 6, 15)
        # 3 transactions inside the 14-day window, 2 outside
        txns = [
            _txn(transaction_id="T1", amount=-100.0, transaction_date=today_proxy - timedelta(days=5)),
            _txn(transaction_id="T2", amount=-200.0, transaction_date=today_proxy - timedelta(days=10)),
            _txn(transaction_id="T3", amount=500.0,  transaction_date=today_proxy - timedelta(days=2)),
            _txn(transaction_id="T4", amount=-50.0,  transaction_date=today_proxy - timedelta(days=30)),
            _txn(transaction_id="T5", amount=-80.0,  transaction_date=today_proxy - timedelta(days=45)),
        ]
        result = _run(txns, CashFlowMetric(window_days=14))["ACC-A"]
        # Transactions T1, T2, T3 are within 14 days of max date (today_proxy)
        assert result["cashflow_txn_count"] == 3
        assert math.isclose(result["cashflow_net"], 200.0, rel_tol=1e-4)

    def test_all_inside_window(self):
        today_proxy = date(2024, 6, 15)
        txns = [
            _txn(transaction_id="T1", amount=-100.0, transaction_date=today_proxy - timedelta(days=1)),
            _txn(transaction_id="T2", amount=400.0,  transaction_date=today_proxy - timedelta(days=2)),
        ]
        result = _run(txns, CashFlowMetric(window_days=30))["ACC-A"]
        assert result["cashflow_txn_count"] == 2


# ---------------------------------------------------------------------------
# Multi-account isolation
# ---------------------------------------------------------------------------

class TestMultiAccountIsolation:
    def test_accounts_do_not_bleed(self):
        txns = [
            _txn(transaction_id="T1", account_id="ACC-A", amount=-100.0),
            _txn(transaction_id="T2", account_id="ACC-A", amount=-200.0),
            _txn(transaction_id="T3", account_id="ACC-B", amount=5000.0, merchant_category="SALARY"),
        ]
        result = _run(txns, TransactionVolumeMetric())
        assert result["ACC-A"]["txn_count"] == 2
        assert result["ACC-B"]["txn_count"] == 1
        assert result["ACC-A"]["total_credit"] == 0.0
        assert result["ACC-B"]["total_debit"] == 0.0


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class TestMetricRegistry:
    def test_duplicate_registration_raises(self):
        reg = MetricRegistry()
        reg.register(TransactionVolumeMetric())
        with pytest.raises(ValueError, match="already registered"):
            reg.register(TransactionVolumeMetric())

    def test_replace_works(self):
        reg = MetricRegistry()
        reg.register(TransactionVolumeMetric())
        reg.replace(TransactionVolumeMetric())  # should not raise
        assert len(reg.all()) == 1

    def test_dynamic_registration(self):
        """Add CashFlowMetric(window_days=14) and verify it appears in output."""
        reg = MetricRegistry()
        reg.register(CashFlowMetric(window_days=14))
        assert reg.get("cash_flow") is not None

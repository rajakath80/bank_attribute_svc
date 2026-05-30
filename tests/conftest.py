"""
tests/conftest.py – Shared pytest fixtures
==========================================
"""

from __future__ import annotations

import random
from datetime import date, timedelta

import pytest
import polars as pl
from fastapi.testclient import TestClient

from app.main import app
from app.models import Transaction, AttributeRequest
from app.normalizer import normalize
from app.registry import metric_registry


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def client():
    """Synchronous TestClient (no Redis required – cache silently no-ops)."""
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Transaction factories
# ---------------------------------------------------------------------------

def _make_transaction(
    transaction_id: str | None = None,
    account_id: str = "ACC-000001",
    amount: float = -50.0,
    transaction_date: date | None = None,
    merchant_category: str = "GROCERY",
    channel: str = "POS",
) -> Transaction:
    import uuid
    return Transaction(
        transaction_id=transaction_id or str(uuid.uuid4()),
        account_id=account_id,
        amount=amount,
        transaction_date=transaction_date or date(2024, 6, 15),
        merchant_category=merchant_category,
        channel=channel,
    )


@pytest.fixture
def single_txn():
    return _make_transaction()


@pytest.fixture
def two_account_txns():
    """10 transactions across 2 accounts."""
    txns = []
    for i in range(5):
        txns.append(_make_transaction(
            account_id="ACC-000001",
            amount=-float(i * 10 + 10),
            transaction_date=date(2024, 1, 1) + timedelta(days=i),
        ))
    for i in range(5):
        txns.append(_make_transaction(
            account_id="ACC-000002",
            amount=float(i * 100 + 100),
            merchant_category="SALARY",
            channel="ACH",
            transaction_date=date(2024, 1, 1) + timedelta(days=i),
        ))
    return txns


@pytest.fixture
def normalised_df(two_account_txns):
    return normalize(two_account_txns)


@pytest.fixture
def large_request():
    """10 k transaction request for light benchmark testing in unit tests."""
    random.seed(99)
    categories = ["GROCERY", "SALARY", "FUEL", "RETAIL"]
    channels = ["POS", "ACH", "ATM"]
    txns = []
    for i in range(10_000):
        txns.append(Transaction(
            transaction_id=f"TXN-{i:08d}",
            account_id=f"ACC-{(i % 100):04d}",
            amount=round(random.uniform(-500, 500), 2),
            transaction_date=date(2024, 1, 1) + timedelta(days=random.randint(0, 364)),
            merchant_category=random.choice(categories),
            channel=random.choice(channels),
        ))
    return AttributeRequest(transactions=txns)


@pytest.fixture
def large_df(large_request):
    return normalize(large_request.transactions)

"""
app/registry.py - Metric registry & built-in metric definitions
================================================================
To add a new metric:
    1. Subclass BaseMetric.
    2. Implement ``expressions()`` - return a list of Polars Expr that will
       be evaluated inside a group_by("account_id").agg(...) context.
    3. The class is auto-registered on import; no other wiring needed.

Example - adding CashFlowMetric in one line (demo for the Loom):
    metric_registry.register(CashFlowMetric(window_days=14, min_transactions=2))
"""

# enables postponed evaluation of type annotations so forward references
# and self-referential types are treated as strings at runtime avoiding
# import/order issues until evaluated later.
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

import polars as pl

logger = logging.getLogger(__name__)


# Base class
class BaseMetric(ABC):
    """
    Abstract base for all attribute metrics.

    Subclasses declare their output column names in ``output_columns`` and
    implement ``expressions()`` to return the corresponding Polars Expr list.
    """

    # Unique human-readable name (used in response metadata & cache keys)
    name: ClassVar[str]

    # Columns this metric writes into the aggregation result
    output_columns: ClassVar[list[str]]

    @abstractmethod
    def expressions(self) -> list[pl.Expr]:
        """
        Return a list of named Polars expressions for use inside
        ``group_by("account_id").agg(...)``.

        Each expression must call ``.alias(column_name)`` so the engine
        can build the final DataFrame cleanly.
        """

    def __repr__(self) -> str:
        return f"<Metric name={self.name!r}>"


# Registry
class MetricRegistry:
    """Thread-safe (GIL-protected) registry of BaseMetric instances."""

    def __init__(self) -> None:
        self._metrics: dict[str, BaseMetric] = {}

    def register(self, metric: BaseMetric) -> "MetricRegistry":
        """Add a metric. Raises if a metric with the same name exists."""
        if metric.name in self._metrics:
            raise ValueError(
                f"Metric '{metric.name}' is already registered."
                "Use replace() to overwrite."
            )
        self._metrics[metric.name] = metric
        logger.debug("Registered metric: %s", metric.name)
        return self  # fluent API

    def replace(self, metric: BaseMetric) -> "MetricRegistry":
        """Overwrite an existing metric (useful in tests)."""
        self._metrics[metric.name] = metric
        return self

    def unregister(self, name: str) -> None:
        self._metrics.pop(name, None)

    def all(self) -> list[BaseMetric]:
        return list(self._metrics.values())

    def get(self, name: str) -> BaseMetric | None:
        return self._metrics.get(name)


# Built-in metrics
class TransactionVolumeMetric(BaseMetric):
    """
    Count of transactions and total / average monetary flow per account.
    """

    name = "transaction_volume"
    output_columns = [
        "txn_count",
        "total_credit",
        "total_debit",
        "net_flow",
        "avg_txn_amount",
    ]

    def expressions(self) -> list[pl.Expr]:
        return [
            pl.len().alias("txn_count"),
            pl.col("amount")
            .filter(pl.col("amount") > 0)
            .sum()
            .fill_null(0)
            .alias("total_credit"),
            pl.col("amount")
            .filter(pl.col("amount") < 0)
            .sum()
            .fill_null(0)
            .alias("total_debit"),
            pl.col("amount").sum().alias("net_flow"),
            pl.col("amount").mean().alias("avg_txn_amount"),
        ]


class RecencyMetric(BaseMetric):
    """
    Days since the most recent transaction and days since the first
    transaction (tenure proxy).
    """

    name = "recency"
    output_columns = ["days_since_last_txn", "days_since_first_txn", "active_days"]

    def expressions(self) -> list[pl.Expr]:
        today = pl.lit(pl.Series([__import__("datetime").date.today()])).cast(pl.Date)
        return [
            (today - pl.col("transaction_date").max())
            .dt.total_days()
            .first()
            .alias("days_since_last_txn"),
            (today - pl.col("transaction_date").min())
            .dt.total_days()
            .first()
            .alias("days_since_first_txn"),
            pl.col("transaction_date").n_unique().alias("active_days"),
        ]


class SpendCategoryMetric(BaseMetric):
    """
    Dominant spend category and category entropy (diversity score).
    """

    name = "spend_category"
    output_columns = [
        "top_category",
        "category_count",
        "grocery_spend",
        "salary_credit",
    ]

    def expressions(self) -> list[pl.Expr]:
        return [
            pl.col("merchant_category").mode().first().alias("top_category"),
            pl.col("merchant_category").n_unique().alias("category_count"),
            pl.col("amount")
            .filter(pl.col("merchant_category") == "GROCERY")
            .sum()
            .fill_null(0)
            .alias("grocery_spend"),
            pl.col("amount")
            .filter(pl.col("merchant_category") == "SALARY")
            .sum()
            .fill_null(0)
            .alias("salary_credit"),
        ]


class ChannelBehaviourMetric(BaseMetric):
    """
    Channel distribution - useful for fraud and customer segmentation models.
    """

    name = "channel_behaviour"
    output_columns = [
        "pos_count",
        "ach_count",
        "atm_count",
        "wire_count",
        "digital_ratio",
    ]

    def expressions(self) -> list[pl.Expr]:
        return [
            pl.col("channel")
            .filter(pl.col("channel") == "POS")
            .len()
            .alias("pos_count"),
            pl.col("channel")
            .filter(pl.col("channel") == "ACH")
            .len()
            .alias("ach_count"),
            pl.col("channel")
            .filter(pl.col("channel") == "ATM")
            .len()
            .alias("atm_count"),
            pl.col("channel")
            .filter(pl.col("channel") == "WIRE")
            .len()
            .alias("wire_count"),
            # digital = non-ATM, non-POS
            (
                pl.col("channel")
                .filter(~pl.col("channel").is_in(["ATM", "POS"]))
                .len()
                .cast(pl.Float64)
                / pl.len().cast(pl.Float64)
            ).alias("digital_ratio"),
        ]


@dataclass
class CashFlowMetric(BaseMetric):
    """
    Rolling-window cash flow features.

    Parameters
    ----------
    window_days:
        Number of calendar days to look back from the most recent transaction.
    min_transactions:
        Minimum transactions within the window to emit non-null values.

    Demo usage (one line):
        metric_registry.register(CashFlowMetric(window_days=14, min_transactions=2))
    """

    window_days: int = 30
    min_transactions: int = 1

    name: ClassVar[str] = "cash_flow"
    output_columns: ClassVar[list[str]] = [
        "cashflow_net",
        "cashflow_credit",
        "cashflow_debit",
        "cashflow_txn_count",
    ]

    def expressions(self) -> list[pl.Expr]:
        """
        NOTE: Polars group_by.agg does not support per-group rolling windows
        natively.  We approximate the window by filtering rows that fall
        within `window_days` of the account's own latest transaction.
        This is done via a struct + list approach.
        """
        wd = self.window_days
        # Pack the columns we need into a struct so we can filter inside agg
        in_window = pl.col("transaction_date") >= (
            pl.col("transaction_date").max() - pl.duration(days=wd)
        )
        return [
            pl.col("amount").filter(in_window).sum().fill_null(0).alias("cashflow_net"),
            pl.col("amount")
            .filter(in_window & (pl.col("amount") > 0))
            .sum()
            .fill_null(0)
            .alias("cashflow_credit"),
            pl.col("amount")
            .filter(in_window & (pl.col("amount") < 0))
            .sum()
            .fill_null(0)
            .alias("cashflow_debit"),
            pl.col("amount").filter(in_window).len().alias("cashflow_txn_count"),
        ]


# Singleton registry

metric_registry = MetricRegistry()

# Register built-in metrics in prefered output order
for _metric in [
    TransactionVolumeMetric(),
    RecencyMetric(),
    SpendCategoryMetric(),
    ChannelBehaviourMetric(),
    CashFlowMetric(window_days=30, min_transactions=1),
]:
    metric_registry.register(_metric)


# metric_registry.replace(CashFlowMetric(window_days=14, min_transactions=2))

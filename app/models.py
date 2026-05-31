"""
app/models.py - Pydantic v2 request / response schemas
=======================================================
Strict typing on the way in keeps the engine layer clean and ensures
deterministic serialisation on the way out.
"""

from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class Transaction(BaseModel):
    """
    Single raw transaction row.

    All monetary amounts are Decimal to avoid floating-point drift during
    ingestion; the normaliser converts them to float64 before handing off
    to Polars.
    """

    transaction_id: str = Field(..., description="Globally unique transaction ID")
    account_id: str = Field(..., description="Account the transaction belongs to")
    amount: Decimal = Field(
        ..., description="Transaction amount -> positive = credit, negative = debit"
    )
    transaction_date: date = Field(..., description="ISO-8601 date of the transaction")
    merchant_category: str = Field(
        default="UNKNOWN", description="MCC-style category string, e.g. GROCERY, SALARY"
    )
    channel: str = Field(
        default="UNKNOWN", description="Payment channel, e.g. POS, ACH, WIRE, ATM"
    )

    @field_validator("account_id", "transaction_id")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        return v.strip()

    @field_validator("merchant_category", "channel")
    @classmethod
    def upper_and_strip(cls, v: str) -> str:
        return v.strip().upper()

    model_config = {"frozen": True}  # hashable for dedup


class AttributeRequest(BaseModel):
    """
    Batch request - up to MAX_BATCH_SIZE transactions in one call.
    """

    transactions: list[Transaction] = Field(
        ..., min_length=1, description="Raw transaction rows to process"
    )

    @model_validator(mode="after")
    def check_batch_size(self) -> "AttributeRequest":
        from app.core.config import settings

        limit = settings.max_batch_size
        if len(self.transactions) > limit:
            raise ValueError(
                f"Batch size {len(self.transactions)} exceeds limit {limit}"
            )
        return self


class AttributeResponse(BaseModel):
    """
    Per-account attribute vectors + request metadata.

    ``attributes`` maps account_id → {metric_name: value, ...}
    """

    attributes: dict[str, dict[str, Any]] = Field(
        ..., description="Keyed by account_id, each value is a flat attribute map"
    )
    meta: dict[str, Any] = Field(
        ..., description="Request-level metadata (timing, cache status, counts)"
    )

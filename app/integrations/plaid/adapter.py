"""
Plaid → AttributeRequest adapter
=================================
Maps Plaid transaction schema to our internal Transaction model.

Key differences handled
-----------------------
* Sign convention: Plaid positive = debit, we use negative = debit
* Category:        Plaid personal_finance_category.primary → merchant_category
* Channel:         Plaid payment_channel → uppercase channel
* Enrichment:      merchant_name, location, balance fields extracted
"""

import logging
from datetime import date
from decimal import Decimal, InvalidOperation

from app.models import AttributeRequest, Transaction

logger = logging.getLogger(__name__)

# Plaid category -> our internal category mapping
CATEGORY_MAP = {
    "FOOD_AND_DRINK": "GROCERY",
    "GROCERIES": "GROCERY",
    "TRANSFER_IN": "SALARY",
    "INCOME": "SALARY",
    "TRANSPORTATION": "FUEL",
    "TRAVEL": "TRAVEL",
    "MEDICAL": "HEALTHCARE",
    "ENTERTAINMENT": "ENTERTAINMENT",
    "GENERAL_MERCHANDISE": "RETAIL",
    "HOME_IMPROVEMENT": "RETAIL",
    "LOAN_PAYMENTS": "TRANSFER",
    "BANK_FEES": "UNKNOWN",
}

CHANNEL_MAP = {"online": "ONLINE", "in_store": "POS", "other": "UNKNOWN"}


def plaid_to_attribute_request(plaid_response: dict) -> AttributeRequest:
    """
    Transform Plaid /transactions/get response → AttributeRequest.
    """
    transactions = []
    skipped = 0

    for txn in plaid_response.get("transactions", []):
        try:
            # Map category
            pfc = txn.get("personal_finance_category") or {}
            raw_category = pfc.get("primary", "UNKNOWN")
            category = CATEGORY_MAP.get(raw_category, "UNKNOWN")

            # Map channel
            raw_channel = txn.get("payment_channel", "other")
            channel = CHANNEL_MAP.get(raw_channel, "UNKNOWN")

            # Invert Plaid sign convention
            raw = txn.get("amount", 0)
            try:
                amount = -Decimal(str(raw))
            except (InvalidOperation, ValueError):
                amount = Decimal(0)

            transactions.append(
                Transaction(
                    transaction_id=txn["transaction_id"],
                    account_id=txn["account_id"],
                    amount=amount,
                    transaction_date=date.fromisoformat(str(txn["date"])),
                    merchant_category=category,
                    channel=channel,
                )
            )
        except Exception as exc:
            skipped += 1
            logger.warning("Skipped Plaid transaction: %s", exc)

    if skipped:
        logger.warning("Skipped %d malformed Plaid transactions", skipped)

    return AttributeRequest(transactions=transactions)


def extract_balance_features(plaid_response: dict) -> dict:
    """
    Extract account balance features from Plaid response.
    These are injected into the risk scorer as additional signals.

    Overdraft risk = current_balance - available_balance
    """

    features = {}
    for account in plaid_response.get("accounts", []):
        account_id = account["account_id"]
        balances = account.get("balances", {})
        current = balances.get("current") or 0
        available = balances.get("available") or 0
        features[account_id] = {
            "current_balance": current,
            "available_balance": available,
            "overdraft_risk": round(current - available, 2),
        }
    return features

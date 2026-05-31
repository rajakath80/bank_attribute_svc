"""
Plaid client wrapper
====================
Handles authentication and transaction fetching from Plaid sandbox/production.
All credentials via environment variables.
"""

import logging
import time
from datetime import date, timedelta

import plaid
from plaid.api import plaid_api
from plaid.model.item_public_token_exchange_request import (
    ItemPublicTokenExchangeRequest,
)
from plaid.model.products import Products
from plaid.model.sandbox_public_token_create_request import (
    SandboxPublicTokenCreateRequest,
)
from plaid.model.transactions_get_request import TransactionsGetRequest
from plaid.model.transactions_get_request_options import TransactionsGetRequestOptions

from app.core.config import settings

# from plaid.model.country_code import CountryCode

logger = logging.getLogger(__name__)

PLAID_ENV_MAP = {
    "sandbox": plaid.Environment.Sandbox,
    "production": plaid.Environment.Production,
}


def get_plaid_client() -> plaid_api.PlaidApi:
    configuration = plaid.Configuration(
        host=PLAID_ENV_MAP.get(settings.plaid_env),
        api_key={"clientId": settings.plaid_client_id, "secret": settings.plaid_secret},
    )
    return plaid_api.PlaidApi(plaid.ApiClient(configuration))


def get_sandbox_access_token() -> str:
    """
    Create a sandbox access token using Plaid test credentials.
    In production this comes from the Link UI OAuth flow.
    """
    client = get_plaid_client()

    # Create sandbox public token
    pt_request = SandboxPublicTokenCreateRequest(
        institution_id="ins_109509", initial_products=[Products("transactions")]
    )
    pt_response = client.sandbox_public_token_create(pt_request)

    # Exchange for access token
    exchange_request = ItemPublicTokenExchangeRequest(
        public_token=pt_response.public_token
    )
    exchange_response = client.item_public_token_exchange(exchange_request)
    return exchange_response.access_token


def fetch_plaid_transactions(access_token: str, days_back: int = 90) -> dict:
    """
    Fetch transactions from Plaid for the given access token.
    Returns raw Plaid response dict.
    """
    client = get_plaid_client()
    start_date = date.today() - timedelta(days=days_back)
    end_date = date.today()

    request = TransactionsGetRequest(
        access_token=access_token,
        start_date=start_date,
        end_date=end_date,
        options=TransactionsGetRequestOptions(count=500),
    )

    # Retry up to 5 times - Plaid sandbox needs time to prepare transactions
    for attempt in range(5):
        try:
            response = client.transactions_get(request)
            logger.info(
                "Fetched %d Plaid transactions (%s -> %s)",
                len(response.transactions),
                start_date,
                end_date,
            )
            return response.to_dict()
        except plaid.ApiException as e:
            if "PRODUCT_NOT_READY" in str(e):
                logger.info(
                    "Plaid not ready, retrying in 2s (attempt %d/5)", attempt + 1
                )
                time.sleep(2)
            else:
                raise

    raise RuntimeError("Plaid transactions not ready after 5 retries")

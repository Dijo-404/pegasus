"""Composition root: the only place that wires interfaces to concrete adapters."""

from pathlib import Path

from pegasus.application.commerce_service import CommerceService
from pegasus.application.ports import CommerceProvider, PaymentVerifier, X402PaymentProvider
from pegasus.application.private_checkout_service import PrivateCheckoutService
from pegasus.application.x402_service import X402Service
from pegasus.infrastructure.persistence.sqlite_repository import SQLiteRepository
from pegasus.infrastructure.providers.bitrefill_client import BitrefillClient
from pegasus.infrastructure.providers.zcash_client import ZcashClient
from pegasus.infrastructure.providers.x402_client import X402Client
from pegasus.infrastructure.security.hmac_grant_authority import HmacGrantAuthority
from pegasus.infrastructure.settings import Settings
from pegasus.presentation.http.app import build_http_app
from pegasus.presentation.http.settings import HttpSettings


def create_app(
    settings: Settings | None = None,
    provider: CommerceProvider | None = None,
    zcash: PaymentVerifier | None = None,
    x402: X402PaymentProvider | None = None,
):
    settings = settings or Settings.from_env()
    repository = SQLiteRepository(settings.database_path, settings.data_key)
    commerce_provider = provider if provider is not None else BitrefillClient(settings.bitrefill_api_key)
    payment_verifier = (
        zcash
        if zcash is not None
        else ZcashClient(
            settings.zcash_graphql_url,
            settings.zcash_account_id,
            settings.zcash_confirmations,
        )
    )
    commerce = CommerceService(
        settings.commerce_policy, repository, commerce_provider, HmacGrantAuthority(settings.grant_secret)
    )
    private_checkout = PrivateCheckoutService(settings.private_checkout_policy, repository, payment_verifier)
    api_payment_provider = (
        x402 if x402 is not None else X402Client(settings.x402_private_key_file, settings.x402_rpc_url)
    )
    api_payments = X402Service(
        settings.x402_policy, repository, api_payment_provider,
        HmacGrantAuthority(settings.grant_secret, expected_action="x402.pay_request"),
    )
    http_settings = HttpSettings(
        owner_token=settings.owner_token,
        agent_token=settings.agent_token,
        http_allowed_hosts=settings.http_allowed_hosts,
        bitrefill_configured=bool(settings.bitrefill_api_key),
        zcash_configured=settings.zcash_enabled,
        max_purchase_minor=settings.max_purchase_minor,
        max_daily_minor=settings.max_daily_minor,
        allowed_products=settings.allowed_products,
        allowed_countries=settings.allowed_countries,
        zcash_amount_zats=settings.zcash_amount_zats,
        static_directory=Path(__file__).parent / "presentation" / "web",
        x402_configured=settings.x402_enabled,
        x402_allowed_origins=settings.x402_allowed_origins,
        x402_allowed_payees=settings.x402_allowed_payees,
    )
    return build_http_app(commerce, private_checkout, http_settings, api_payments)

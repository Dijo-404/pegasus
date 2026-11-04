"""Configuration required by the HTTP interface, supplied by the composition root."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class HttpSettings:
    owner_token: str
    agent_token: str
    bitrefill_configured: bool
    zcash_configured: bool
    max_purchase_minor: int
    max_daily_minor: int
    allowed_products: frozenset[str]
    allowed_countries: frozenset[str]
    zcash_amount_zats: int
    static_directory: Path

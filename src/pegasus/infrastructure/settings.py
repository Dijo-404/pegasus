from dataclasses import dataclass, field
import ipaddress
import os
import re

from cryptography.fernet import Fernet
from dotenv import load_dotenv

from pegasus.domain.commerce_policy import CommercePolicy
from pegasus.domain.private_checkout_policy import PrivateCheckoutPolicy


def csv(value: str) -> frozenset[str]:
    return frozenset(part.strip() for part in value.split(",") if part.strip())


def valid_http_host(host: str) -> bool:
    """Allow explicit DNS names and IP literals, never schemes, ports or wildcards."""
    if not isinstance(host, str) or not host or host != host.lower() or len(host) > 253:
        return False
    if host.startswith("[") and host.endswith("]"):
        try:
            return isinstance(ipaddress.ip_address(host[1:-1]), ipaddress.IPv6Address)
        except ValueError:
            return False
    return all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in host.split("."))


@dataclass(frozen=True)
class Settings:
    owner_token: str
    agent_token: str
    grant_secret: str
    data_key: str
    http_allowed_hosts: frozenset[str] = field(
        default_factory=lambda: csv("localhost,127.0.0.1,[::1],testserver")
    )
    database_path: str = ".local/pegasus.db"
    bitrefill_api_key: str = ""
    max_purchase_minor: int = 500
    max_daily_minor: int = 1000
    allowed_products: frozenset[str] = field(default_factory=lambda: csv("airtel-india,delos-syldavia"))
    allowed_countries: frozenset[str] = field(default_factory=lambda: csv("IN"))
    allowed_emails: frozenset[str] = field(default_factory=frozenset)
    allowed_recipients: frozenset[str] = field(default_factory=frozenset)
    quote_ttl_seconds: int = 300
    grant_ttl_seconds: int = 90
    zcash_enabled: bool = False
    zcash_graphql_url: str = "http://127.0.0.1:8000/graphql"
    zcash_account_id: int = 1
    zcash_confirmations: int = 1
    zcash_amount_zats: int = 100000

    def __post_init__(self):
        for name in ("owner_token", "agent_token", "grant_secret"):
            if len(getattr(self, name)) < 32:
                raise ValueError(
                    f"{name.upper()} must contain at least 32 characters; run scripts/setup_environment.py"
                )
        if self.owner_token == self.agent_token:
            raise ValueError("Owner and agent tokens must be different")
        if not self.http_allowed_hosts or not all(valid_http_host(host) for host in self.http_allowed_hosts):
            raise ValueError("HTTP_ALLOWED_HOSTS must list explicit lowercase hostnames or IP addresses")
        Fernet(self.data_key.encode())
        if (
            min(
                self.max_purchase_minor,
                self.max_daily_minor,
                self.quote_ttl_seconds,
                self.grant_ttl_seconds,
                self.zcash_account_id,
                self.zcash_confirmations,
                self.zcash_amount_zats,
            )
            <= 0
        ):
            raise ValueError("Limits, timeouts, account id and confirmations must be positive")
        if self.max_purchase_minor > self.max_daily_minor:
            raise ValueError("Per-purchase cap cannot exceed daily cap")

    @property
    def commerce_policy(self) -> CommercePolicy:
        names = CommercePolicy.__dataclass_fields__
        return CommercePolicy(**{name: getattr(self, name) for name in names})

    @property
    def private_checkout_policy(self) -> PrivateCheckoutPolicy:
        return PrivateCheckoutPolicy(enabled=self.zcash_enabled, amount_zats=self.zcash_amount_zats)

    @classmethod
    def from_env(cls):
        load_dotenv()
        values = {}
        for name, info in cls.__dataclass_fields__.items():
            value = os.environ.get(name.upper())
            if value is None:
                continue
            if name.startswith("allowed_") or name == "http_allowed_hosts":
                values[name] = csv(value)
            elif info.type is int:
                values[name] = int(value)
            elif info.type is bool:
                if value.lower() not in {"true", "false"}:
                    raise ValueError(f"{name.upper()} must be true or false")
                values[name] = value.lower() == "true"
            else:
                values[name] = value
        for name in ("owner_token", "agent_token", "grant_secret", "data_key"):
            values.setdefault(name, "")
        return cls(**values)

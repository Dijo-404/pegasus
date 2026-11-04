"""Validated HTTP request bodies. Domain policies remain in the application."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EmptyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PurchaseProposalRequest(EmptyRequest):
    product_id: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_-]+$")
    package_value: str = Field(min_length=1, max_length=120)
    country: str = Field(pattern=r"^[A-Z]{2}$")
    recipient: str = Field(default="", max_length=254)
    email: str = Field(max_length=254, pattern=r"^(?:|[^\s@]+@[^\s@]+\.[^\s@]+)$")
    receipt_mode: Literal["email", "provider_account"] = "email"
    receipt_account_reference: str | None = Field(default=None, pattern=r"^sha256:[a-f0-9]{64}$")
    payment_method: str = Field(max_length=40)
    max_total_minor: int = Field(gt=0, le=100000)


class PurchaseApprovalRequest(EmptyRequest):
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class PurchaseExecutionRequest(EmptyRequest):
    grant: str = Field(min_length=10, max_length=8192)


class ApiPaymentProposalRequest(EmptyRequest):
    url: str = Field(min_length=8, max_length=2048)
    max_total_minor: int = Field(gt=0, le=100000)

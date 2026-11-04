"""Separate local owner and agent credentials at the HTTP boundary."""

import hmac

from fastapi import Request

from pegasus.domain.exceptions import Denied
from .settings import HttpSettings


class HttpAuthentication:
    def __init__(self, settings: HttpSettings):
        self.settings = settings

    def actor(self, request: Request) -> str:
        authorization = request.headers.get("authorization", "")
        token = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""
        if hmac.compare_digest(token.encode(), self.settings.owner_token.encode()):
            return "owner"
        if hmac.compare_digest(token.encode(), self.settings.agent_token.encode()):
            return "agent"
        raise Denied("UNAUTHORIZED", "A local owner or agent bearer token is required.")

    def owner(self, request: Request) -> str:
        role = self.actor(request)
        if role != "owner":
            raise Denied("OWNER_REQUIRED", "Exact purchase approval requires the separate owner credential.")
        return role

"""HMAC adapter for short-lived execution grants."""

import base64
import hmac
import json
import time

from pegasus.domain.authorization_policy import GRANT_ISSUER
from pegasus.domain.canonicalization import canonical
from pegasus.domain.exceptions import Denied


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


class HmacGrantAuthority:
    def __init__(self, secret: str, expected_action: str = "bitrefill.create_invoice"):
        self._secret = secret.encode()
        self._expected_action = expected_action

    def sign(self, claims: dict) -> str:
        body = _encode(canonical(claims))
        return body + "." + _encode(hmac.digest(self._secret, body.encode(), "sha256"))

    def verify(self, token: str) -> dict:
        try:
            body, signature = token.split(".")
            expected = _encode(hmac.digest(self._secret, body.encode(), "sha256"))
            if not hmac.compare_digest(signature, expected):
                raise ValueError()
            claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
            now = int(time.time())
            if claims["iss"] != GRANT_ISSUER or claims["aud"] != "execution-gateway":
                raise ValueError()
            if claims["action"] != self._expected_action or claims["v"] != 1:
                raise ValueError()
            if claims["exp"] <= now or claims["nbf"] > now:
                raise Denied("GRANT_EXPIRED", "This approval expired. Create a fresh intent.")
            return claims
        except Denied:
            raise
        except (ValueError, KeyError, TypeError):
            raise Denied("INVALID_GRANT", "Invalid execution grant.") from None

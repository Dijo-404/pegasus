import base64
import hashlib
import hmac
import json
import time

from .errors import Denied


def canonical(value: dict) -> bytes:
    """v1: only authority-owned JSON primitives; amounts are integer minor units."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(value: dict) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def sign(claims: dict, secret: str) -> str:
    body = encode(canonical(claims))
    return body + "." + encode(hmac.digest(secret.encode(), body.encode(), "sha256"))


def verify(token: str, secret: str) -> dict:
    try:
        body, signature = token.split(".")
        expected = encode(hmac.digest(secret.encode(), body.encode(), "sha256"))
        if not hmac.compare_digest(signature, expected):
            raise ValueError()
        claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        now = int(time.time())
        if claims["iss"] != "veilagent" or claims["aud"] != "execution-gateway":
            raise ValueError()
        if claims["action"] != "bitrefill.create_invoice" or claims["v"] != 1:
            raise ValueError()
        if claims["exp"] <= now or claims["nbf"] > now:
            raise Denied("GRANT_EXPIRED", "This approval expired. Create a fresh intent.")
        return claims
    except Denied:
        raise
    except (ValueError, KeyError, TypeError):
        raise Denied("INVALID_GRANT", "Invalid execution grant.") from None

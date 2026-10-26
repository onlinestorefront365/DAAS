import hashlib
import hmac
import ipaddress
import secrets
import socket
from urllib.parse import urlparse

KEY_PREFIX = "dk_live_"


def generate_api_key() -> tuple[str, str, str]:
    """Return (plaintext, display_prefix, sha256_hash). Only the hash is stored."""
    plaintext = KEY_PREFIX + secrets.token_urlsafe(32)
    return plaintext, plaintext[: len(KEY_PREFIX) + 6], hash_api_key(plaintext)


def hash_api_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


def generate_webhook_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(24)


def sign_payload(secret: str, timestamp: int, body: bytes) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return f"t={timestamp},v1={mac.hexdigest()}"


class UnsafeWebhookURL(ValueError):
    pass


def check_webhook_url(url: str, allow_private: bool = False) -> None:
    """Reject non-HTTPS URLs and hosts resolving to internal addresses (SSRF guard)."""
    parsed = urlparse(url)
    if parsed.scheme != "https" and not (allow_private and parsed.scheme == "http"):
        raise UnsafeWebhookURL("webhook_url must use https")
    if not parsed.hostname:
        raise UnsafeWebhookURL("webhook_url has no host")
    if allow_private:
        return
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeWebhookURL(f"cannot resolve {parsed.hostname}") from exc
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        if not addr.is_global:
            raise UnsafeWebhookURL("webhook_url resolves to a non-public address")

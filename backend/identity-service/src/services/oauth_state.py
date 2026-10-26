"""Signed, self-contained, Redis-free OAuth ``state``.

The callback always lands on the ONE fixed apex URL registered with every
provider, so everything the callback needs to get the user back where they
started has to travel inside ``state`` itself: originating host, post-auth
redirect path, intent, provider, and the browser-binding hashes. That makes it
a bearer token in a query string, so it is HMAC-signed with a domain-separated
subkey and carries its own short expiry.
"""

from __future__ import annotations

import base64
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from src.core import key_derivation
from src.core.config import Settings, settings
from src.services.tickets import guard_digest


@dataclass(frozen=True)
class StatePayload:
    """Decoded, verified contents of a signed OAuth ``state`` parameter.

    ``action`` is ``"login"`` or ``"link"``. ``csrf`` and ``guard_hash`` (JSON key
    ``"lg"``, present only for a flow that bounced through a custom domain via
    ``oauth-login.ts``) are SHA-256 hex digests of the raw CSRF and
    ``owt_xdomain_guard`` cookies, never the raw values. Nothing here compares
    them: the flow layer checks ``csrf`` against the raw cookie at the callback,
    and ``guard_hash`` is stored on the cross-domain ticket and checked
    (constant-time) at redemption (``sso_exchange``/``link_complete``).
    """

    origin: str
    redirect: str
    action: str
    provider: str
    nonce: str
    exp: int
    csrf: str
    guard_hash: str | None = None


class OAuthStateCodec:
    """Signed, self-contained, Redis-free OAuth ``state``."""

    def __init__(self, *, config: Settings = settings) -> None:
        self.config = config
        # Domain-separated subkey, never the raw JWT secret. States live minutes,
        # so changing the derivation needs no migration: an in-flight state just
        # fails verification and the user retries the redirect.
        self._key = key_derivation.oauth_state_key(config.JWT_SECRET_KEY)
        self._pkce_key = key_derivation.oauth_pkce_key(config.JWT_SECRET_KEY)

    @property
    def ttl_seconds(self) -> int:
        """Lifetime of a freshly signed state."""
        return max(self.config.OAUTH_STATE_EXPIRE_MINUTES, 1) * 60

    @staticmethod
    def _encode_part(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")

    @staticmethod
    def _decode_part(encoded: str) -> bytes:
        padded = encoded + ("=" * ((4 - len(encoded) % 4) % 4))
        return base64.urlsafe_b64decode(padded.encode("utf-8"))

    def _signature(self, payload_json: bytes) -> str:
        digest = bytes.fromhex(key_derivation.hmac_sha256_hex(self._key, payload_json.decode("utf-8")))
        return self._encode_part(digest)

    def code_verifier(self, payload: StatePayload) -> str:
        """The PKCE ``code_verifier`` of the flow ``payload`` signs: ``base64url(HMAC(pkce_key, nonce))``.

        Derived on both legs (authorize, code exchange) from the single-use nonce,
        so it is never stored, and never travels in the state or the URL.
        """
        return self._encode_part(bytes.fromhex(key_derivation.hmac_sha256_hex(self._pkce_key, payload.nonce)))

    def encode(
        self,
        *,
        origin: str,
        redirect: str,
        action: str,
        provider: str,
        csrf: str,
        guard_hash: str | None = None,
    ) -> str:
        """Build a signed, short-lived ``state`` for ``provider``'s authorization URL.

        ``csrf`` is the RAW CSRF cookie of the browser starting the flow; only its
        SHA-256 hex digest is stored (key ``"c"``), and the raw value is never
        persisted or logged. An attacker can mint a validly signed ``state`` for
        themselves but cannot read the victim's HttpOnly cookie, so cannot produce
        a ``csrf`` whose hash matches — that binds the callback to the SAME browser.

        ``guard_hash`` is already ``sha256_hex`` of the raw ``owt_xdomain_guard``
        cookie (computed by the frontend), so it is stored verbatim under ``"lg"``.
        It is omitted for every flow that never bounced through a custom domain;
        ``verify`` then yields ``guard_hash=None`` and cross-domain ticket issuance
        fails closed.

        The result (``base64url(json) + "." + base64url(hmac)``) needs no shared
        storage to verify. Nonce single use is enforced by the caller that has
        Redis (the flow layer's ``callback``), so this stays infra-free.
        """
        now_ts = int(datetime.now(UTC).timestamp())
        payload: dict[str, str | int] = {
            "o": origin,
            "r": redirect,
            "a": action,
            "p": provider,
            "n": self._encode_part(secrets.token_bytes(24)),
            "e": now_ts + self.ttl_seconds,
            "c": guard_digest(csrf),
        }
        if guard_hash is not None:
            payload["lg"] = guard_hash
        payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return f"{self._encode_part(payload_json)}.{self._signature(payload_json)}"

    def verify(self, state: str) -> StatePayload:
        """Verify a signed OAuth ``state`` and decode its payload.

        Checks only the HMAC (constant-time) and the embedded expiry; raises
        ``ValueError`` — never ``HTTPException`` — if the state is missing,
        malformed, tampered with or expired. The caller must still consume
        ``nonce`` and compare ``csrf``/``guard_hash`` against the raw cookies,
        which only the RPC layer has. No payload field is read before the
        signature checks out.
        """
        if not state or not isinstance(state, str):
            raise ValueError("state is required")

        try:
            encoded_payload, signature = state.split(".", maxsplit=1)
            payload_json = self._decode_part(encoded_payload)

            expected_signature = self._signature(payload_json)
            if not hmac.compare_digest(signature, expected_signature):
                raise ValueError("invalid state signature")

            payload = json.loads(payload_json)
            exp = int(payload["e"])
            now_ts = int(datetime.now(UTC).timestamp())
            if now_ts > exp:
                raise ValueError("state expired")

            guard_hash = payload.get("lg")
            return StatePayload(
                origin=str(payload["o"]),
                redirect=str(payload["r"]),
                action=str(payload["a"]),
                provider=str(payload["p"]),
                nonce=str(payload["n"]),
                exp=exp,
                csrf=str(payload["c"]),
                guard_hash=str(guard_hash) if guard_hash is not None else None,
            )
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("malformed OAuth state") from exc


oauth_state = OAuthStateCodec()

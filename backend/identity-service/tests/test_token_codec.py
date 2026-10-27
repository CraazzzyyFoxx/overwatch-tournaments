"""Access/service JWTs: EdDSA format, what ``decode`` rejects, the legacy HS256 window, and the scope
``invalidate_session`` demands."""

import asyncio
import base64
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from shared.core.errors import BaseAPIException as HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.core.config import settings  # noqa: E402
from src.services.security import TokenCodec  # noqa: E402
from src.services.service_tokens import ServiceTokenService  # noqa: E402
from tests._fakes import FakeSessionCache  # noqa: E402

_SID = "0b9c8f4e-2f7a-4a43-9a51-5b1f3c0e7d21"


def _codec(now: float = 0.0) -> TokenCodec:
    """A codec whose process "started" at monotonic 0 and whose clock reads ``now``."""
    return TokenCodec(settings, clock=lambda: now, started_at=0.0)


def _rejected(codec: TokenCodec, token: str) -> None:
    with pytest.raises(HTTPException) as exc:
        codec.decode(token)
    assert exc.value.status_code == 401


def _signed(codec: TokenCodec, **overrides: object) -> str:
    """An EdDSA token signed with the codec's real key, claims overridable."""
    now = datetime.now(UTC)
    claims = {
        "sub": "7",
        "sid": _SID,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "iss": "owt-identity",
        "aud": "owt",
        "jti": "a" * 32,
    }
    claims.update(overrides)
    return jwt.encode(claims, codec._signing_key, algorithm="EdDSA")


def _legacy(**extra: object) -> str:
    """What the previous release minted: HS256 over the raw secret, no iss/aud/iat."""
    claims = {"sub": "7", "type": "access", "exp": datetime.now(UTC) + timedelta(minutes=5), **extra}
    return jwt.encode(claims, settings.JWT_SECRET_KEY, algorithm="HS256")


def test_access_token_is_eddsa_with_exactly_the_identity_claims() -> None:
    codec = _codec()

    token = codec.access_token({"sub": 7, "sid": _SID, "email": "a@b.c", "is_superuser": True})

    assert jwt.get_unverified_header(token) == {"alg": "EdDSA", "typ": "JWT"}
    payload = codec.decode(token)
    assert set(payload) == {"sub", "sid", "type", "iat", "exp", "iss", "aud", "jti"}
    assert (payload["sub"], payload["sid"], payload["type"]) == ("7", _SID, "access")
    assert (payload["iss"], payload["aud"]) == ("owt-identity", "owt")
    assert len(payload["jti"]) == 32 and int(payload["jti"], 16) >= 0
    assert payload["exp"] - payload["iat"] == codec.access_token_ttl_seconds


def test_published_public_key_verifies_tokens() -> None:
    """The gateway's JWT_PUBLIC_KEY: raw 32 bytes, unpadded base64url, enough to verify."""
    codec = _codec()
    raw = base64.urlsafe_b64decode(codec.public_key_b64 + "=")
    assert len(codec.public_key_b64) == 43 and len(raw) == 32

    token = codec.access_token({"sub": "7", "sid": _SID})

    claims = jwt.decode(
        token, Ed25519PublicKey.from_public_bytes(raw), algorithms=["EdDSA"], audience="owt", issuer="owt-identity"
    )
    assert claims["sub"] == "7"


@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "someone-else"},
        {"aud": "elsewhere"},
        {"aud": ["owt"]},
        # An access token under the service issuer/audience is still not a service token.
        {"iss": settings.SERVICE_TOKEN_ISSUER, "aud": settings.SERVICE_TOKEN_AUDIENCE},
        {"type": "refresh"},
        {"exp": datetime.now(UTC) - timedelta(seconds=1)},
    ],
)
def test_decode_rejects_wrong_issuer_audience_type_or_expiry(overrides: dict) -> None:
    codec = _codec()
    _rejected(codec, _signed(codec, **overrides))


@pytest.mark.parametrize("missing", ["iat", "iss", "aud", "sub", "exp"])
def test_decode_requires_registered_claims(missing: str) -> None:
    codec = _codec()
    token = _signed(codec)
    claims = jwt.decode(token, options={"verify_signature": False})
    del claims[missing]
    _rejected(codec, jwt.encode(claims, codec._signing_key, algorithm="EdDSA"))


def test_decode_rejects_a_token_signed_by_another_key() -> None:
    other = TokenCodec(settings.model_copy(update={"JWT_SECRET_KEY": "another-secret"}))
    _rejected(_codec(), other.access_token({"sub": "7", "sid": _SID}))


def test_decode_rejects_alg_none_and_rs256() -> None:
    codec = _codec()
    claims = jwt.decode(_signed(codec), options={"verify_signature": False})
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    _rejected(codec, jwt.encode(claims, None, algorithm="none"))
    _rejected(codec, jwt.encode(claims, rsa_key, algorithm="RS256"))


def test_legacy_hs256_is_accepted_only_inside_the_post_start_window() -> None:
    ttl = _codec().access_token_ttl_seconds
    token = _legacy(sid=_SID, email="a@b.c")

    assert _codec(now=ttl - 1).decode(token)["sub"] == "7"
    _rejected(_codec(now=ttl), token)


def test_legacy_window_still_verifies_the_hs256_signature() -> None:
    forged = jwt.encode(
        {"sub": "7", "type": "access", "exp": datetime.now(UTC) + timedelta(minutes=5)},
        "not-the-secret",
        algorithm="HS256",
    )
    _rejected(_codec(), forged)


# -- service tokens ------------------------------------------------------------


def _service(scopes: list[str]) -> tuple[ServiceTokenService, FakeSessionCache, str]:
    config = SimpleNamespace(
        SERVICE_CLIENTS={"bot": "s3cret"},
        SERVICE_SCOPES={"bot": scopes},
        SERVICE_TOKEN_ISSUER=settings.SERVICE_TOKEN_ISSUER,
        SERVICE_TOKEN_AUDIENCE=settings.SERVICE_TOKEN_AUDIENCE,
        SERVICE_ACCESS_TOKEN_EXPIRE_MINUTES=5,
    )
    cache = FakeSessionCache()
    service = ServiceTokenService(codec=_codec(), cache=cache, config=config)
    return service, cache, service.issue("bot", "s3cret").access_token


def test_service_token_is_eddsa_with_iat_and_jti() -> None:
    service, _, token = _service(["identity:invalidate"])

    assert jwt.get_unverified_header(token)["alg"] == "EdDSA"
    payload = service.codec.decode(token)
    assert payload["type"] == "service" and payload["scopes"] == ["identity:invalidate"]
    assert (payload["iss"], payload["aud"]) == (settings.SERVICE_TOKEN_ISSUER, settings.SERVICE_TOKEN_AUDIENCE)
    assert isinstance(payload["iat"], int) and len(payload["jti"]) == 32


def test_invalidate_rbac_requires_the_invalidate_scope() -> None:
    service, cache, token = _service(["something:else"])

    with pytest.raises(HTTPException) as exc:
        asyncio.run(service.invalidate_rbac(token, 42))

    assert exc.value.status_code == 403
    assert cache.invalidated == []


def test_invalidate_rbac_with_the_scope_drops_the_entry() -> None:
    service, cache, token = _service(["identity:invalidate"])

    asyncio.run(service.invalidate_rbac(token, 42))

    assert cache.invalidated == [42]


def test_invalidate_rbac_rejects_a_user_access_token() -> None:
    service, cache, _ = _service(["identity:invalidate"])
    access = service.codec.access_token({"sub": "7", "sid": _SID})

    with pytest.raises(HTTPException) as exc:
        asyncio.run(service.invalidate_rbac(access, 42))

    assert exc.value.status_code == 401
    assert cache.invalidated == []

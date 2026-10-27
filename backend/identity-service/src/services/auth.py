"""RPC-facing orchestration of the password/session lifecycle.

Client metadata (user-agent, ip) arrives explicitly: the gateway forwards the
UA/IP it sees from nginx.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.repository import (
    AuthUserRepository,
    RoleRepository,
    SocialAccountRepository,
    UserRepository,
    WorkspaceMemberRepository,
)
from src import schemas
from src.core.metrics import LOGIN_TOTAL, REFRESH_TOTAL
from src.schemas.auth import permission_key
from src.services.audit import record_operator_audit
from src.services.auth_users import AuthUserService, auth_users
from src.services.login_throttle import LOCKED_DETAIL, LoginThrottle, login_throttle
from src.services.security import PasswordHasher, TokenCodec, passwords, token_codec
from src.services.session_cache import SessionCache, session_cache
from src.services.sessions import RefreshTokenService, SessionService, refresh_tokens, sessions
from src.services.token_payload import TokenPayloadBuilder, token_payloads

__all__ = ["AuthenticationService", "auth"]

_INVALID_REFRESH_TOKEN = "Invalid or expired refresh token"
# A refresh that lost its token to a concurrent one waits this long for the winner's pair.
_IDEM_POLL_ATTEMPTS = 10
_IDEM_POLL_INTERVAL_SECONDS = 0.1
# Passwordless re-authentication: the caller's session must have signed in this recently.
REAUTH_WINDOW = timedelta(minutes=10)
REAUTH_REQUIRED = "reauth_required"


class AuthenticationService:
    """RPC-facing orchestration of the password/session lifecycle."""

    def __init__(
        self,
        *,
        users: AuthUserService = auth_users,
        tokens: RefreshTokenService = refresh_tokens,
        session_reader: SessionService = sessions,
        codec: TokenCodec = token_codec,
        cache: SessionCache = session_cache,
        payloads: TokenPayloadBuilder = token_payloads,
        auth_users_repo: AuthUserRepository = AuthUserRepository(),
        members: WorkspaceMemberRepository = WorkspaceMemberRepository(),
        roles: RoleRepository = RoleRepository(),
        players: UserRepository = UserRepository(),
        socials: SocialAccountRepository = SocialAccountRepository(),
        hasher: PasswordHasher = passwords,
        throttle: LoginThrottle = login_throttle,
    ) -> None:
        self.users = users
        self.tokens = tokens
        self.session_reader = session_reader
        self.codec = codec
        self.cache = cache
        self.payloads = payloads
        self.auth_users_repo = auth_users_repo
        self.members = members
        self.roles = roles
        self.players = players
        self.socials = socials
        self.hasher = hasher
        self.throttle = throttle

    # --- session issuance ---

    async def issue_session(
        self,
        session: AsyncSession,
        user: models.AuthUser,
        *,
        user_agent: str | None,
        ip_address: str | None,
        commit: bool = True,
    ) -> schemas.Token:
        """Mint an access/refresh pair under a fresh logical session.

        Shared by password login and the OAuth callback: both must stamp the
        same claim set and the same ``sid``, since the ``sid`` is what session
        revocation and the access-token blacklist are keyed on. The token names
        the account and the session only; everything else is resolved per request.
        """
        session_id, session_started_at = self.codec.new_session()
        access_token = self.codec.access_token({"sub": str(user.id), "sid": str(session_id)})
        refresh_token = self.codec.new_refresh_token()
        await self.tokens.issue(
            session,
            user_id=user.id,
            token=refresh_token,
            session_id=session_id,
            session_started_at=session_started_at,
            user_agent=user_agent,
            ip_address=ip_address,
            commit=commit,
        )
        return schemas.Token(access_token=access_token, refresh_token=refresh_token)

    # --- credentials ---

    async def register(self, session: AsyncSession, payload: schemas.UserRegister) -> models.AuthUser:
        return await self.users.register(session, payload)

    async def login(
        self,
        session: AsyncSession,
        email: str,
        password: str,
        user_agent: str | None,
        ip_address: str | None,
    ) -> schemas.Token:
        # Before the password is looked at: a locked email gets no oracle, right or wrong.
        if await self.throttle.is_locked(email):
            LOGIN_TOTAL.labels(result="locked").inc()
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=LOCKED_DETAIL)
        user = await self.users.authenticate(session, email, password)
        if not user:
            await self.throttle.record_failure(email)
            LOGIN_TOTAL.labels(result="invalid").inc()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        await self.throttle.clear(email)
        if not user.is_active:
            LOGIN_TOTAL.labels(result="inactive").inc()
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive")

        token = await self.issue_session(session, user, user_agent=user_agent, ip_address=ip_address)
        LOGIN_TOTAL.labels(result="success").inc()
        return token

    async def refresh(
        self,
        session: AsyncSession,
        refresh_token: str,
        user_agent: str | None,
        ip_address: str | None,
    ) -> schemas.Token:
        """Rotate a refresh token, reusing the caller's logical session id.

        The old token is consumed by an ``UPDATE ... WHERE NOT is_revoked`` run
        under the owner's row lock, and only the transaction that flipped it
        mints a successor. A loser -- a concurrent refresh of the same token, or
        one that lost to a logout -- rolls back and answers with the winner's
        pair from the idempotency entry, or 401 when none appears: a revoked
        session never gains a live successor.
        """
        # Fast-path: a concurrent request already rotated this token.
        old_token_hash = self.codec.hash_refresh_token(refresh_token)
        cached_pair = await self.cache.get_refresh_idem(old_token_hash)
        if cached_pair is not None:
            REFRESH_TOTAL.labels(result="idempotent").inc()
            return schemas.Token(**cached_pair)

        record = await self.tokens.get_active_record(session, refresh_token)
        # Rotation grace: the client is replaying the token we JUST rotated
        # because it never received the new pair (the request died with the old
        # network path — a VPN switch). Beyond the grace window this stays a
        # reuse attack.
        grace_replay = False
        if not record:
            record = await self.tokens.get_grace_record(session, refresh_token)
            grace_replay = record is not None
        if not record:
            # Triggers reuse-detection on a known-but-revoked token.
            reused = await self.tokens.handle_reuse(session, refresh_token)
            REFRESH_TOTAL.labels(result="reuse" if reused else "invalid").inc()
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_INVALID_REFRESH_TOKEN)

        # Identity-only, and locked: the owner's row is what serializes this
        # rotation against every revocation of the user's sessions.
        user = await self.auth_users_repo.get(
            session, record.user_id, options=self.auth_users_repo.identity_options(), for_update=True
        )
        if not user:
            REFRESH_TOTAL.labels(result="invalid").inc()
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_INVALID_REFRESH_TOKEN)
        if not user.is_active:
            REFRESH_TOTAL.labels(result="invalid").inc()
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive")

        if grace_replay:
            # Retire the successor minted by the lost rotation so the session
            # keeps exactly one live refresh token; keep the sid unbanned — the
            # access token issued below carries it. Nothing to retire means a
            # concurrent replay or a logout got there first.
            consumed = await self.tokens.revoke_session(
                session,
                record.user_id,
                record.session_id,
                commit=False,
                blacklist=False,
            )
        else:
            consumed = await self.tokens.revoke_token(session, refresh_token, commit=False)
        if not consumed:
            return await self._lost_rotation(session, old_token_hash)

        access_token = self.codec.access_token({"sub": str(user.id), "sid": str(record.session_id)})
        new_refresh_token = self.codec.new_refresh_token()
        await self.tokens.issue(
            session,
            user_id=user.id,
            token=new_refresh_token,
            session_id=record.session_id,
            session_started_at=record.session_started_at,
            user_agent=user_agent,
            ip_address=ip_address,
            commit=False,
        )
        # One commit for the whole rotation: the old token's revocation and the
        # new token's row must land together or neither, else a crash between
        # them either strands the session tokenless or leaves two live tokens.
        await session.commit()

        await self.cache.set_refresh_idem(old_token_hash, access_token, new_refresh_token)
        REFRESH_TOTAL.labels(result="grace" if grace_replay else "rotated").inc()
        return schemas.Token(access_token=access_token, refresh_token=new_refresh_token)

    async def _lost_rotation(self, session: AsyncSession, old_token_hash: str) -> schemas.Token:
        """Another transaction consumed the token after we read it.

        A concurrent refresh of the same token publishes its pair right after
        its commit (which our UPDATE waited on), so wait briefly for it. None
        appearing means a revocation won: 401, with nothing minted here.
        """
        await session.rollback()
        for _ in range(_IDEM_POLL_ATTEMPTS):
            cached_pair = await self.cache.get_refresh_idem(old_token_hash)
            if cached_pair is not None:
                REFRESH_TOTAL.labels(result="idempotent").inc()
                return schemas.Token(**cached_pair)
            await asyncio.sleep(_IDEM_POLL_INTERVAL_SECONDS)
        REFRESH_TOTAL.labels(result="concurrent").inc()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_INVALID_REFRESH_TOKEN)

    # --- sessions ---

    async def logout(self, session: AsyncSession, user: models.AuthUser, refresh_token: str) -> None:
        record = await self.tokens.get_record(session, refresh_token)
        if record is not None and record.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Refresh token does not belong to the current user",
            )
        if record is not None and record.session_id is not None:
            await self.tokens.revoke_session(session, user.id, record.session_id)
        else:
            await self.tokens.revoke_token(session, refresh_token)

    async def logout_all(self, session: AsyncSession, user: models.AuthUser) -> None:
        await self.tokens.revoke_all(session, user.id)

    async def list_sessions(self, session: AsyncSession, user: models.AuthUser) -> list[schemas.SessionRead]:
        current_session_id = getattr(user, "_current_session_id", None)
        summaries = await self.session_reader.list_user_sessions(
            session, user.id, current_session_id=current_session_id
        )
        return [schemas.SessionRead.model_validate(summary) for summary in summaries]

    async def revoke_session(
        self,
        session: AsyncSession,
        user: models.AuthUser,
        session_id: UUID,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Revoke one of the caller's other sessions, journalled (it kills a credential)."""
        current_session_id = getattr(user, "_current_session_id", None)
        if current_session_id == str(session_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current session cannot be revoked from the sessions list",
            )
        summary = await self.session_reader.get_user_session(
            session, user.id, session_id, current_session_id=current_session_id
        )
        if summary is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
        # Staged before ``revoke_session`` commits, so it shares the revoke's transaction.
        await record_operator_audit(
            session,
            user,
            action="session.revoke",
            entity_type="session",
            after={"session_id": str(session_id)},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await self.tokens.revoke_session(session, user.id, session_id)

    # --- account ---

    async def get_me(self, session: AsyncSession, user_id: int) -> schemas.AuthUser:
        user = await self.users.get_with_rbac(session, user_id, include_player=True)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        data = schemas.AuthUser.model_validate(user, from_attributes=True).model_dump()
        global_roles, global_permissions = self.users.rbac_from_instance(user)
        data["roles"] = global_roles
        data["permissions"] = global_permissions

        memberships = await self.members.list_memberships_for_auth_user(session, user.id)
        ws_rbac = await self.roles.workspace_rbac_for_user(
            session, user.id, [workspace_id for workspace_id, _ in memberships]
        )

        workspaces = []
        for workspace_id, slug in memberships:
            role_names, permissions = ws_rbac.get(workspace_id, ([], []))
            workspaces.append(
                schemas.AuthUserWorkspace(
                    workspace_id=workspace_id,
                    slug=slug,
                    rbac_permissions=[
                        permission_key(perm.get("resource", ""), perm.get("action", "")) for perm in permissions
                    ],
                    rbac_roles=role_names,
                )
            )

        data["workspaces"] = [workspace.model_dump() for workspace in workspaces]
        data["linked_players"] = [player.model_dump() for player in self.payloads.linked_players(user)]
        denies = await self.payloads.load_denies(session, user.id)
        data["denies"] = [f"{deny['resource']}.{deny['action']}" for deny in denies]
        return schemas.AuthUser.model_validate(data)

    async def update_me(
        self,
        session: AsyncSession,
        user: models.AuthUser,
        payload: schemas.UserUpdate,
    ) -> models.AuthUser:
        if payload.username is not None and payload.username != user.username:
            if user.is_denied("account", "rename"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail="You are not allowed to change your name"
                )
            if await self.auth_users_repo.username_taken(session, payload.username, exclude_user_id=user.id):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This name is already taken")
            user.username = payload.username
        if payload.first_name is not None:
            user.first_name = payload.first_name
        if payload.last_name is not None:
            user.last_name = payload.last_name
        if payload.email is not None and payload.email != user.email:
            if await self.auth_users_repo.email_taken(session, payload.email, exclude_user_id=user.id):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")
            user.email = payload.email
            # Ownership of the new address is unproven until a verification flow
            # confirms it. Together with fail-closed OAuth email matching, this
            # breaks the "swap email -> take over via OAuth" chain.
            user.is_verified = False

        try:
            await session.commit()
        except IntegrityError as exc:
            # A concurrent write to the same name (or email) won the unique index.
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="This name or email is already taken"
            ) from exc
        # Email and username ride in the cached RBAC entry the token path answers from.
        await self.cache.invalidate_rbac(user.id)
        # The identity map hands back this very instance with its expired columns reloaded, plus the player the
        # account's avatar is read off.
        reloaded = await self.users.get_identity(session, user.id, include_player=True)
        assert reloaded is not None  # the caller's own row, just committed
        return reloaded

    @staticmethod
    def _current_session(user: models.AuthUser) -> UUID | None:
        raw = getattr(user, "_current_session_id", None)
        try:
            return UUID(raw) if raw else None
        except ValueError:
            return None

    async def _reauthenticate(self, session: AsyncSession, user: models.AuthUser, current_password: str | None) -> None:
        """Prove the caller holds the account right now, before a credential-level change.

        A password account proves it with the current password. A passwordless
        one cannot, so the caller's own session must have signed in within
        ``REAUTH_WINDOW`` (a stolen, long-lived session does not qualify); else
        403 ``reauth_required`` and the client sends the user through sign-in.
        """
        if user.hashed_password:
            if not current_password:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is required")
            if not await self.hasher.verify(current_password, user.hashed_password):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect")
            return
        session_id = self._current_session(user)
        current = (
            None if session_id is None else await self.session_reader.get_user_session(session, user.id, session_id)
        )
        if current is None or current["status"] != "active" or datetime.now(UTC) - current["login_at"] > REAUTH_WINDOW:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=REAUTH_REQUIRED)

    async def set_password(
        self,
        session: AsyncSession,
        user: models.AuthUser,
        payload: schemas.PasswordSetRequest,
    ) -> None:
        """Set the first password or change it; every OTHER session is signed out."""
        await self._reauthenticate(session, user, payload.current_password)
        user.hashed_password = await self.hasher.hash(payload.new_password)
        # Commits the new hash together with the revocation, then blacklists the revoked sids.
        await self.tokens.revoke_all(session, user.id, keep_session_id=self._current_session(user))

    async def delete_me(
        self,
        session: AsyncSession,
        user: models.AuthUser,
        *,
        current_password: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Self-service account deletion. Historical data is never touched.

        Only auth-owned rows go away, all via ``ondelete=CASCADE``: sessions and
        refresh tokens, OAuth connections, role grants, permission denies, API
        keys, preview-access grants, subscription records. Everything that
        carries history references the account with ``ondelete=SET NULL``
        instead -- the player identity (``players.user.auth_user_id``), audit
        rows, and the ``reviewed_by``/``checked_in_by``/``deleted_by`` stamps on
        registrations -- so tournaments, matches, statistics, registrations,
        achievements and workspace membership all survive verbatim. The player
        simply becomes unclaimed again, exactly as it was before this account
        existed, and can be re-claimed by a future OAuth login or an admin link.

        The player's OAuth-verified social identities lose their verified mark
        and their ``provider_user_id`` pin, the same pair the OAuth unlink flow
        clears: the connections that proved them are gone with the account, and
        a surviving pin would keep capturing that provider identity instead of
        letting the provider account be linked to a new one -- which is the
        whole reason a user deletes an account they cannot sign into any other
        way. The handle rows themselves stay, so the public profile keeps
        showing the same names.

        Superusers are refused: self-deleting the account that administers the
        platform is a footgun the admin surface already refuses in the other
        direction (deleting yourself from the auth-user admin is rejected too).
        Everyone else re-authenticates first (``_reauthenticate``).
        """
        if user.is_superuser:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Superuser accounts cannot be deleted here. Ask another administrator to remove it.",
            )
        await self._reauthenticate(session, user, current_password)

        user_id = user.id
        email = user.email  # captured before the delete/commit expires the instance
        username = user.username

        player_id = await self.players.get_id_by_auth_user_id(session, user_id)
        if player_id is not None:
            await self.socials.unverify_for_player(session, user_id=player_id)

        # Blacklists every live session id: the refresh tokens are about to be
        # cascade-deleted, but the stateless access tokens already handed out
        # stay decodable until they expire on their own.
        await self.tokens.revoke_all(session, user_id, commit=False)

        await record_operator_audit(
            session,
            user,
            action="auth_user.delete_self",
            entity_type="auth_user",
            entity_id=user_id,
            entity_label=username or email,
            before={"email": email, "username": username, "player_id": player_id},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await self.auth_users_repo.delete(session, user)
        await session.commit()
        await self.cache.invalidate_rbac(user_id)
        logger.info(f"Account self-deleted: user_id={user_id} email={email} player_id={player_id}")


auth = AuthenticationService()

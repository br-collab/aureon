"""
aureon.approval_service.operator_auth
=====================================
Authentication and replay protection for authority mutations (AUR-I-03).

Before Wave 2, anyone who could reach the public service could create and
approve decisions, open the session, propose and approve doctrine, resume
paused lifecycles and move MMF positions: none of those routes checked who was
calling. The Tier 0 halt routes already required the operator key
(``AUREON_ADMIN_KEY`` sent as ``X-Admin-Key``) and failed closed when it was
unset. This module extends that one mechanism to every authority mutation,
rather than adding a second one.

Every authenticated request must carry:

- ``X-Admin-Key`` — the operator key. Compared in constant time. When
  ``AUREON_ADMIN_KEY`` is unset, every request is refused (fail closed).
- ``X-Request-Nonce`` — a value unique to this request, 16 to 128 characters
  of letters, digits, ``-`` and ``_`` (a UUID works). A nonce seen within
  :data:`REPLAY_WINDOW_SECONDS` is refused, so a captured request cannot be
  replayed.

An authenticated caller is recorded as the CAOM-001 operator: a kernel
``ActorRef`` of kind ``HUMAN``, authenticated. The boot-time session auto-open
does not go through HTTP and is recorded as ``DETERMINISTIC_SERVICE``.

Pure apart from the nonce cache's own memory: no Flask, no I/O.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import threading
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass

from cannae_kernel.actor import ActorKind, ActorRef
from cannae_kernel.ids import ActorId, encode_ulid

__all__ = [
    "ADMIN_KEY_HEADER",
    "BOOT_SERVICE_ACTOR",
    "NONCE_HEADER",
    "OPERATOR_ACTOR",
    "REPLAY_WINDOW_SECONDS",
    "AuthOutcome",
    "NonceCache",
    "authenticate",
]

ADMIN_KEY_HEADER = "X-Admin-Key"
NONCE_HEADER = "X-Request-Nonce"
REPLAY_WINDOW_SECONDS = 15 * 60
_NONCE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


def _stable_actor_id(name: str) -> ActorId:
    """A fixed actor id derived from a name. The actor registry lives in the Cannae C2
    harness (JUM-D-18); until then these identities are constants."""
    digest = hashlib.sha256(name.encode("utf-8")).digest()
    return ActorId("act_" + encode_ulid(0, digest[:10]))


#: The single CAOM-001 operator, as authenticated by the operator key.
OPERATOR_ACTOR = ActorRef(
    actor_id=_stable_actor_id("aureon:caom-001:operator"),
    actor_kind=ActorKind.HUMAN,
    role="CAOM-001 operator",
    entitlement_refs=("AUREON_ADMIN_KEY",),
    authenticated=True,
)

#: The in-process boot sequence that auto-opens the session (CLAUDE.md invariant).
BOOT_SERVICE_ACTOR = ActorRef(
    actor_id=_stable_actor_id("aureon:boot:session-auto-open"),
    actor_kind=ActorKind.DETERMINISTIC_SERVICE,
    role="aureon boot session auto-open",
    entitlement_refs=("CAOM-001 six-step session protocol",),
    authenticated=True,
)


class NonceCache:
    """Nonces seen within the replay window. Thread-safe, bounded, in memory.

    In memory means per process: Aureon runs one gunicorn worker, and a restart
    clears the cache, which is acceptable because a restart also ends any window
    in which a captured request would have been useful to replay against state
    that has since been reloaded.
    """

    def __init__(self, *, window_seconds: int = REPLAY_WINDOW_SECONDS, max_entries: int = 10_000):
        self._window = window_seconds
        self._max = max_entries
        self._seen: OrderedDict[str, float] = OrderedDict()
        self._lock = threading.Lock()

    def first_use(self, nonce: str, now: float) -> bool:
        """Record ``nonce``; True if it had not been seen within the window."""
        with self._lock:
            while self._seen:
                oldest_nonce, seen_at = next(iter(self._seen.items()))
                if now - seen_at < self._window:
                    break
                self._seen.popitem(last=False)
            if nonce in self._seen:
                return False
            if len(self._seen) >= self._max:
                # Full of live nonces: a flood. Refuse rather than forget one early.
                return False
            self._seen[nonce] = now
            return True


@dataclass(frozen=True)
class AuthOutcome:
    ok: bool
    status: int
    error: str | None
    actor: ActorRef | None
    nonce: str | None


def _refused(status: int, error: str, nonce: str | None = None) -> AuthOutcome:
    return AuthOutcome(ok=False, status=status, error=error, actor=None, nonce=nonce)


def authenticate(
    headers: Mapping[str, str],
    *,
    admin_key: str | None,
    nonces: NonceCache,
    now: float,
) -> AuthOutcome:
    """Authenticate one request. 401 when credentials are missing, 403 when refused."""
    if not admin_key:
        return _refused(
            403,
            "Authority mutations are disabled: AUREON_ADMIN_KEY is not set (fails closed).",
        )
    supplied = headers.get(ADMIN_KEY_HEADER) or ""
    if not supplied:
        return _refused(401, f"{ADMIN_KEY_HEADER} is required for authority mutations.")
    supplied_digest = hashlib.sha256(supplied.encode("utf-8")).digest()
    expected_digest = hashlib.sha256(admin_key.encode("utf-8")).digest()
    if not hmac.compare_digest(supplied_digest, expected_digest):
        return _refused(403, f"{ADMIN_KEY_HEADER} does not match.")
    nonce = headers.get(NONCE_HEADER) or ""
    if not nonce:
        return _refused(401, f"{NONCE_HEADER} is required for authority mutations.")
    if not _NONCE_PATTERN.match(nonce):
        return _refused(
            401, f"{NONCE_HEADER} must be 16-128 letters, digits, '-' or '_' (a UUID works)."
        )
    if not nonces.first_use(nonce, now):
        return _refused(403, f"{NONCE_HEADER} was already used: replay refused.", nonce)
    return AuthOutcome(ok=True, status=200, error=None, actor=OPERATOR_ACTOR, nonce=nonce)

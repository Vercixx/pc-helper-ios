"""logind session discovery, unlocking, and locking.

Why this needs no privileges
----------------------------
``org.freedesktop.login1.policy`` defines a single action,
``org.freedesktop.login1.lock-sessions``, described as "Lock or unlock active
sessions" -- it guards *both* directions, so the absence of a separate
``unlock-session`` action is not the reason either call works.

The reason is the caller's uid. logind passes the session owner's uid to
``bus_verify_polkit_async`` as its ``good_user`` argument, which returns
"authorized" before polkit is ever consulted when the calling process's uid
matches. That is a property of *who is asking*, not of *which verb*, which is why
it covers lock and unlock alike. So this module runs as an ordinary user with no
sudo, no setuid binary, and no polkit rule.

Why it shells out
-----------------
``loginctl`` is invoked with :func:`asyncio.create_subprocess_exec`, an absolute
path, and an argument vector. No shell is ever involved, so there is no quoting or
injection surface. Session ids are additionally pattern-checked before use.

Why the result is re-read
-------------------------
``loginctl unlock-session`` emits logind's ``Unlock`` signal and exits 0 whether
or not any screen locker acts on it. Reporting success from that exit code would
be a lie on a system running a locker that ignores logind (bare swaylock, i3lock).
So we poll ``LockedHint`` afterwards and only report success once it actually
changes. ``lock-session`` has the same problem in the other direction, and gets
the same treatment.

Why lock and unlock do not share a target
-----------------------------------------
They rank candidate sessions inversely: unlock wants the locked one, lock wants
the unlocked one. See :func:`_rank_for_unlock` and :func:`_rank_for_lock`. On a
single-session desktop both pick the same session, so getting this wrong is
invisible until someone runs two seats.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .errors import ApiError

SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9]{1,32}$")

GRAPHICAL_TYPES = frozenset({"wayland", "x11", "mir"})

# How long to wait for the screen locker to react to logind's Unlock signal.
UNLOCK_CONFIRM_TIMEOUT_S = 5.0
UNLOCK_POLL_INTERVAL_S = 0.2

# The same, for Lock. Longer on purpose: releasing a locker that is already
# running is quicker than starting one, and a screen that failed to lock is a
# worse thing to report wrongly than a screen that failed to unlock.
LOCK_CONFIRM_TIMEOUT_S = 8.0
LOCK_POLL_INTERVAL_S = 0.2

_COMMAND_TIMEOUT_S = 10.0


def loginctl_path() -> str:
    return shutil.which("loginctl") or "/usr/bin/loginctl"


@dataclass(frozen=True, slots=True)
class SessionInfo:
    id: str
    uid: int
    type: str
    klass: str
    active: bool
    locked: bool
    seat: str | None = None
    desktop: str | None = None
    user: str | None = None

    @property
    def is_graphical(self) -> bool:
        return self.klass == "user" and self.type in GRAPHICAL_TYPES

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "class": self.klass,
            "active": self.active,
            "locked": self.locked,
            "seat": self.seat,
            "desktop": self.desktop,
        }


@dataclass(frozen=True, slots=True)
class UnlockResult:
    session: SessionInfo
    was_locked: bool
    unlocked: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session.id,
            "was_locked": self.was_locked,
            "unlocked": self.unlocked,
            "type": self.session.type,
            "desktop": self.session.desktop,
            "seat": self.session.seat,
        }


@dataclass(frozen=True, slots=True)
class LockResult:
    session: SessionInfo
    was_locked: bool
    locked: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session.id,
            "was_locked": self.was_locked,
            "locked": self.locked,
            "type": self.session.type,
            "desktop": self.session.desktop,
            "seat": self.session.seat,
        }


class SessionError(ApiError):
    pass


async def _run(*args: str, timeout: float = _COMMAND_TIMEOUT_S) -> tuple[int, str, str]:
    """Execute loginctl. No shell, absolute path, argument vector."""
    try:
        proc = await asyncio.create_subprocess_exec(
            loginctl_path(),
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (OSError, FileNotFoundError) as exc:
        raise ApiError("internal_error", f"cannot execute loginctl: {exc}") from exc

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise ApiError("internal_error", "loginctl timed out") from None

    return (
        proc.returncode or 0,
        stdout.decode("utf-8", "replace"),
        stderr.decode("utf-8", "replace").strip(),
    )


def _parse_show_output(text: str) -> dict[str, str]:
    """Parse ``Key=Value`` lines from ``loginctl show-session``.

    Values are taken verbatim after the first ``=`` so that a value containing an
    ``=`` survives intact.
    """
    props: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            props[key.strip()] = value
    return props


async def _list_session_ids() -> list[tuple[str, int, str]]:
    """Return ``(session_id, uid, class)`` for every session.

    Prefers ``--json=short`` (systemd 246+), which already carries the class and
    saves a round trip per session. Falls back to the legacy table, from which
    only the first two columns are read -- those have been stable across every
    systemd release, whereas the later columns have not.
    """
    rc, stdout, _ = await _run("list-sessions", "--json=short")
    if rc == 0:
        try:
            entries = json.loads(stdout)
        except json.JSONDecodeError:
            entries = None
        if isinstance(entries, list):
            out: list[tuple[str, int, str]] = []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                sid = str(entry.get("session", "")).strip()
                if not SESSION_ID_RE.match(sid):
                    continue
                raw_uid = entry.get("uid")
                if not isinstance(raw_uid, int) or isinstance(raw_uid, bool):
                    continue
                uid = raw_uid
                out.append((sid, uid, str(entry.get("class") or "")))
            return out

    rc, stdout, stderr = await _run("list-sessions", "--no-legend")
    if rc != 0:
        raise ApiError("internal_error", f"loginctl list-sessions failed: {stderr}")
    out = []
    for line in stdout.splitlines():
        fields = line.split()
        if len(fields) < 2:
            continue
        sid = fields[0]
        if not SESSION_ID_RE.match(sid) or not fields[1].isdigit():
            continue
        out.append((sid, int(fields[1]), ""))
    return out


async def describe_session(session_id: str) -> SessionInfo | None:
    """Full properties for one session, or None if it no longer exists."""
    if not SESSION_ID_RE.match(session_id):
        raise ApiError("bad_request", "malformed session id")

    rc, stdout, _ = await _run(
        "show-session",
        session_id,
        "--property=Id",
        "--property=User",
        "--property=Name",
        "--property=Seat",
        "--property=Desktop",
        "--property=Type",
        "--property=Class",
        "--property=Active",
        "--property=LockedHint",
    )
    if rc != 0:
        return None

    props = _parse_show_output(stdout)
    try:
        uid = int(props.get("User", "-1"))
    except ValueError:
        uid = -1

    return SessionInfo(
        id=props.get("Id") or session_id,
        uid=uid,
        type=(props.get("Type") or "").lower(),
        klass=(props.get("Class") or "").lower(),
        active=props.get("Active") == "yes",
        locked=props.get("LockedHint") == "yes",
        seat=props.get("Seat") or None,
        desktop=props.get("Desktop") or None,
        user=props.get("Name") or None,
    )


async def list_own_sessions() -> list[SessionInfo]:
    """Every session belonging to the uid this service runs as."""
    own_uid = os.getuid()
    result: list[SessionInfo] = []
    for session_id, uid, klass in await _list_session_ids():
        if uid != own_uid:
            continue
        # Cheap pre-filter when list-sessions gave us the class: systemd creates a
        # 'manager' session alongside the real one and it can never be unlocked.
        if klass and klass != "user":
            continue
        info = await describe_session(session_id)
        if info is not None and info.uid == own_uid:
            result.append(info)
    return result


def _tiebreak(session: SessionInfo) -> tuple[int, int]:
    """Shared tail of both sort keys: active sessions first, then lowest id."""
    numeric = int(session.id) if session.id.isdigit() else 1_000_000
    return (0 if session.active else 1, numeric)


def _rank_for_unlock(session: SessionInfo) -> tuple[int, int, int]:
    """Locked sessions first.

    A locked session is precisely the one worth unlocking, so it outranks an
    active-but-unlocked one on a multi-seat box.
    """
    return (0 if session.locked else 1, *_tiebreak(session))


def _rank_for_lock(session: SessionInfo) -> tuple[int, int, int]:
    """Unlocked sessions first -- the exact inverse of :func:`_rank_for_unlock`.

    Deliberately a separate function rather than a flag on one. Reusing the
    unlock ranking here would send a lock request at a session that is already
    locked, change nothing, and report success; on a single-session desktop the
    two rankings agree and that bug never shows itself.
    """
    return (0 if not session.locked else 1, *_tiebreak(session))


async def _validate_explicit_target(session_id: str) -> SessionInfo:
    """Check a caller-supplied session id.

    Shared by both operations: whichever way it is going, a caller must not be
    able to steer this at someone else's session or at a non-graphical one.
    """
    if not SESSION_ID_RE.match(session_id):
        raise ApiError("bad_request", "malformed session id")
    info = await describe_session(session_id)
    if info is None:
        raise ApiError("no_session", f"no session {session_id!r}")
    if info.uid != os.getuid():
        raise ApiError("no_session", f"session {session_id!r} belongs to another user")
    if not info.is_graphical:
        raise ApiError(
            "no_session", f"session {session_id!r} is {info.klass}/{info.type}, not graphical"
        )
    return info


async def _find_target(
    session_id: str | None,
    rank: Callable[[SessionInfo], tuple[int, int, int]],
) -> SessionInfo:
    if session_id is not None:
        return await _validate_explicit_target(session_id)

    candidates = [s for s in await list_own_sessions() if s.is_graphical]
    if not candidates:
        raise ApiError("no_session", "no graphical session found for this user")
    candidates.sort(key=rank)
    return candidates[0]


async def find_unlock_target(session_id: str | None = None) -> SessionInfo:
    """Choose the session to unlock (PROTOCOL.md 6.1)."""
    return await _find_target(session_id, _rank_for_unlock)


async def find_lock_target(session_id: str | None = None) -> SessionInfo:
    """Choose the session to lock (PROTOCOL.md 6.2)."""
    return await _find_target(session_id, _rank_for_lock)


async def unlock_session(session_id: str | None = None) -> UnlockResult:
    """Unlock the graphical session and confirm the state actually changed."""
    target = await find_unlock_target(session_id)

    if not target.locked:
        # Idempotent: asking to unlock an unlocked session is a success, not an
        # error. The app retries on flaky wifi and should not see a failure.
        return UnlockResult(session=target, was_locked=False, unlocked=True)

    rc, _, stderr = await _run("unlock-session", target.id)
    if rc != 0:
        raise ApiError(
            "unlock_failed",
            f"loginctl unlock-session failed: {stderr or f'exit {rc}'}",
        )

    confirmed = await _await_locked_hint(
        target.id,
        want=False,
        timeout=UNLOCK_CONFIRM_TIMEOUT_S,
        interval=UNLOCK_POLL_INTERVAL_S,
    )
    if not confirmed:
        raise ApiError(
            "unlock_failed",
            "logind accepted the unlock but the screen locker did not release the "
            "session within {:.0f}s. Lockers that ignore logind's Unlock signal "
            "(bare swaylock, i3lock) cannot be unlocked remotely.".format(
                UNLOCK_CONFIRM_TIMEOUT_S
            ),
        )

    final = await describe_session(target.id) or target
    return UnlockResult(session=final, was_locked=True, unlocked=True)


async def lock_session(session_id: str | None = None) -> LockResult:
    """Lock the graphical session and confirm the state actually changed."""
    target = await find_lock_target(session_id)

    if target.locked:
        # Idempotent, mirroring unlock: asking to lock a locked session is a
        # success, not an error. A second tap on a flaky connection must not
        # read as a failure.
        return LockResult(session=target, was_locked=True, locked=True)

    rc, _, stderr = await _run("lock-session", target.id)
    if rc != 0:
        raise ApiError(
            "lock_failed",
            f"loginctl lock-session failed: {stderr or f'exit {rc}'}",
        )

    confirmed = await _await_locked_hint(
        target.id,
        want=True,
        timeout=LOCK_CONFIRM_TIMEOUT_S,
        interval=LOCK_POLL_INTERVAL_S,
    )
    if not confirmed:
        # A different failure from unlock's, and worth wording differently.
        # There, a locker was running and would not let go. Here, most likely
        # nothing was listening for logind's Lock signal at all -- so the screen
        # is still open, which is the dangerous direction to be wrong in.
        raise ApiError(
            "lock_failed",
            "logind accepted the lock but no screen locker engaged within "
            "{:.0f}s, so the session is still unlocked. Locking needs a locker "
            "listening for logind's Lock signal (KDE Plasma and GNOME are; bare "
            "swaylock and i3lock are not).".format(LOCK_CONFIRM_TIMEOUT_S),
        )

    final = await describe_session(target.id) or target
    return LockResult(session=final, was_locked=False, locked=True)


async def _await_locked_hint(
    session_id: str,
    *,
    want: bool,
    timeout: float,
    interval: float,
) -> bool:
    """Poll LockedHint until it reaches ``want``, or the timeout elapses.

    The screen locker reacts to logind's signal asynchronously and only then
    updates the hint, so a single immediate read would race and usually lose.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        info = await describe_session(session_id)
        if info is None:
            return False
        if info.locked == want:
            return True
        if loop.time() >= deadline:
            return False
        await asyncio.sleep(interval)


async def current_session() -> SessionInfo | None:
    """Best graphical session for status reporting; None is not an error."""
    try:
        return await find_unlock_target()
    except ApiError:
        return None

"""logind session discovery and unlocking.

Why this needs no privileges
----------------------------
``org.freedesktop.login1.policy`` defines a ``lock-sessions`` action but no
``unlock-session`` action. logind consults polkit only when the caller's uid
differs from the target session's uid; a service running as the session owner is
authorized implicitly. So this module runs as an ordinary user with no sudo, no
setuid binary, and no polkit rule.

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
clears.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from dataclasses import dataclass
from typing import Any

from .errors import ApiError

SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9]{1,32}$")

GRAPHICAL_TYPES = frozenset({"wayland", "x11", "mir"})

# How long to wait for the screen locker to react to logind's Unlock signal.
UNLOCK_CONFIRM_TIMEOUT_S = 5.0
UNLOCK_POLL_INTERVAL_S = 0.2

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


def _rank(session: SessionInfo) -> tuple[int, int, int]:
    """Sort key: locked sessions first, then active ones, then lowest id.

    A locked session is precisely the one worth unlocking, so it outranks an
    active-but-unlocked one on a multi-seat box.
    """
    numeric = int(session.id) if session.id.isdigit() else 1_000_000
    return (0 if session.locked else 1, 0 if session.active else 1, numeric)


async def find_unlock_target(session_id: str | None = None) -> SessionInfo:
    """Choose the session to unlock.

    An explicit id must still belong to us and be graphical -- the caller cannot
    steer this at someone else's session.
    """
    if session_id is not None:
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

    candidates = [s for s in await list_own_sessions() if s.is_graphical]
    if not candidates:
        raise ApiError("no_session", "no graphical session found for this user")
    candidates.sort(key=_rank)
    return candidates[0]


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

    confirmed = await _await_unlocked(target.id)
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


async def _await_unlocked(session_id: str) -> bool:
    """Poll LockedHint until it clears or the timeout elapses.

    The screen locker reacts to logind's signal asynchronously and then clears the
    hint, so a single immediate read would race and usually lose.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + UNLOCK_CONFIRM_TIMEOUT_S
    while True:
        info = await describe_session(session_id)
        if info is None:
            return False
        if not info.locked:
            return True
        if loop.time() >= deadline:
            return False
        await asyncio.sleep(UNLOCK_POLL_INTERVAL_S)


async def current_session() -> SessionInfo | None:
    """Best graphical session for status reporting; None is not an error."""
    try:
        return await find_unlock_target()
    except ApiError:
        return None

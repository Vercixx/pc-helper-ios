"""Session discovery and unlocking, driven by recorded loginctl output.

``loginctl`` is stubbed rather than invoked so these run anywhere, but the
fixtures are captured verbatim from a real KDE/Wayland Arch machine.
"""

from __future__ import annotations

import os

import pytest

from conftest import LOGINCTL_SESSIONS_JSON
from wol_unlock import session as S
from wol_unlock.errors import ApiError

UID = os.getuid()


def props(**overrides) -> str:
    base = {
        "User": str(UID), "Name": "alice", "Seat": "seat0", "Desktop": "KDE",
        "Type": "wayland", "Class": "user", "Active": "yes", "LockedHint": "no",
    }
    base.update(overrides)
    return "".join(f"{k}={v}\n" for k, v in base.items())


class FakeLoginctl:
    """Records invocations and replays canned output."""

    def __init__(self, sessions_json: str = LOGINCTL_SESSIONS_JSON, **session_props):
        self.sessions_json = sessions_json.replace('"uid":1000', f'"uid":{UID}')
        self.session_props = session_props or {"1": props(), "2": props(Class="manager", Type="")}
        self.calls: list[tuple[str, ...]] = []
        self.unlock_flips_hint = True

    async def __call__(self, *args: str, timeout: float = 10.0):
        self.calls.append(args)
        if args[0] == "list-sessions":
            if "--json=short" in args:
                return 0, self.sessions_json, ""
            return 1, "", "unsupported"
        if args[0] == "show-session":
            session_id = args[1]
            if session_id not in self.session_props:
                return 1, "", f"Failed to get path for session '{session_id}'"
            return 0, self.session_props[session_id], ""
        if args[0] == "unlock-session":
            if self.unlock_flips_hint:
                self.session_props[args[1]] = self.session_props[args[1]].replace(
                    "LockedHint=yes", "LockedHint=no"
                )
            return 0, "", ""
        return 1, "", "unexpected command"


@pytest.fixture
def loginctl(monkeypatch):
    fake = FakeLoginctl()
    monkeypatch.setattr(S, "_run", fake)
    monkeypatch.setattr(S, "UNLOCK_CONFIRM_TIMEOUT_S", 0.5)
    monkeypatch.setattr(S, "UNLOCK_POLL_INTERVAL_S", 0.01)
    return fake


class TestSessionSelection:
    async def test_picks_graphical_not_manager(self, loginctl):
        """systemd creates a Class=manager session alongside the real one; it can
        never be unlocked and must never be chosen."""
        target = await S.find_unlock_target()
        assert target.id == "1"
        assert target.klass == "user"
        assert target.type == "wayland"

    async def test_lists_only_our_uid(self, loginctl):
        loginctl.sessions_json = LOGINCTL_SESSIONS_JSON.replace(
            '"uid":1000', f'"uid":{UID + 1}'
        )
        with pytest.raises(ApiError) as exc:
            await S.find_unlock_target()
        assert exc.value.code == "no_session"

    async def test_locked_session_outranks_active_one(self, monkeypatch):
        fake = FakeLoginctl(
            sessions_json=(
                '[{"session":"3","uid":1000,"class":"user"},'
                '{"session":"4","uid":1000,"class":"user"}]'
            ),
            **{
                "3": props(Active="yes", LockedHint="no"),
                "4": props(Active="no", LockedHint="yes"),
            },
        )
        monkeypatch.setattr(S, "_run", fake)
        target = await S.find_unlock_target()
        assert target.id == "4", "the locked session is the one worth unlocking"

    async def test_explicit_id_must_be_graphical(self, loginctl):
        with pytest.raises(ApiError, match="not graphical"):
            await S.find_unlock_target("2")

    async def test_explicit_unknown_id(self, loginctl):
        with pytest.raises(ApiError) as exc:
            await S.find_unlock_target("99")
        assert exc.value.code == "no_session"

    @pytest.mark.parametrize("bad", ["../../etc", "1; rm -rf /", "1 2", "", "a" * 40])
    async def test_malformed_id_rejected_before_use(self, loginctl, bad):
        """Ids are pattern-checked before ever becoming an argv entry."""
        with pytest.raises(ApiError) as exc:
            await S.find_unlock_target(bad)
        assert exc.value.code in ("bad_request", "no_session")
        assert not any(bad in call for call in loginctl.calls)

    async def test_falls_back_to_table_when_json_unsupported(self, monkeypatch):
        fake = FakeLoginctl()

        async def no_json(*args: str, timeout: float = 10.0):
            if args[0] == "list-sessions" and "--json=short" in args:
                return 1, "", "unknown option"
            if args[0] == "list-sessions":
                return 0, f"      1 {UID} alice seat0 830 user tty1 no -\n", ""
            return await fake(*args, timeout=timeout)

        monkeypatch.setattr(S, "_run", no_json)
        target = await S.find_unlock_target()
        assert target.id == "1"


class TestUnlock:
    async def test_unlocking_a_locked_session(self, loginctl):
        loginctl.session_props["1"] = props(LockedHint="yes")
        result = await S.unlock_session()
        assert result.was_locked is True
        assert result.unlocked is True
        assert ("unlock-session", "1") in loginctl.calls

    async def test_already_unlocked_is_idempotent(self, loginctl):
        result = await S.unlock_session()
        assert result.was_locked is False
        assert result.unlocked is True
        # No point signalling logind for a session that is not locked.
        assert not any(call[0] == "unlock-session" for call in loginctl.calls)

    async def test_locker_ignoring_logind_is_reported_as_failure(self, loginctl):
        """`loginctl unlock-session` exits 0 whether or not any locker acts on the
        signal. Trusting that exit code would report success on swaylock/i3lock."""
        loginctl.session_props["1"] = props(LockedHint="yes")
        loginctl.unlock_flips_hint = False

        with pytest.raises(ApiError) as exc:
            await S.unlock_session()
        assert exc.value.code == "unlock_failed"
        assert "screen locker" in exc.value.message

    async def test_loginctl_failure_surfaces(self, loginctl, monkeypatch):
        loginctl.session_props["1"] = props(LockedHint="yes")

        async def failing(*args: str, timeout: float = 10.0):
            if args[0] == "unlock-session":
                return 1, "", "Access denied"
            return await FakeLoginctl.__call__(loginctl, *args, timeout=timeout)

        monkeypatch.setattr(S, "_run", failing)
        with pytest.raises(ApiError) as exc:
            await S.unlock_session()
        assert exc.value.code == "unlock_failed"
        assert "Access denied" in exc.value.message


class TestParsing:
    def test_show_output_parsing(self):
        parsed = S._parse_show_output("Type=wayland\nDesktop=KDE\nEmpty=\nOdd=a=b\n")
        assert parsed == {"Type": "wayland", "Desktop": "KDE", "Empty": "", "Odd": "a=b"}

    async def test_current_session_returns_none_instead_of_raising(self, monkeypatch):
        async def nothing(*args: str, timeout: float = 10.0):
            return 0, "[]", ""

        monkeypatch.setattr(S, "_run", nothing)
        assert await S.current_session() is None

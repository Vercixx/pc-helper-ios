"""Persistent state: trusted devices, spent nonces, audit log.

SQLite in WAL mode. The nonce table is deliberately *on disk* rather than in
memory: an in-memory replay cache would reopen a `timestamp_skew_s`-wide replay
window every time the service restarted, and restarts are exactly when an attacker
who has captured a request would try one.

All public methods are async and run their SQLite work on a worker thread, so a
slow fsync cannot stall the event loop.
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

SCHEMA_VERSION = 1

_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS devices (
    device_id    TEXT PRIMARY KEY,
    pubkey       BLOB NOT NULL UNIQUE,
    name         TEXT NOT NULL,
    platform     TEXT NOT NULL DEFAULT '',
    paired_at    INTEGER NOT NULL,
    last_seen_at INTEGER,
    revoked_at   INTEGER
);

-- Nonces are scoped per device: two devices independently drawing the same 16
-- random bytes is astronomically unlikely but would otherwise be a spurious
-- rejection, and cross-device uniqueness buys nothing.
CREATE TABLE IF NOT EXISTS nonces (
    device_id  TEXT NOT NULL,
    nonce      TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    PRIMARY KEY (device_id, nonce)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_nonces_expires ON nonces(expires_at);

CREATE TABLE IF NOT EXISTS audit (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        INTEGER NOT NULL,
    device_id TEXT,
    action    TEXT NOT NULL,
    result    TEXT NOT NULL,
    peer_ip   TEXT,
    detail    TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit(ts DESC);
"""


@dataclass(frozen=True, slots=True)
class DeviceRecord:
    device_id: str
    pubkey: bytes
    name: str
    platform: str
    paired_at: int
    last_seen_at: int | None
    revoked_at: int | None

    @property
    def revoked(self) -> bool:
        return self.revoked_at is not None

    def to_dict(self) -> dict[str, Any]:
        from .crypto.canonical import fingerprint

        return {
            "device_id": self.device_id,
            "name": self.name,
            "platform": self.platform,
            "fp": fingerprint(self.pubkey),
            "paired_at": self.paired_at,
            "last_seen_at": self.last_seen_at,
            "revoked_at": self.revoked_at,
            "revoked": self.revoked,
        }


@dataclass(frozen=True, slots=True)
class AuditRecord:
    id: int
    ts: int
    device_id: str | None
    action: str
    result: str
    peer_ip: str | None
    detail: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts": self.ts,
            "device_id": self.device_id,
            "action": self.action,
            "result": self.result,
            "peer_ip": self.peer_ip,
            "detail": self.detail,
        }


def _device_from_row(row: sqlite3.Row) -> DeviceRecord:
    return DeviceRecord(
        device_id=row["device_id"],
        pubkey=row["pubkey"],
        name=row["name"],
        platform=row["platform"],
        paired_at=row["paired_at"],
        last_seen_at=row["last_seen_at"],
        revoked_at=row["revoked_at"],
    )


class Store:
    """Async facade over a single SQLite connection guarded by a lock."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    # -- lifecycle ---------------------------------------------------------- #

    @classmethod
    async def open(cls, path: Path) -> "Store":
        store = cls(path)
        await asyncio.to_thread(store._open_sync)
        return store

    def _open_sync(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        conn = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA)
        conn.execute(
            "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(SCHEMA_VERSION),),
        )
        self._conn = conn
        # The database holds public keys and access history, not secrets, but
        # there is no reason for anything else on the system to read it.
        try:
            self._path.chmod(0o600)
        except OSError:
            pass

    async def close(self) -> None:
        await asyncio.to_thread(self._close_sync)

    def _close_sync(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def _run(self, fn, *args):
        with self._lock:
            if self._conn is None:
                raise RuntimeError("store is not open")
            return fn(self._conn, *args)

    async def _call(self, fn, *args):
        return await asyncio.to_thread(self._run, fn, *args)

    # -- devices ------------------------------------------------------------ #

    async def upsert_device(
        self, *, device_id: str, pubkey: bytes, name: str, platform: str, now: int
    ) -> DeviceRecord:
        """Enroll a device, or re-enroll one that is pairing again.

        Re-pairing clears ``revoked_at``. That is the intended way back in after a
        revocation: it still requires a fresh code and a fresh local approval, so
        it grants nothing that a first-time pairing would not.
        """

        def op(conn: sqlite3.Connection) -> DeviceRecord:
            conn.execute(
                """
                INSERT INTO devices(device_id, pubkey, name, platform, paired_at,
                                    last_seen_at, revoked_at)
                VALUES(?, ?, ?, ?, ?, NULL, NULL)
                ON CONFLICT(device_id) DO UPDATE SET
                    name       = excluded.name,
                    platform   = excluded.platform,
                    paired_at  = excluded.paired_at,
                    revoked_at = NULL
                """,
                (device_id, pubkey, name, platform, now),
            )
            row = conn.execute(
                "SELECT * FROM devices WHERE device_id = ?", (device_id,)
            ).fetchone()
            return _device_from_row(row)

        return await self._call(op)

    async def get_device(self, device_id: str) -> DeviceRecord | None:
        def op(conn: sqlite3.Connection) -> DeviceRecord | None:
            row = conn.execute(
                "SELECT * FROM devices WHERE device_id = ?", (device_id,)
            ).fetchone()
            return _device_from_row(row) if row else None

        return await self._call(op)

    async def list_devices(self, *, include_revoked: bool = True) -> list[DeviceRecord]:
        def op(conn: sqlite3.Connection) -> list[DeviceRecord]:
            sql = "SELECT * FROM devices"
            if not include_revoked:
                sql += " WHERE revoked_at IS NULL"
            sql += " ORDER BY paired_at ASC"
            return [_device_from_row(row) for row in conn.execute(sql)]

        return await self._call(op)

    async def revoke_device(self, device_id: str, now: int) -> bool:
        def op(conn: sqlite3.Connection) -> bool:
            cur = conn.execute(
                "UPDATE devices SET revoked_at = ? WHERE device_id = ? AND revoked_at IS NULL",
                (now, device_id),
            )
            return cur.rowcount > 0

        return await self._call(op)

    async def delete_device(self, device_id: str) -> bool:
        def op(conn: sqlite3.Connection) -> bool:
            cur = conn.execute("DELETE FROM devices WHERE device_id = ?", (device_id,))
            conn.execute("DELETE FROM nonces WHERE device_id = ?", (device_id,))
            return cur.rowcount > 0

        return await self._call(op)

    async def touch_device(self, device_id: str, now: int) -> None:
        def op(conn: sqlite3.Connection) -> None:
            conn.execute(
                "UPDATE devices SET last_seen_at = ? WHERE device_id = ?", (now, device_id)
            )

        await self._call(op)

    # -- nonces ------------------------------------------------------------- #

    async def consume_nonce(self, device_id: str, nonce: str, expires_at: int) -> bool:
        """Record a nonce, returning False if it was already used.

        Atomic by virtue of the primary key: the INSERT either succeeds or raises
        IntegrityError, with no check-then-act race between concurrent requests.
        """

        def op(conn: sqlite3.Connection) -> bool:
            try:
                conn.execute(
                    "INSERT INTO nonces(device_id, nonce, expires_at) VALUES(?, ?, ?)",
                    (device_id, nonce, expires_at),
                )
            except sqlite3.IntegrityError:
                return False
            return True

        return await self._call(op)

    async def sweep_nonces(self, now: int) -> int:
        def op(conn: sqlite3.Connection) -> int:
            cur = conn.execute("DELETE FROM nonces WHERE expires_at <= ?", (now,))
            return cur.rowcount

        return await self._call(op)

    async def count_nonces(self) -> int:
        def op(conn: sqlite3.Connection) -> int:
            return int(conn.execute("SELECT COUNT(*) FROM nonces").fetchone()[0])

        return await self._call(op)

    # -- audit -------------------------------------------------------------- #

    async def add_audit(
        self,
        *,
        ts: int,
        action: str,
        result: str,
        device_id: str | None = None,
        peer_ip: str | None = None,
        detail: str | None = None,
    ) -> None:
        def op(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO audit(ts, device_id, action, result, peer_ip, detail) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (ts, device_id, action, result, peer_ip, detail),
            )

        await self._call(op)

    async def tail_audit(self, limit: int = 50) -> list[AuditRecord]:
        limit = max(1, min(int(limit), 1000))

        def op(conn: sqlite3.Connection) -> list[AuditRecord]:
            rows: Iterable[sqlite3.Row] = conn.execute(
                "SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)
            )
            return [
                AuditRecord(
                    id=row["id"],
                    ts=row["ts"],
                    device_id=row["device_id"],
                    action=row["action"],
                    result=row["result"],
                    peer_ip=row["peer_ip"],
                    detail=row["detail"],
                )
                for row in rows
            ]

        return await self._call(op)

    async def prune_audit(self, keep: int = 5000) -> int:
        """Bound the audit table so an attacker cannot fill the disk by
        hammering the endpoint."""

        def op(conn: sqlite3.Connection) -> int:
            cur = conn.execute(
                "DELETE FROM audit WHERE id <= "
                "(SELECT MAX(id) FROM audit) - ?",
                (keep,),
            )
            return cur.rowcount

        return await self._call(op)


def format_devices(devices: Sequence[DeviceRecord]) -> list[dict[str, Any]]:
    return [device.to_dict() for device in devices]

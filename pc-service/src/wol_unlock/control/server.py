"""Unix-socket control server."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket
import struct
import time
from pathlib import Path
from typing import Any

from ..context import ServiceContext
from ..errors import ApiError
from . import protocol as P

log = logging.getLogger("wol_unlock.control")

_UCRED_FMT = "3i"  # pid, uid, gid


class _Connection:
    """One connected CLI process."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer
        self.events: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=64)

    def push(self, message: dict[str, Any]) -> None:
        """Queue an event, dropping it if the client is not draining.

        A stalled CLI must never apply backpressure to the pairing flow.
        """
        try:
            self.events.put_nowait(message)
        except asyncio.QueueFull:
            pass


class ControlServer:
    def __init__(self, context: ServiceContext, path: Path) -> None:
        self._context = context
        self._path = path
        self._server: asyncio.AbstractServer | None = None
        self._connections: set[_Connection] = set()

    # -- lifecycle ---------------------------------------------------------- #

    #: ``sockaddr_un.sun_path`` is a fixed 108-byte buffer on Linux. Checking it
    #: ourselves turns a bare "AF_UNIX path too long" OSError into something that
    #: says which path and what to do about it.
    MAX_SOCKET_PATH = 107

    async def start(self) -> None:
        encoded = str(self._path).encode("utf-8")
        if len(encoded) > self.MAX_SOCKET_PATH:
            raise RuntimeError(
                f"control socket path is {len(encoded)} bytes, over the "
                f"{self.MAX_SOCKET_PATH}-byte AF_UNIX limit: {self._path}\n"
                f"Set XDG_RUNTIME_DIR to a shorter directory (normally /run/user/{os.getuid()})."
            )
        self._unlink_stale()
        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # The parent directory ($XDG_RUNTIME_DIR) is already 0700 and owned by us,
        # so the socket is unreachable by other users even before the chmod below.
        # The chmod and the SO_PEERCRED check in _handle are belt and braces.
        self._server = await asyncio.start_unix_server(self._handle, path=str(self._path))
        os.chmod(self._path, 0o600)
        self._context.pairing.add_listener(self._on_pairing_event)
        log.info("control socket listening on %s", self._path)

    def _unlink_stale(self) -> None:
        """Remove a socket left behind by a crashed process.

        Only if nothing is actually listening -- otherwise a second instance
        would silently steal the socket from a healthy one.
        """
        if not self._path.exists():
            return
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            probe.connect(str(self._path))
        except OSError:
            self._path.unlink(missing_ok=True)
            return
        finally:
            probe.close()
        raise RuntimeError(f"another wol-unlock instance is already using {self._path}")

    async def stop(self) -> None:
        self._context.pairing.remove_listener(self._on_pairing_event)
        if self._server is not None:
            self._server.close()
            with contextlib.suppress(Exception):
                await self._server.wait_closed()
            self._server = None
        for conn in list(self._connections):
            with contextlib.suppress(Exception):
                conn.writer.close()
        self._connections.clear()
        self._path.unlink(missing_ok=True)

    # -- events ------------------------------------------------------------- #

    def _on_pairing_event(self, name: str, data: dict[str, Any]) -> None:
        message = P.event(name, data)
        for conn in list(self._connections):
            conn.push(message)

    # -- connection handling ------------------------------------------------ #

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if not self._authorized(writer):
            writer.close()
            return

        conn = _Connection(reader, writer)
        self._connections.add(conn)
        pump = asyncio.create_task(self._pump_events(conn))
        try:
            await self._read_commands(conn)
        except (ConnectionResetError, asyncio.IncompleteReadError):
            pass
        except Exception:  # noqa: BLE001
            log.exception("control connection failed")
        finally:
            pump.cancel()
            with contextlib.suppress(Exception):
                await pump
            self._connections.discard(conn)
            with contextlib.suppress(Exception):
                writer.close()
                await writer.wait_closed()

    def _authorized(self, writer: asyncio.StreamWriter) -> bool:
        """Only the user running the service may talk to the control socket."""
        sock = writer.get_extra_info("socket")
        if sock is None:
            return False
        try:
            raw = sock.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize(_UCRED_FMT)
            )
            _pid, uid, _gid = struct.unpack(_UCRED_FMT, raw)
        except OSError:
            log.warning("cannot read SO_PEERCRED; rejecting control connection")
            return False
        if uid != os.getuid():
            log.warning("rejecting control connection from uid %d", uid)
            return False
        return True

    async def _pump_events(self, conn: _Connection) -> None:
        while True:
            message = await conn.events.get()
            try:
                conn.writer.write(P.encode(message))
                await conn.writer.drain()
            except (ConnectionResetError, BrokenPipeError):
                return

    async def _read_commands(self, conn: _Connection) -> None:
        while True:
            try:
                line = await conn.reader.readuntil(b"\n")
            except asyncio.LimitOverrunError:
                await self._send(conn, P.error(None, "bad_request", "control line too long"))
                return
            except asyncio.IncompleteReadError:
                return
            if not line:
                return
            if len(line) > P.MAX_LINE_BYTES:
                await self._send(conn, P.error(None, "bad_request", "control line too long"))
                return

            request_id: Any = None
            try:
                message = P.decode(line)
                request_id = message.get("id")
                command = message.get("cmd")
                args = message.get("args") or {}
                if not isinstance(args, dict):
                    raise ValueError("args must be an object")
                if command not in P.COMMANDS:
                    raise ApiError("bad_request", f"unknown command {command!r}")
                data = await self._dispatch(str(command), args)
            except ApiError as exc:
                await self._send(conn, P.error(request_id, exc.code, exc.message))
            except (ValueError, UnicodeDecodeError) as exc:
                await self._send(conn, P.error(request_id, "bad_request", str(exc)))
            except Exception as exc:  # noqa: BLE001
                log.exception("control command failed")
                await self._send(conn, P.error(request_id, "internal_error", str(exc)))
            else:
                await self._send(conn, P.response(request_id, data))

    async def _send(self, conn: _Connection, message: dict[str, Any]) -> None:
        try:
            conn.writer.write(P.encode(message))
            await conn.writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            pass

    # -- commands ----------------------------------------------------------- #

    async def _dispatch(self, command: str, args: dict[str, Any]) -> Any:
        ctx = self._context

        if command == P.CMD_STATUS:
            from .. import session as session_mod
            from .. import wake as wake_mod

            current = await session_mod.current_session()
            return {
                **ctx.server_info(),
                "uptime_s": ctx.uptime_s,
                "session": current.to_dict() if current else None,
                "pairing": ctx.pairing.snapshot(),
                "wake_targets": wake_mod.describe_targets(ctx.config.wake_targets),
                "http": {
                    "bind": ctx.config.http.bind,
                    "port": ctx.config.http.port,
                    "allowed_networks": [str(n) for n in ctx.config.http.allowed_networks],
                },
                "devices": len(await ctx.store.list_devices(include_revoked=False)),
                "config_path": str(ctx.config.source_path) if ctx.config.source_path else None,
                "unlock_enabled": ctx.config.unlock_enabled,
            }

        if command == P.CMD_PAIR_BEGIN:
            window = args.get("window_s")
            return await ctx.pairing.begin(int(window) if window is not None else None)

        if command == P.CMD_PAIR_CANCEL:
            await ctx.pairing.cancel("cancelled")
            return {"cancelled": True}

        if command == P.CMD_PAIR_APPROVE:
            return {"resolved": await ctx.pairing.resolve(True)}

        if command == P.CMD_PAIR_DENY:
            return {"resolved": await ctx.pairing.resolve(False)}

        if command == P.CMD_DEVICES_LIST:
            devices = await ctx.store.list_devices(include_revoked=True)
            return {"devices": [d.to_dict() for d in devices]}

        if command in (P.CMD_DEVICES_REVOKE, P.CMD_DEVICES_DELETE):
            selector = args.get("device")
            if not isinstance(selector, str) or not selector:
                raise ApiError("bad_request", "device selector is required")
            device = await self._resolve_device(selector)
            if command == P.CMD_DEVICES_REVOKE:
                changed = await ctx.store.revoke_device(device.device_id, int(time.time()))
            else:
                changed = await ctx.store.delete_device(device.device_id)
            await ctx.store.add_audit(
                ts=int(time.time()),
                action=command,
                result="ok" if changed else "noop",
                device_id=device.device_id,
                detail=device.name,
            )
            return {"device": device.to_dict(), "changed": changed}

        if command == P.CMD_AUDIT_TAIL:
            limit = args.get("limit", 50)
            rows = await ctx.store.tail_audit(int(limit) if isinstance(limit, int) else 50)
            return {"entries": [row.to_dict() for row in rows]}

        raise ApiError("bad_request", f"unhandled command {command!r}")

    async def _resolve_device(self, selector: str):
        """Find a device by exact id, or by a unique name/fingerprint prefix.

        Ambiguity is an error rather than a guess -- revoking the wrong device is
        not something to be helpful about.
        """
        devices = await self._context.store.list_devices(include_revoked=True)
        for device in devices:
            if device.device_id == selector:
                return device

        needle = selector.lower()
        matches = [
            device
            for device in devices
            if device.device_id.lower().startswith(needle)
            or device.name.lower().startswith(needle)
            or device.to_dict()["fp"].lower().startswith(needle)
        ]
        if not matches:
            raise ApiError("bad_request", f"no device matches {selector!r}")
        if len(matches) > 1:
            names = ", ".join(f"{d.name} ({d.device_id})" for d in matches)
            raise ApiError("bad_request", f"{selector!r} is ambiguous: {names}")
        return matches[0]

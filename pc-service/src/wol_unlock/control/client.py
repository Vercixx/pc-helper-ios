"""Async client for the control socket, used by ``wol-unlockctl``."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any

from . import protocol as P


class ControlError(Exception):
    """A command the service refused."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class ControlClient:
    """One connection. Commands and unsolicited events share it, so a reader
    task demultiplexes replies (by id) from events (by name)."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._reader = reader
        self._writer = writer
        self._next_id = 0
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._closed = asyncio.Event()
        self._pump = asyncio.create_task(self._read_loop())

    @classmethod
    async def connect(cls, path: Path) -> "ControlClient":
        try:
            reader, writer = await asyncio.open_unix_connection(str(path))
        except (FileNotFoundError, ConnectionRefusedError) as exc:
            raise ControlError(
                "not_running",
                f"cannot reach the service at {path}. Is it running?\n"
                f"  systemctl --user status wol-unlock",
            ) from exc
        return cls(reader, writer)

    async def _read_loop(self) -> None:
        try:
            while True:
                line = await self._reader.readuntil(b"\n")
                if not line:
                    break
                try:
                    message = P.decode(line)
                except ValueError:
                    continue
                if "event" in message:
                    await self._events.put(message)
                    continue
                request_id = message.get("id")
                future = self._pending.pop(request_id, None) if request_id is not None else None
                if future is not None and not future.done():
                    future.set_result(message)
        except (asyncio.IncompleteReadError, ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            self._closed.set()
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(
                        ControlError("connection_lost", "the service closed the connection")
                    )
            self._pending.clear()

    async def call(self, command: str, timeout: float = 15.0, **args: Any) -> dict[str, Any]:
        if self._closed.is_set():
            raise ControlError("connection_lost", "control connection is closed")
        self._next_id += 1
        request_id = self._next_id
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        self._writer.write(P.encode({"id": request_id, "cmd": command, "args": args}))
        await self._writer.drain()

        try:
            message = await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(request_id, None)
            raise ControlError("timeout", f"{command} timed out after {timeout:g}s") from None

        if not message.get("ok"):
            err = message.get("error") or {}
            raise ControlError(
                str(err.get("code", "error")), str(err.get("message", "command failed"))
            )
        return message.get("data") or {}

    async def next_event(self, timeout: float | None = None) -> dict[str, Any] | None:
        """Next unsolicited event, or None on timeout / disconnect."""
        getter = asyncio.ensure_future(self._events.get())
        closed = asyncio.ensure_future(self._closed.wait())
        try:
            done, _ = await asyncio.wait(
                {getter, closed}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
            if getter in done:
                return getter.result()
            return None
        finally:
            for task in (getter, closed):
                if not task.done():
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await task

    async def close(self) -> None:
        self._pump.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await self._pump
        with contextlib.suppress(Exception):
            self._writer.close()
            await self._writer.wait_closed()

"""``wol-unlockctl`` -- the local management interface.

Everything here talks to the running service over the 0600 Unix socket. Opening a
pairing window is only possible through this path, which is what makes "pairing
requires physical access to the PC" true by construction.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
from typing import Any

from rich.text import Text

from ..config import control_socket_path
from ..control.client import ControlClient, ControlError
from ..control import protocol as P
from . import render
from .render import console


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wol-unlockctl",
        description="Manage the wol-unlock service running for this user.",
    )
    parser.add_argument("--socket", default=None, help="path to the control socket")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="show service, session and wake status")

    pair = sub.add_parser("pair", help="open a pairing window and show the code/QR")
    pair.add_argument("--window", type=int, default=None, help="window length in seconds")
    pair.add_argument("--no-qr", action="store_true", help="print only the code")
    pair.add_argument(
        "--light-terminal",
        action="store_true",
        help="invert the QR for terminals with a light background",
    )
    pair.add_argument(
        "--yes",
        action="store_true",
        help="approve the first device automatically (for scripted setup)",
    )

    sub.add_parser("devices", help="list trusted devices")

    revoke = sub.add_parser("revoke", help="revoke a device by id, name or fingerprint prefix")
    revoke.add_argument("device")

    remove = sub.add_parser("remove", help="delete a device record entirely")
    remove.add_argument("device")

    audit = sub.add_parser("audit", help="show recent activity")
    audit.add_argument("-n", "--limit", type=int, default=25)

    discover = sub.add_parser("discover", help="browse the LAN for advertised services")
    discover.add_argument("--timeout", type=float, default=3.0)

    return parser


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

async def cmd_status(client: ControlClient, _args: argparse.Namespace) -> int:
    console.print(render.render_status(await client.call(P.CMD_STATUS)))
    return 0


async def cmd_devices(client: ControlClient, _args: argparse.Namespace) -> int:
    data = await client.call(P.CMD_DEVICES_LIST)
    devices = data.get("devices") or []
    if not devices:
        console.print("[dim]No devices are paired. Run[/dim] wol-unlockctl pair")
        return 0
    console.print(render.render_devices(devices))
    return 0


async def cmd_revoke(client: ControlClient, args: argparse.Namespace) -> int:
    data = await client.call(P.CMD_DEVICES_REVOKE, device=args.device)
    device = data.get("device") or {}
    if data.get("changed"):
        console.print(f"[green]Revoked[/green] {device.get('name')} ({device.get('device_id')})")
    else:
        console.print(f"[yellow]{device.get('name')} was already revoked[/yellow]")
    return 0


async def cmd_remove(client: ControlClient, args: argparse.Namespace) -> int:
    data = await client.call(P.CMD_DEVICES_DELETE, device=args.device)
    device = data.get("device") or {}
    console.print(f"[green]Deleted[/green] {device.get('name')} ({device.get('device_id')})")
    return 0


async def cmd_audit(client: ControlClient, args: argparse.Namespace) -> int:
    data = await client.call(P.CMD_AUDIT_TAIL, limit=args.limit)
    entries = data.get("entries") or []
    if not entries:
        console.print("[dim]No activity recorded yet.[/dim]")
        return 0
    console.print(render.render_audit(entries))
    return 0


async def cmd_pair(client: ControlClient, args: argparse.Namespace) -> int:
    """Open a window, show the code, and drive the approval prompt."""
    opened = await client.call(P.CMD_PAIR_BEGIN, window_s=args.window)
    console.print(
        render.render_pairing_panel(
            opened, show_qr=not args.no_qr, light_terminal=args.light_terminal
        )
    )
    console.print("[dim]Press Ctrl-C to cancel.[/dim]\n")

    deadline = asyncio.get_running_loop().time() + float(opened.get("expires_in_s", 120)) + 90

    try:
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                console.print("[yellow]Pairing window closed.[/yellow]")
                return 1

            event = await client.next_event(timeout=remaining)
            if event is None:
                console.print("[yellow]Pairing window closed.[/yellow]")
                return 1

            name = event.get("event")
            data = event.get("data") or {}

            if name == P.EVENT_PAIR_REQUEST:
                if not await _prompt_approval(client, data, auto_yes=args.yes):
                    return 1

            elif name == P.EVENT_PAIR_COMPLETED:
                console.print(
                    f"\n[bold green]Paired[/bold green] {data.get('name')} "
                    f"([dim]{data.get('device_id')}[/dim])"
                )
                console.print("[dim]It can now wake and unlock this PC.[/dim]")
                return 0

            elif name == P.EVENT_PAIR_CLOSED:
                reason = data.get("reason", "closed")
                if reason == "paired":
                    return 0
                console.print(f"[yellow]Pairing window closed: {reason}[/yellow]")
                return 1

    except (KeyboardInterrupt, asyncio.CancelledError):
        console.print("\n[yellow]Cancelled.[/yellow]")
        with contextlib.suppress(ControlError):
            await client.call(P.CMD_PAIR_CANCEL)
        return 130


async def _prompt_approval(
    client: ControlClient, data: dict[str, Any], *, auto_yes: bool
) -> bool:
    """Ask the operator to approve one enrolling device.

    The fingerprint is printed so it can be compared against what the phone
    shows -- that comparison is what defeats a race in which someone else on the
    LAN raced to submit the code first.
    """
    console.print(
        Text.assemble(
            ("\nDevice requesting access\n", "bold"),
            ("  name        ", "dim"), (f"{data.get('device_name')}\n", ""),
            ("  platform    ", "dim"), (f"{data.get('platform') or '-'}\n", ""),
            ("  device id   ", "dim"), (f"{data.get('device_id')}\n", ""),
            ("  fingerprint ", "dim"), (f"{data.get('fp')}\n", "cyan"),
        )
    )

    if auto_yes:
        console.print("[dim]--yes given; approving.[/dim]")
        await client.call(P.CMD_PAIR_APPROVE)
        return True

    try:
        answer = await asyncio.to_thread(input, "Approve this device? [y/N] ")
    except (EOFError, KeyboardInterrupt):
        answer = ""

    if answer.strip().lower() in ("y", "yes"):
        await client.call(P.CMD_PAIR_APPROVE)
        return True

    await client.call(P.CMD_PAIR_DENY)
    console.print("[yellow]Denied.[/yellow]")
    return False


async def cmd_discover(_client: ControlClient | None, args: argparse.Namespace) -> int:
    """Browse for advertisements. Runs without the service, as a network test."""
    from ..discovery import browse

    with console.status(f"Browsing _wol-unlock._tcp for {args.timeout:g}s…"):
        services = await browse(args.timeout)
    if not services:
        console.print("[yellow]No services found.[/yellow]")
        console.print("[dim]If the service is running here, check that udp/5353 is allowed.[/dim]")
        return 1
    console.print(render.render_discovered(services))
    return 0


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

COMMANDS = {
    "status": cmd_status,
    "pair": cmd_pair,
    "devices": cmd_devices,
    "revoke": cmd_revoke,
    "remove": cmd_remove,
    "audit": cmd_audit,
}


async def run(args: argparse.Namespace) -> int:
    # discover talks to the network, not to the service, so it works even when
    # the service is stopped -- which is exactly when you want to check it.
    if args.command == "discover":
        return await cmd_discover(None, args)

    path = args.socket or control_socket_path()
    client = await ControlClient.connect(path)
    try:
        return await COMMANDS[args.command](client, args)
    finally:
        await client.close()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(run(args))
    except ControlError as exc:
        console.print(f"[red]{exc.code}[/red]: {exc.message}")
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())

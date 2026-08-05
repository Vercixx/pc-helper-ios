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
from ..i18n import _
from ..control.client import ControlClient, ControlError
from ..control import protocol as P
from . import render
from .render import console


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wol-unlockctl",
        description=_("cli.description"),
    )
    parser.add_argument("--socket", default=None, help=_("cli.socket"))
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help=_("cli.cmd.status"))

    pair = sub.add_parser("pair", help=_("cli.cmd.pair"))
    pair.add_argument("--window", type=int, default=None, help=_("cli.opt.window"))
    pair.add_argument("--no-qr", action="store_true", help=_("cli.opt.noQr"))
    pair.add_argument("--light-terminal", action="store_true", help=_("cli.opt.lightTerminal"))
    pair.add_argument("--yes", action="store_true", help=_("cli.opt.yes"))

    sub.add_parser("devices", help=_("cli.cmd.devices"))

    revoke = sub.add_parser("revoke", help=_("cli.cmd.revoke"))
    revoke.add_argument("device")

    remove = sub.add_parser("remove", help=_("cli.cmd.remove"))
    remove.add_argument("device")

    audit = sub.add_parser("audit", help=_("cli.cmd.audit"))
    audit.add_argument("-n", "--limit", type=int, default=25)

    discover = sub.add_parser("discover", help=_("cli.cmd.discover"))
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
        console.print(f"[dim]{_('cli.noDevices')}[/dim] wol-unlockctl pair")
        return 0
    console.print(render.render_devices(devices))
    return 0


async def cmd_revoke(client: ControlClient, args: argparse.Namespace) -> int:
    data = await client.call(P.CMD_DEVICES_REVOKE, device=args.device)
    device = data.get("device") or {}
    if data.get("changed"):
        console.print(
            f"[green]{_('cli.revoked')}[/green] {device.get('name')} ({device.get('device_id')})"
        )
    else:
        console.print(f"[yellow]{_('cli.alreadyRevoked', name=device.get('name'))}[/yellow]")
    return 0


async def cmd_remove(client: ControlClient, args: argparse.Namespace) -> int:
    data = await client.call(P.CMD_DEVICES_DELETE, device=args.device)
    device = data.get("device") or {}
    console.print(
        f"[green]{_('cli.deleted')}[/green] {device.get('name')} ({device.get('device_id')})"
    )
    return 0


async def cmd_audit(client: ControlClient, args: argparse.Namespace) -> int:
    data = await client.call(P.CMD_AUDIT_TAIL, limit=args.limit)
    entries = data.get("entries") or []
    if not entries:
        console.print(f"[dim]{_('cli.noActivity')}[/dim]")
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
    console.print(f"[dim]{_('cli.cancelHint')}[/dim]\n")

    deadline = asyncio.get_running_loop().time() + float(opened.get("expires_in_s", 120)) + 90

    try:
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                console.print(f"[yellow]{_('cli.windowClosed')}[/yellow]")
                return 1

            event = await client.next_event(timeout=remaining)
            if event is None:
                console.print(f"[yellow]{_('cli.windowClosed')}[/yellow]")
                return 1

            name = event.get("event")
            data = event.get("data") or {}

            if name == P.EVENT_PAIR_REQUEST:
                if not await _prompt_approval(client, data, auto_yes=args.yes):
                    return 1

            elif name == P.EVENT_PAIR_COMPLETED:
                console.print(
                    f"\n[bold green]{_('cli.paired')}[/bold green] {data.get('name')} "
                    f"([dim]{data.get('device_id')}[/dim])"
                )
                console.print(f"[dim]{_('cli.pairedHint')}[/dim]")
                return 0

            elif name == P.EVENT_PAIR_CLOSED:
                reason = data.get("reason", "closed")
                if reason == "paired":
                    return 0
                console.print(f"[yellow]{_('cli.windowClosedReason', reason=reason)}[/yellow]")
                return 1

    except (KeyboardInterrupt, asyncio.CancelledError):
        console.print(f"\n[yellow]{_('cli.cancelled')}[/yellow]")
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
            (f"\n{_('cli.request.title')}\n", "bold"),
            (f"  {_('cli.request.name'):<12}", "dim"), (f"{data.get('device_name')}\n", ""),
            (f"  {_('cli.request.platform'):<12}", "dim"), (f"{data.get('platform') or '-'}\n", ""),
            (f"  {_('cli.request.id'):<12}", "dim"), (f"{data.get('device_id')}\n", ""),
            (f"  {_('cli.request.fp'):<12}", "dim"), (f"{data.get('fp')}\n", "cyan"),
        )
    )

    if auto_yes:
        console.print(f"[dim]{_('cli.autoApprove')}[/dim]")
        await client.call(P.CMD_PAIR_APPROVE)
        return True

    try:
        answer = await asyncio.to_thread(input, _("cli.approvePrompt"))
    except (EOFError, KeyboardInterrupt):
        answer = ""

    # "y"/"yes" stay accepted in every language: they are what muscle memory
    # types, and a Russian keyboard layout still has the Latin keys.
    if answer.strip().lower() in ("y", "yes", _("cli.approveYes")):
        await client.call(P.CMD_PAIR_APPROVE)
        return True

    await client.call(P.CMD_PAIR_DENY)
    console.print(f"[yellow]{_('cli.denied')}[/yellow]")
    return False


async def cmd_discover(_client: ControlClient | None, args: argparse.Namespace) -> int:
    """Browse for advertisements. Runs without the service, as a network test."""
    from ..discovery import browse

    with console.status(_("cli.browsing", timeout=args.timeout)):
        services = await browse(args.timeout)
    if not services:
        console.print(f"[yellow]{_('cli.noServices')}[/yellow]")
        console.print(f"[dim]{_('cli.noServicesHint')}[/dim]")
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

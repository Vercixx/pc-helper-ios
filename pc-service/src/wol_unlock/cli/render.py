"""Rich-based rendering for the terminal UI."""

from __future__ import annotations

import io
import time
from typing import Any, Sequence

import qrcode
from qrcode.constants import ERROR_CORRECT_L
from rich.align import Align
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #

def fmt_ts(ts: int | None) -> str:
    if not ts:
        return "never"
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
    return f"{when} ({fmt_ago(ts)})"


def fmt_ago(ts: int | None) -> str:
    if not ts:
        return "never"
    delta = int(time.time()) - int(ts)
    if delta < 0:
        return "in the future"
    for size, unit in ((86400, "d"), (3600, "h"), (60, "m")):
        if delta >= size:
            return f"{delta // size}{unit} ago"
    return f"{delta}s ago"


def fmt_bool(value: Any, yes: str = "yes", no: str = "no") -> Text:
    return Text(yes, style="green") if value else Text(no, style="dim")


# --------------------------------------------------------------------------- #
# QR
# --------------------------------------------------------------------------- #

def render_qr(payload: str, *, light_terminal: bool = False) -> str:
    """ASCII QR sized for a terminal.

    ``invert`` is on by default: on a dark terminal the filled blocks read as the
    light quiet zone and the gaps as dark modules, which is the polarity a phone
    camera expects. Pass ``light_terminal=True`` on a light colour scheme.
    """
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_L, border=2)
    qr.add_data(payload)
    qr.make(fit=True)
    buffer = io.StringIO()
    qr.print_ascii(out=buffer, invert=not light_terminal)
    return buffer.getvalue().rstrip("\n")


def render_pairing_panel(data: dict[str, Any], *, show_qr: bool = True,
                         light_terminal: bool = False) -> Panel:
    code = data.get("code_display") or data.get("code", "")
    blocks: list[Any] = []

    if show_qr:
        blocks.append(Align.center(Text(render_qr(data.get("qr", ""), light_terminal=light_terminal))))
        blocks.append(Text(""))

    blocks.append(Align.center(Text(code, style="bold cyan on grey15")))
    blocks.append(Text(""))
    blocks.append(
        Align.center(
            Text.assemble(
                ("Scan the code, or type it into the app.  ", "dim"),
                (f"Expires in {data.get('expires_in_s', 0)}s", "yellow"),
            )
        )
    )
    if data.get("require_approval", True):
        blocks.append(
            Align.center(Text("You will be asked to approve the device here.", style="dim"))
        )
    blocks.append(Text(""))
    blocks.append(
        Align.center(Text(f"server fingerprint  {data.get('server_fp', '')[:16]}…", style="dim"))
    )

    return Panel(
        Group(*blocks),
        title="[bold]Pairing mode[/bold]",
        border_style="cyan",
        padding=(1, 2),
    )


# --------------------------------------------------------------------------- #
# Tables
# --------------------------------------------------------------------------- #

def render_devices(devices: Sequence[dict[str, Any]]) -> Table:
    table = Table(title="Trusted devices", header_style="bold", expand=False)
    table.add_column("Device", style="bold")
    table.add_column("ID")
    table.add_column("Fingerprint")
    table.add_column("Platform")
    table.add_column("Paired")
    table.add_column("Last seen")
    table.add_column("State")

    for device in devices:
        revoked = device.get("revoked")
        table.add_row(
            device.get("name", "?"),
            device.get("device_id", ""),
            (device.get("fp") or "")[:16] + "…",
            device.get("platform") or "-",
            fmt_ago(device.get("paired_at")),
            fmt_ago(device.get("last_seen_at")),
            Text("revoked", style="red") if revoked else Text("active", style="green"),
        )
    return table


def render_status(data: dict[str, Any]) -> Group:
    head = Table.grid(padding=(0, 2))
    head.add_column(style="dim", justify="right")
    head.add_column()

    head.add_row("name", str(data.get("name", "")))
    head.add_row("fingerprint", str(data.get("fp", "")))
    head.add_row("api", str(data.get("api", "")))
    head.add_row("uptime", f"{data.get('uptime_s', 0)}s")
    http = data.get("http") or {}
    head.add_row("listening", f"{http.get('bind')}:{http.get('port')}")
    head.add_row("allowed", ", ".join(http.get("allowed_networks") or []))
    head.add_row("devices", str(data.get("devices", 0)))
    head.add_row("capabilities", ", ".join(data.get("caps") or []))
    head.add_row("unlock", fmt_bool(data.get("unlock_enabled"), "enabled", "disabled"))
    if data.get("config_path"):
        head.add_row("config", str(data["config_path"]))

    session = data.get("session")
    if session:
        state = Text("locked", style="yellow") if session.get("locked") else Text("unlocked", style="green")
        head.add_row(
            "session",
            Text.assemble(
                f"{session.get('id')} ",
                (f"{session.get('desktop') or '?'}/{session.get('type')} ", "dim"),
                state,
            ),
        )
    else:
        head.add_row("session", Text("none found", style="red"))

    pairing = data.get("pairing") or {}
    if pairing.get("active"):
        head.add_row(
            "pairing",
            Text(f"{pairing.get('state')} ({pairing.get('expires_in_s', 0)}s left)", style="cyan"),
        )
    else:
        head.add_row("pairing", Text("closed", style="dim"))

    blocks: list[Any] = [Panel(head, title="[bold]wol-unlock[/bold]", border_style="blue")]

    targets = data.get("wake_targets") or []
    if targets:
        table = Table(title="Wake targets", header_style="bold")
        table.add_column("MAC")
        table.add_column("Interface")
        table.add_column("Broadcast")
        table.add_column("Link")
        for target in targets:
            link = target.get("link", "?")
            style = "green" if link == "up" else "yellow" if link == "down" else "dim"
            table.add_row(
                target.get("mac", ""),
                target.get("iface") or "-",
                f"{target.get('broadcast')}:{target.get('port')}",
                Text(link, style=style),
            )
        blocks.append(table)

    return Group(*blocks)


def render_audit(entries: Sequence[dict[str, Any]]) -> Table:
    table = Table(title="Recent activity", header_style="bold")
    table.add_column("When", style="dim")
    table.add_column("Action")
    table.add_column("Result")
    table.add_column("Device")
    table.add_column("From", style="dim")
    table.add_column("Detail", style="dim", overflow="fold")

    for entry in reversed(list(entries)):
        result = entry.get("result", "")
        style = "green" if result == "ok" else "red"
        table.add_row(
            fmt_ago(entry.get("ts")),
            entry.get("action", ""),
            Text(result, style=style),
            (entry.get("device_id") or "-")[:12],
            entry.get("peer_ip") or "-",
            entry.get("detail") or "",
        )
    return table


def render_discovered(services: Sequence[dict[str, Any]]) -> Table:
    table = Table(title="Discovered services (_wol-unlock._tcp)", header_style="bold")
    table.add_column("Name", style="bold")
    table.add_column("Host")
    table.add_column("Addresses")
    table.add_column("Fingerprint")
    table.add_column("Caps")
    table.add_column("Pairing")

    for service in services:
        table.add_row(
            service.get("name", ""),
            f"{service.get('host', '')}:{service.get('port', '')}",
            ", ".join(service.get("addresses") or []),
            (service.get("fp") or "")[:16] + "…",
            service.get("caps") or "",
            fmt_bool(service.get("pair") == "1", "open", "closed"),
        )
    return table

"""Rich-based rendering for the terminal UI.

Every visible string goes through ``i18n._``; see that module for the language
selection and for why ApiError messages are excluded.
"""

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

from ..i18n import _

console = Console()


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #

def fmt_ts(ts: int | None) -> str:
    if not ts:
        return _("never")
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
    return f"{when} ({fmt_ago(ts)})"


def fmt_ago(ts: int | None) -> str:
    if not ts:
        return _("never")
    delta = int(time.time()) - int(ts)
    if delta < 0:
        return _("future")
    for size, key in ((86400, "ago.d"), (3600, "ago.h"), (60, "ago.m")):
        if delta >= size:
            return _(key, n=delta // size)
    return _("ago.s", n=delta)


def fmt_bool(value: Any, yes: str | None = None, no: str | None = None) -> Text:
    yes = _("yes") if yes is None else yes
    no = _("no") if no is None else no
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
                (_("pair.scan"), "dim"),
                (_("pair.expires", n=data.get("expires_in_s", 0)), "yellow"),
            )
        )
    )
    if data.get("require_approval", True):
        blocks.append(
            Align.center(Text(_("pair.willApprove"), style="dim"))
        )
    blocks.append(Text(""))
    blocks.append(
        Align.center(Text(_("pair.fingerprint", fp=data.get("server_fp", "")[:16]), style="dim"))
    )

    return Panel(
        Group(*blocks),
        title=f"[bold]{_('pair.title')}[/bold]",
        border_style="cyan",
        padding=(1, 2),
    )


# --------------------------------------------------------------------------- #
# Tables
# --------------------------------------------------------------------------- #

def render_devices(devices: Sequence[dict[str, Any]]) -> Table:
    table = Table(title=_("devices.title"), header_style="bold", expand=False)
    table.add_column(_("devices.name"), style="bold")
    table.add_column(_("devices.id"))
    table.add_column(_("devices.fp"))
    table.add_column(_("devices.platform"))
    table.add_column(_("devices.paired"))
    table.add_column(_("devices.lastSeen"))
    table.add_column(_("devices.state"))

    for device in devices:
        revoked = device.get("revoked")
        table.add_row(
            device.get("name", "?"),
            device.get("device_id", ""),
            (device.get("fp") or "")[:16] + "…",
            device.get("platform") or "-",
            fmt_ago(device.get("paired_at")),
            fmt_ago(device.get("last_seen_at")),
            Text(_("devices.revoked"), style="red")
            if revoked
            else Text(_("devices.active"), style="green"),
        )
    return table


def render_status(data: dict[str, Any]) -> Group:
    head = Table.grid(padding=(0, 2))
    head.add_column(style="dim", justify="right")
    head.add_column()

    head.add_row(_("status.name"), str(data.get("name", "")))
    head.add_row(_("status.fingerprint"), str(data.get("fp", "")))
    head.add_row(_("status.api"), str(data.get("api", "")))
    head.add_row(_("status.uptime"), f"{data.get('uptime_s', 0)}s")
    http = data.get("http") or {}
    head.add_row(_("status.listening"), f"{http.get('bind')}:{http.get('port')}")
    head.add_row(_("status.allowed"), ", ".join(http.get("allowed_networks") or []))
    head.add_row(_("status.devices"), str(data.get("devices", 0)))
    head.add_row(_("status.capabilities"), ", ".join(data.get("caps") or []))
    head.add_row(
        _("status.unlock"),
        fmt_bool(data.get("unlock_enabled"), _("status.enabled"), _("status.disabled")),
    )
    if data.get("config_path"):
        head.add_row(_("status.config"), str(data["config_path"]))

    session = data.get("session")
    if session:
        state = (
            Text(_("status.locked"), style="yellow")
            if session.get("locked")
            else Text(_("status.unlocked"), style="green")
        )
        head.add_row(
            _("status.session"),
            Text.assemble(
                f"{session.get('id')} ",
                (f"{session.get('desktop') or '?'}/{session.get('type')} ", "dim"),
                state,
            ),
        )
    else:
        head.add_row(_("status.session"), Text(_("status.noSession"), style="red"))

    pairing = data.get("pairing") or {}
    if pairing.get("active"):
        head.add_row(
            _("status.pairing"),
            Text(
                _(
                    "status.pairingOpen",
                    state=pairing.get("state"),
                    n=pairing.get("expires_in_s", 0),
                ),
                style="cyan",
            ),
        )
    else:
        head.add_row(_("status.pairing"), Text(_("status.pairingClosed"), style="dim"))

    blocks: list[Any] = [Panel(head, title="[bold]wol-unlock[/bold]", border_style="blue")]

    targets = data.get("wake_targets") or []
    if targets:
        table = Table(title=_("wake.title"), header_style="bold")
        table.add_column(_("wake.mac"))
        table.add_column(_("wake.iface"))
        table.add_column(_("wake.broadcast"))
        table.add_column(_("wake.link"))
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
    table = Table(title=_("audit.title"), header_style="bold")
    table.add_column(_("audit.when"), style="dim")
    table.add_column(_("audit.action"))
    table.add_column(_("audit.result"))
    table.add_column(_("audit.device"))
    table.add_column(_("audit.from"), style="dim")
    table.add_column(_("audit.detail"), style="dim", overflow="fold")

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
    table = Table(title=_("discover.title"), header_style="bold")
    table.add_column(_("discover.name"), style="bold")
    table.add_column(_("discover.host"))
    table.add_column(_("discover.addresses"))
    table.add_column(_("discover.fp"))
    table.add_column(_("discover.caps"))
    table.add_column(_("discover.pairing"))

    for service in services:
        table.add_row(
            service.get("name", ""),
            f"{service.get('host', '')}:{service.get('port', '')}",
            ", ".join(service.get("addresses") or []),
            (service.get("fp") or "")[:16] + "…",
            service.get("caps") or "",
            fmt_bool(service.get("pair") == "1", _("discover.open"), _("discover.closed")),
        )
    return table

"""Local control channel: a 0600 Unix socket used by ``wol-unlockctl``.

Administrative operations -- above all opening a pairing window -- live here and
*only* here. They have no HTTP route, so "pairing requires local access to the
machine" is a property of the transport rather than a policy that some future
handler could forget to enforce.
"""

from .server import ControlServer  # noqa: F401

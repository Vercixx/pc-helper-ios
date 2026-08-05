"""Signed LAN service for Wake-on-LAN and logind session unlock.

Protocol v1 is specified in ``docs/PROTOCOL.md`` at the repository root. Every
wire format in this package mirrors that document; the test vectors in
``tests/test_canonical.py`` are copied from it verbatim.
"""

__version__ = "1.0.0"

API_VERSION = 1
PROTOCOL_VERSION = 1

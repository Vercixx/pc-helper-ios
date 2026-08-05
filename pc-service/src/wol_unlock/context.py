"""The assembled service: the object every layer reads its collaborators from."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .config import Config
from .identity import ServerIdentity
from .pairing import PairingManager
from .ratelimit import RateLimiter
from .store import Store


@dataclass(slots=True)
class ServiceContext:
    config: Config
    identity: ServerIdentity
    store: Store
    pairing: PairingManager
    rate_limiter: RateLimiter
    started_at: float = field(default_factory=time.monotonic)
    discovery: Any = None

    @property
    def uptime_s(self) -> int:
        return int(time.monotonic() - self.started_at)

    def server_info(self) -> dict[str, Any]:
        """The public description of this server.

        Deliberately identical to what the mDNS TXT record already broadcasts, so
        the unauthenticated ``/v1/server-info`` endpoint discloses nothing that is
        not already on the wire for anyone listening to multicast.
        """
        return {
            "v": 1,
            "api": 1,
            "name": self.config.name,
            "fp": self.identity.fingerprint,
            "caps": list(self.config.capabilities),
            "pair": self.pairing.is_open,
        }

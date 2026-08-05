"""``wol-unlock`` -- the service entry point."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

from . import __version__, config as config_mod
from .errors import ConfigError
from .service import Service


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wol-unlock",
        description="Signed LAN service for Wake-on-LAN and logind session unlock.",
    )
    parser.add_argument("--version", action="version", version=f"wol-unlock {__version__}")
    parser.add_argument("-c", "--config", type=Path, default=None, help="path to config.toml")
    parser.add_argument(
        "--write-default-config",
        action="store_true",
        help="write a commented config reflecting this machine's interfaces, then exit",
    )
    parser.add_argument("--force", action="store_true", help="overwrite an existing config")
    parser.add_argument(
        "--check", action="store_true", help="validate the configuration and exit"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="logging verbosity",
    )
    return parser


def setup_logging(level: str) -> None:
    # stderr only: under systemd this lands in the journal with correct
    # timestamps, so adding our own would just duplicate them.
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(levelname)-7s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    logging.getLogger("zeroconf").setLevel(logging.WARNING)


async def _run(config: config_mod.Config) -> int:
    service = Service(config)
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, service.request_stop)
        except (NotImplementedError, RuntimeError):
            # Not available on every platform/loop; Ctrl-C still raises
            # KeyboardInterrupt, which main() handles.
            pass

    try:
        await service.start()
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("wol_unlock").error("failed to start: %s", exc)
        logging.getLogger("wol_unlock").debug("startup traceback", exc_info=True)
        await service.stop()
        return 1

    try:
        await service.wait_closed()
    finally:
        await service.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.log_level)
    log = logging.getLogger("wol_unlock")

    if args.write_default_config:
        try:
            path = config_mod.write_default_config(args.config, overwrite=args.force)
        except ConfigError as exc:
            log.error("%s", exc)
            return 1
        print(f"Wrote {path}")
        return 0

    try:
        config = config_mod.load(args.config)
    except ConfigError as exc:
        log.error("configuration error: %s", exc)
        return 2

    if args.check:
        print(f"Configuration OK ({config.source_path or 'built-in defaults'})")
        print(f"  name            {config.name}")
        print(f"  listen          {config.http.bind}:{config.http.port}")
        print(f"  allowed         {', '.join(str(n) for n in config.http.allowed_networks)}")
        print(f"  capabilities    {', '.join(config.capabilities)}")
        print(f"  wake targets    {len(config.wake_targets)}")
        for target in config.wake_targets:
            print(f"    - {target.mac} via {target.broadcast}:{target.port} ({target.iface})")
        print(f"  state dir       {config.state_dir}")
        print(f"  control socket  {config_mod.control_socket_path()}")
        return 0

    try:
        return asyncio.run(_run(config))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())

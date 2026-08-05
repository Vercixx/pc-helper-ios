"""Message catalogues for everything a human reads on the PC.

Scope, deliberately drawn:

* The ``wol-unlockctl`` terminal UI is translated. It is the only part of this
  service a person reads directly.
* ``ApiError.message`` is **not**. Those strings go over the wire, where the
  normative thing is the ``code`` (PROTOCOL.md 4.1) -- the iOS app renders its
  own wording from the code and ignores the message, so translating them would
  change only log lines, at the cost of making logs harder to match against the
  spec. The codes stay English on purpose.

No gettext: a ``.mo`` file is a build artifact to keep in sync and a runtime
dependency on the system's locale data, for two languages and a few dozen
strings. A dict is inspectable, diffable, and testable.

The language comes from the environment (``LANG`` and friends), or from
``WOL_UNLOCK_LANG`` to override it for one invocation.
"""

from __future__ import annotations

import os

EN: dict[str, str] = {
    # Relative times and booleans.
    "never": "never",
    "future": "in the future",
    "ago.d": "{n}d ago",
    "ago.h": "{n}h ago",
    "ago.m": "{n}m ago",
    "ago.s": "{n}s ago",
    "yes": "yes",
    "no": "no",
    # Pairing panel.
    "pair.title": "Pairing mode",
    "pair.scan": "Scan the code, or type it into the app.  ",
    "pair.expires": "Expires in {n}s",
    "pair.willApprove": "You will be asked to approve the device here.",
    "pair.fingerprint": "server fingerprint  {fp}…",
    # Devices table.
    "devices.title": "Trusted devices",
    "devices.name": "Device",
    "devices.id": "ID",
    "devices.fp": "Fingerprint",
    "devices.platform": "Platform",
    "devices.paired": "Paired",
    "devices.lastSeen": "Last seen",
    "devices.state": "State",
    "devices.revoked": "revoked",
    "devices.active": "active",
    # Status panel.
    "status.name": "name",
    "status.fingerprint": "fingerprint",
    "status.api": "api",
    "status.uptime": "uptime",
    "status.listening": "listening",
    "status.allowed": "allowed",
    "status.devices": "devices",
    "status.capabilities": "capabilities",
    "status.unlock": "unlock",
    "status.config": "config",
    "status.session": "session",
    "status.pairing": "pairing",
    "status.enabled": "enabled",
    "status.disabled": "disabled",
    "status.locked": "locked",
    "status.unlocked": "unlocked",
    "status.noSession": "none found",
    "status.pairingOpen": "{state} ({n}s left)",
    "status.pairingClosed": "closed",
    # Wake targets table.
    "wake.title": "Wake targets",
    "wake.mac": "MAC",
    "wake.iface": "Interface",
    "wake.broadcast": "Broadcast",
    "wake.link": "Link",
    # Audit table.
    "audit.title": "Recent activity",
    "audit.when": "When",
    "audit.action": "Action",
    "audit.result": "Result",
    "audit.device": "Device",
    "audit.from": "From",
    "audit.detail": "Detail",
    # Discovery table.
    "discover.title": "Discovered services (_wol-unlock._tcp)",
    "discover.name": "Name",
    "discover.host": "Host",
    "discover.addresses": "Addresses",
    "discover.fp": "Fingerprint",
    "discover.caps": "Caps",
    "discover.pairing": "Pairing",
    "discover.open": "open",
    "discover.closed": "closed",
    # wol-unlockctl.
    "cli.description": "Manage the wol-unlock service running for this user.",
    "cli.socket": "path to the control socket",
    "cli.cmd.status": "show service, session and wake status",
    "cli.cmd.pair": "open a pairing window and show the code/QR",
    "cli.cmd.devices": "list trusted devices",
    "cli.cmd.revoke": "revoke a device by id, name or fingerprint prefix",
    "cli.cmd.remove": "delete a device record entirely",
    "cli.cmd.audit": "show recent activity",
    "cli.cmd.discover": "browse the LAN for advertised services",
    "cli.opt.window": "window length in seconds",
    "cli.opt.noQr": "print only the code",
    "cli.opt.lightTerminal": "invert the QR for terminals with a light background",
    "cli.opt.yes": "approve the first device automatically (for scripted setup)",
    "cli.noDevices": "No devices are paired. Run",
    "cli.revoked": "Revoked",
    "cli.alreadyRevoked": "{name} was already revoked",
    "cli.deleted": "Deleted",
    "cli.noActivity": "No activity recorded yet.",
    "cli.cancelHint": "Press Ctrl-C to cancel.",
    "cli.windowClosed": "Pairing window closed.",
    "cli.windowClosedReason": "Pairing window closed: {reason}",
    "cli.paired": "Paired",
    "cli.pairedHint": "It can now wake and unlock this PC.",
    "cli.cancelled": "Cancelled.",
    "cli.request.title": "Device requesting access",
    "cli.request.name": "name",
    "cli.request.platform": "platform",
    "cli.request.id": "device id",
    "cli.request.fp": "fingerprint",
    "cli.autoApprove": "--yes given; approving.",
    "cli.approvePrompt": "Approve this device? [y/N] ",
    "cli.approveYes": "y",
    "cli.denied": "Denied.",
    "cli.browsing": "Browsing _wol-unlock._tcp for {timeout:g}s…",
    "cli.noServices": "No services found.",
    "cli.noServicesHint": "If the service is running here, check that udp/5353 is allowed.",
    # Control-socket failures raised on this side of the connection.
    "control.notRunning": (
        "cannot reach the service at {path}. Is it running?\n"
        "  systemctl --user status wol-unlock"
    ),
    "control.lost": "the service closed the connection",
    "control.closed": "control connection is closed",
    "control.timeout": "{command} timed out after {timeout:g}s",
    # wol-unlock (the service entry point).
    "svc.description": "Signed LAN service for Wake-on-LAN and logind session unlock.",
    "svc.opt.config": "path to config.toml",
    "svc.opt.writeDefault": (
        "write a commented config reflecting this machine's interfaces, then exit"
    ),
    "svc.opt.force": "overwrite an existing config",
    "svc.opt.check": "validate the configuration and exit",
    "svc.opt.logLevel": "logging verbosity",
    "svc.wrote": "Wrote {path}",
    "svc.configOk": "Configuration OK ({source})",
    "svc.defaults": "built-in defaults",
    "svc.name": "name",
    "svc.listen": "listen",
    "svc.allowed": "allowed",
    "svc.capabilities": "capabilities",
    "svc.wakeTargets": "wake targets",
    "svc.stateDir": "state dir",
    "svc.controlSocket": "control socket",
}

RU: dict[str, str] = {
    "never": "никогда",
    "future": "в будущем",
    "ago.d": "{n} д назад",
    "ago.h": "{n} ч назад",
    "ago.m": "{n} мин назад",
    "ago.s": "{n} с назад",
    "yes": "да",
    "no": "нет",
    "pair.title": "Режим сопряжения",
    "pair.scan": "Отсканируйте код или введите его в приложении.  ",
    "pair.expires": "Истекает через {n} с",
    "pair.willApprove": "Здесь потребуется подтвердить устройство.",
    "pair.fingerprint": "отпечаток сервера  {fp}…",
    "devices.title": "Доверенные устройства",
    "devices.name": "Устройство",
    "devices.id": "ID",
    "devices.fp": "Отпечаток",
    "devices.platform": "Платформа",
    "devices.paired": "Сопряжено",
    "devices.lastSeen": "Последняя связь",
    "devices.state": "Состояние",
    "devices.revoked": "отозвано",
    "devices.active": "активно",
    "status.name": "имя",
    "status.fingerprint": "отпечаток",
    "status.api": "api",
    "status.uptime": "аптайм",
    "status.listening": "слушает",
    "status.allowed": "разрешено",
    "status.devices": "устройства",
    "status.capabilities": "возможности",
    "status.unlock": "разблокировка",
    "status.config": "конфиг",
    "status.session": "сеанс",
    "status.pairing": "сопряжение",
    "status.enabled": "включена",
    "status.disabled": "выключена",
    "status.locked": "заблокирован",
    "status.unlocked": "разблокирован",
    "status.noSession": "не найден",
    "status.pairingOpen": "{state} (осталось {n} с)",
    "status.pairingClosed": "закрыто",
    "wake.title": "Цели пробуждения",
    "wake.mac": "MAC",
    "wake.iface": "Интерфейс",
    "wake.broadcast": "Широковещание",
    "wake.link": "Линк",
    "audit.title": "Недавняя активность",
    "audit.when": "Когда",
    "audit.action": "Действие",
    "audit.result": "Результат",
    "audit.device": "Устройство",
    "audit.from": "Откуда",
    "audit.detail": "Подробности",
    "discover.title": "Найденные службы (_wol-unlock._tcp)",
    "discover.name": "Имя",
    "discover.host": "Хост",
    "discover.addresses": "Адреса",
    "discover.fp": "Отпечаток",
    "discover.caps": "Возможности",
    "discover.pairing": "Сопряжение",
    "discover.open": "открыто",
    "discover.closed": "закрыто",
    "cli.description": "Управление службой wol-unlock, запущенной для этого пользователя.",
    "cli.socket": "путь к управляющему сокету",
    "cli.cmd.status": "показать состояние службы, сеанса и пробуждения",
    "cli.cmd.pair": "открыть окно сопряжения и показать код/QR",
    "cli.cmd.devices": "список доверенных устройств",
    "cli.cmd.revoke": "отозвать устройство по id, имени или началу отпечатка",
    "cli.cmd.remove": "полностью удалить запись об устройстве",
    "cli.cmd.audit": "показать недавнюю активность",
    "cli.cmd.discover": "искать объявленные службы в локальной сети",
    "cli.opt.window": "длительность окна в секундах",
    "cli.opt.noQr": "печатать только код",
    "cli.opt.lightTerminal": "инвертировать QR для терминалов со светлым фоном",
    "cli.opt.yes": "автоматически подтвердить первое устройство (для скриптов)",
    "cli.noDevices": "Нет сопряжённых устройств. Выполните",
    "cli.revoked": "Отозвано",
    "cli.alreadyRevoked": "{name} уже было отозвано",
    "cli.deleted": "Удалено",
    "cli.noActivity": "Активность пока не записана.",
    "cli.cancelHint": "Нажмите Ctrl-C для отмены.",
    "cli.windowClosed": "Окно сопряжения закрыто.",
    "cli.windowClosedReason": "Окно сопряжения закрыто: {reason}",
    "cli.paired": "Сопряжено",
    "cli.pairedHint": "Теперь оно может будить и разблокировать этот ПК.",
    "cli.cancelled": "Отменено.",
    "cli.request.title": "Устройство запрашивает доступ",
    "cli.request.name": "имя",
    "cli.request.platform": "платформа",
    "cli.request.id": "id устройства",
    "cli.request.fp": "отпечаток",
    "cli.autoApprove": "передан --yes; подтверждаю.",
    "cli.approvePrompt": "Подтвердить это устройство? [д/Н] ",
    "cli.approveYes": "д",
    "cli.denied": "Отклонено.",
    "cli.browsing": "Поиск _wol-unlock._tcp в течение {timeout:g} с…",
    "cli.noServices": "Службы не найдены.",
    "cli.noServicesHint": "Если служба запущена здесь, проверьте, что udp/5353 разрешён.",
    "control.notRunning": (
        "не удаётся связаться со службой по адресу {path}. Она запущена?\n"
        "  systemctl --user status wol-unlock"
    ),
    "control.lost": "служба закрыла соединение",
    "control.closed": "управляющее соединение закрыто",
    "control.timeout": "{command} не ответил за {timeout:g} с",
    "svc.description": (
        "Подписанная служба локальной сети для Wake-on-LAN и разблокировки сеанса logind."
    ),
    "svc.opt.config": "путь к config.toml",
    "svc.opt.writeDefault": (
        "записать конфиг с комментариями, отражающий интерфейсы этой машины, и выйти"
    ),
    "svc.opt.force": "перезаписать существующий конфиг",
    "svc.opt.check": "проверить конфигурацию и выйти",
    "svc.opt.logLevel": "подробность журнала",
    "svc.wrote": "Записано {path}",
    "svc.configOk": "Конфигурация в порядке ({source})",
    "svc.defaults": "встроенные значения по умолчанию",
    "svc.name": "имя",
    "svc.listen": "слушает",
    "svc.allowed": "разрешено",
    "svc.capabilities": "возможности",
    "svc.wakeTargets": "цели пробуждения",
    "svc.stateDir": "каталог состояния",
    "svc.controlSocket": "управляющий сокет",
}

CATALOGS: dict[str, dict[str, str]] = {"en": EN, "ru": RU}

DEFAULT_LOCALE = "en"

#: Checked in order; the first that names a language with a catalogue wins.
_ENV_VARS = ("WOL_UNLOCK_LANG", "LC_ALL", "LC_MESSAGES", "LANG")


def detect_locale(environ: dict[str, str] | None = None) -> str:
    """The language to use, from the environment.

    Accepts anything POSIX-shaped -- ``ru``, ``ru_RU``, ``ru_RU.UTF-8`` -- and
    falls back to English for ``C``, ``POSIX``, an unset environment, or a
    language with no catalogue.
    """
    env = os.environ if environ is None else environ
    for var in _ENV_VARS:
        raw = env.get(var)
        if not raw:
            continue
        code = raw.split(".")[0].split("_")[0].split("-")[0].lower()
        if code in CATALOGS:
            return code
        if code in ("c", "posix"):
            return DEFAULT_LOCALE
    return DEFAULT_LOCALE


_locale: str | None = None


def locale() -> str:
    """The active language, detected once on first use."""
    global _locale
    if _locale is None:
        _locale = detect_locale()
    return _locale


def set_locale(code: str | None) -> None:
    """Pin the language, or pass ``None`` to re-detect. For tests and ``--lang``."""
    global _locale
    _locale = code


def _(key: str, **params: object) -> str:
    """Translate ``key``, substituting ``{placeholder}`` spans from ``params``.

    Falls back to English, and then to the key itself, so a missing translation
    degrades to something readable rather than raising in the middle of output.
    """
    template = CATALOGS.get(locale(), EN).get(key) or EN.get(key) or key
    return template.format(**params) if params else template

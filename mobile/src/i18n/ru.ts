/**
 * Russian.
 *
 * Typed as `Catalog`, so a key missing here — or a plural written as a plain
 * string — fails the typecheck rather than silently falling back to English at
 * runtime.
 */

import type { Catalog } from "./en";

export const ru: Catalog = {
  "nav.myPCs": "Мои ПК",
  "nav.addPC": "Добавить ПК",
  "nav.pair": "Сопряжение",
  "nav.pairWithPC": "Сопряжение с ПК",
  "nav.confirmPairing": "Подтверждение сопряжения",
  "nav.scan": "Сканировать QR-код",
  "nav.camera": "Камера",
  "nav.settings": "Настройки",

  "common.cancel": "Отмена",
  "common.none": "нет",

  "list.empty.title": "Пока нет ПК",
  "list.empty.body":
    "Выполните на своём ПК с Linux {cmd}, затем нажмите ＋ и отсканируйте показанный код.",
  "list.a11y.addPC": "Добавить ПК",
  "list.a11y.rowHint": "Открывает подробности. Долгое нажатие — разбудить и разблокировать.",
  "list.a11y.settings": "Настройки",

  "status.waking": "Пробуждение…",
  "status.unlocking": "Разблокировка…",
  "status.locking": "Блокировка…",
  "status.checking": "Проверка…",
  "status.asleep": "Спит или недоступен",
  "status.noUser": "В сети — никто не вошёл",
  "status.lockedHint": "Заблокирован — долгое нажатие, чтобы разблокировать",
  "status.unlockedHint": "Разблокирован — долгое нажатие, чтобы заблокировать",
  "status.locked": "Заблокирован",
  "status.unlocked": "Разблокирован",

  "action.wake": "Разбудить",
  "action.unlock": "Разблокировать сеанс",
  "action.lock": "Заблокировать сеанс",
  "action.refresh": "Обновить",
  "action.details": "Подробности",

  "detail.gone": "Этот ПК больше не сопряжён.",
  "detail.session": "Сеанс {id}",
  "detail.address": "Адрес",
  "detail.lastIp": "Последний IP",
  "detail.capabilities": "Возможности",
  "detail.wakeTargets": "Цели пробуждения",
  "detail.noTargets": "не настроены",
  "detail.unlockConfirmation": "Подтверждение разблокировки",
  "detail.confirmNone": "Нет",
  "detail.confirmBiometric": "Face ID / код-пароль",
  "detail.deviceId": "ID этого устройства",
  "detail.fingerprint": "Отпечаток ПК",
  "detail.pairedAt": "Сопряжён",
  "detail.widgetStorage": "Хранилище виджета",
  "detail.unpair": "Разорвать сопряжение",
  "detail.unpair.title": "Разорвать сопряжение с {name}?",
  "detail.unpair.body":
    "Ключ этого телефона будет удалён. ПК сохранит свою запись, пока вы не отзовёте её там командой «wol-unlockctl revoke».",
  "detail.unpair.confirm": "Разорвать",

  "widget.ok": "работает",
  "widget.notWritable": "запись недоступна",
  "widget.noGroup": "в подписанном профиле нет App Group",
  "widget.grants": "профиль выдаёт: {keys}",
  "widget.unreadable": "профиль есть, но не читается",
  "widget.noProfile": "профиль подготовки отсутствует",

  "discover.scan.title": "Сканировать QR-код",
  "discover.scan.body": "Самый быстрый способ. Выполните {cmd} на ПК.",
  "discover.manual.title": "Ввести данные вручную",
  "discover.manual.body": "Если ПК в другой подсети или обнаружение заблокировано.",
  "discover.section": "В ЭТОЙ СЕТИ",
  "discover.unavailable.title": "Обнаружение недоступно",
  "discover.unavailable.body":
    "Для просмотра сети через Bonjour нужна сборка для разработки. Используйте QR-код.",
  "discover.failed": "Не удалось просмотреть сеть",
  "discover.looking": "Поиск ПК…",
  "discover.paired": "Сопряжён",
  "discover.pairingOpen": "Сопряжение открыто",
  "discover.a11y.alreadyPaired": "{name}, уже сопряжён",
  "discover.footnote":
    "Найденные имена и отпечатки — только подсказки. При сопряжении личность ПК проверяется по коду, который вы вводите.",

  "pair.code.label": "КОД СОПРЯЖЕНИЯ",
  "pair.code.hint": "Показывается командой {cmd} на ПК. Действует две минуты.",
  "pair.code.a11y": "Код сопряжения",
  "pair.address.label": "АДРЕС ПК",
  "pair.host.a11y": "Имя хоста ПК",
  "pair.port.a11y": "Порт",
  "pair.port.range": "Порт должен быть от 1 до 65535.",
  "pair.identity.label": "ЛИЧНОСТЬ ПК",
  "pair.identity.scanned": "Из QR-кода. Сопряжение прервётся, если ПК предъявит что-то другое.",
  "pair.identity.manual": "Проверьте, что он совпадает с отпечатком на экране ПК.",
  "pair.waiting.title": "Ожидание подтверждения",
  "pair.waiting.body": "Подтвердите это устройство на ПК. Сравните показанный отпечаток.",
  "pair.with": "Сопряжение с «{name}».",
  "pair.contacting": "Соединение с ПК…",
  "pair.waiting": "Ожидание…",
  "pair.submit": "Сопрячь",

  "scan.notATicket": "Это не код сопряжения PC Unlock.",
  "scan.permission.title": "Нужен доступ к камере",
  "scan.permission.body": "Код сопряжения показывается на экране ПК в виде QR-кода.",
  "scan.permission.allow": "Разрешить камеру",
  "scan.hint": "Наведите на QR-код, показанный командой wol-unlockctl pair",

  "wake.failed": "Не удалось отправить magic-пакет.",
  "wake.sent": {
    one: "Отправлен {count} magic-пакет. Ожидание {name}…",
    few: "Отправлено {count} magic-пакета. Ожидание {name}…",
    many: "Отправлено {count} magic-пакетов. Ожидание {name}…",
  },
  "wake.sent.broadcastBlocked":
    " (iOS заблокировал широковещание; использован последний известный IP.)",
  "wake.awake": "{name} проснулся.",
  "wake.noResponse":
    "{name} не вышел в сеть. Пакет отправлен — проверьте, включён ли Wake-on-LAN в BIOS и в настройках сетевой карты.",
  "wake.noResponse.unicast":
    "{name} не вышел в сеть. Удалось отправить только одноадресный пакет, а для него роутер должен всё ещё хранить ARP-запись для {ip}. Резервирование DHCP вместе со статической ARP-записью делает это надёжным.",
  "wake.itsIp": "его IP",
  "wake.needsDevBuild":
    "Для Wake-on-LAN нужна сборка для разработки — Expo Go не может открыть UDP-сокет.",
  "wake.noMacs": "Этот ПК не сообщил ни одного MAC-адреса для пробуждения.",
  "wake.noUnicastKnown":
    "iOS заблокировал широковещание, а одноадресный адрес этого ПК пока неизвестен. Откройте его один раз, пока он включён, чтобы запомнился IP, и попробуйте снова.",
  "wake.nothingSent": "не удалось отправить ни одного magic-пакета",

  "unlock.prompt": "Разблокировать {name}",
  "unlock.cancelled": "Отменено.",
  "unlock.done": "Сеанс {id} разблокирован.",
  "unlock.alreadyUnlocked": "{name} уже был разблокирован.",

  "lock.done": "Сеанс {id} заблокирован.",
  "lock.alreadyLocked": "{name} уже был заблокирован.",

  "error.unreachable": "Не удаётся связаться с этим ПК. Он включён и в той же сети Wi-Fi?",
  "error.device_revoked": "Доступ этого телефона отозван. Выполните сопряжение заново.",
  "error.unknown_device": "Этот ПК не узнаёт этот телефон. Выполните сопряжение заново.",
  "error.timestamp_out_of_window": "Часы телефона расходятся с часами ПК.",
  "error.no_session": "На этом ПК никто не вошёл, поэтому блокировать или разблокировать нечего.",
  "error.rate_limited": "Слишком много запросов. Подождите немного и попробуйте снова.",
  "error.forbidden_network": "ПК отклонил эту сеть. Подключитесь к той же локальной сети.",
  "error.bad_signature": "Ответ не подписан этим ПК. Возможно, кто-то выдаёт себя за него.",
  "error.invalid_code": "Неверный код сопряжения.",
  "error.pairing_closed":
    "Окно сопряжения закрылось. Выполните «wol-unlockctl pair» на ПК ещё раз.",
  "error.pairing_denied": "ПК отклонил это устройство.",
  "error.pairing_timeout": "Никто не подтвердил это устройство на ПК.",

  "settings.language": "ЯЗЫК",
  "settings.language.system": "Системный",
  "settings.language.note":
    "Быстрые команды, виджет и системные запросы разрешений всегда следуют языку системы: iOS определяет их до запуска приложения.",
};

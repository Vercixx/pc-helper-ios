//
//  WUAppIntents.swift
//  Shortcuts, Siri, the Action Button, and Control Center.
//
//  These live in the *app* target, not an extension. That is the whole point:
//  App Intents need no entitlement, no App Group and no separate App ID, so they
//  work on a free Apple account where a widget extension may not. iOS launches
//  the app in the background to run them.
//
//  Reachable from Shortcuts:
//
//    Wake PC        -- a magic packet. Unauthenticated UDP by nature, so it is
//                      safe to put on the Lock Screen or in Control Center.
//    PC status      -- signed and verified; returns "Locked" / "Unlocked".
//    Unlock PC      -- signed and verified, and gated behind device
//                      authentication (see `authenticationPolicy` below).
//
//  Every user-visible string is keyed rather than written inline, and the
//  English wording travels with it as `defaultValue`. Translations live in
//  `mobile/locales/<lang>.json` under `ios["Localizable.strings"]`; Siri
//  phrases are separate, in `mobile/locales/ios/<lang>.lproj/AppShortcuts.strings`.
//
//  These follow the *system* language, not the in-app override: iOS resolves an
//  intent's title for Shortcuts and Spotlight without running the app.
//

import AppIntents
import Foundation

// MARK: - The thing intents act on

struct PCEntity: AppEntity {
  let id: String
  let name: String

  static var typeDisplayRepresentation = TypeDisplayRepresentation(
    name: LocalizedStringResource("entity.pc", defaultValue: "PC")
  )
  static var defaultQuery = PCQuery()

  var displayRepresentation: DisplayRepresentation {
    DisplayRepresentation(title: "\(name)")
  }

  init(id: String, name: String) {
    self.id = id
    self.name = name
  }

  init(_ pc: SharedState.PC) {
    self.init(id: pc.id, name: pc.name)
  }
}

struct PCQuery: EntityQuery {
  func entities(for identifiers: [String]) async throws -> [PCEntity] {
    SharedState.allPCs().filter { identifiers.contains($0.id) }.map(PCEntity.init)
  }

  func suggestedEntities() async throws -> [PCEntity] {
    SharedState.allPCs().map(PCEntity.init)
  }

  func defaultResult() async -> PCEntity? {
    SharedState.allPCs().first.map(PCEntity.init)
  }
}

enum IntentFailure: Error, CustomLocalizedStringResourceConvertible {
  case notPaired
  case cannotUnlock
  case wakeFailed(String)

  var localizedStringResource: LocalizedStringResource {
    switch self {
    case .notPaired:
      return LocalizedStringResource(
        "intent.error.notPaired",
        defaultValue: "No PC is paired. Open PC Unlock and pair one first."
      )
    case .cannotUnlock:
      return LocalizedStringResource(
        "intent.error.cannotUnlock",
        defaultValue: "That PC doesn't offer unlocking."
      )
    case .wakeFailed(let reason):
      return LocalizedStringResource(
        "intent.error.wakeFailed",
        defaultValue: "Couldn't send the wake packet: \(reason)"
      )
    }
  }
}

private func resolve(_ entity: PCEntity?) throws -> SharedState.PC {
  guard let pc = SharedState.pc(id: entity?.id) else { throw IntentFailure.notPaired }
  return pc
}

// MARK: - Wake

struct WakePCIntent: AppIntent {
  static var title = LocalizedStringResource("intent.wake.title", defaultValue: "Wake PC")
  static var description = IntentDescription(
    LocalizedStringResource(
      "intent.wake.description",
      defaultValue: "Sends a Wake-on-LAN magic packet to a paired PC."
    )
  )
  /// No reason to bounce the user into the app for a fire-and-forget UDP packet.
  static var openAppWhenRun: Bool = false

  @Parameter(title: LocalizedStringResource("entity.pc", defaultValue: "PC"))
  var target: PCEntity?

  init() {}
  init(target: PCEntity?) { self.target = target }

  func perform() async throws -> some IntentResult & ProvidesDialog & ReturnsValue<String> {
    let pc = try resolve(target)
    let outcome = MagicPacket.wake(pc: pc)

    guard outcome.packetsSent > 0 else {
      throw IntentFailure.wakeFailed(
        outcome.error
          ?? String(localized: "intent.wake.nothingSent", defaultValue: "no packet could be sent")
      )
    }

    let message = outcome.broadcastBlocked
      ? String(
          localized: "intent.wake.sentUnicast",
          defaultValue: "Sent a wake packet to \(pc.name) (unicast only — iOS blocked broadcast)."
        )
      : String(
          localized: "intent.wake.sent",
          defaultValue: "Sent a wake packet to \(pc.name)."
        )
    return .result(value: message, dialog: IntentDialog(stringLiteral: message))
  }
}

// MARK: - Status

struct PCStatusIntent: AppIntent {
  static var title = LocalizedStringResource("intent.status.title", defaultValue: "Get PC status")
  static var description = IntentDescription(
    LocalizedStringResource(
      "intent.status.description",
      defaultValue: "Asks a paired PC whether it is awake and whether its session is locked."
    )
  )
  static var openAppWhenRun: Bool = false

  @Parameter(title: LocalizedStringResource("entity.pc", defaultValue: "PC"))
  var target: PCEntity?

  init() {}
  init(target: PCEntity?) { self.target = target }

  func perform() async throws -> some IntentResult & ProvidesDialog & ReturnsValue<String> {
    let pc = try resolve(target)

    let message: String
    do {
      let status = try await WUClient.status(pc: pc)
      switch status.locked {
      case .some(true):
        message = String(localized: "intent.status.locked", defaultValue: "\(pc.name) is locked.")
      case .some(false):
        message = String(
          localized: "intent.status.unlocked",
          defaultValue: "\(pc.name) is unlocked."
        )
      case nil:
        message = String(
          localized: "intent.status.noUser",
          defaultValue: "\(pc.name) is awake, but nobody is logged in."
        )
      }
    } catch {
      message = String(
        localized: "intent.failure",
        defaultValue: "\(pc.name): \(error.localizedDescription)"
      )
    }
    return .result(value: message, dialog: IntentDialog(stringLiteral: message))
  }
}

// MARK: - Unlock

struct UnlockPCIntent: AppIntent {
  static var title = LocalizedStringResource(
    "intent.unlock.title",
    defaultValue: "Unlock PC session"
  )
  static var description = IntentDescription(
    LocalizedStringResource(
      "intent.unlock.description",
      defaultValue:
        "Unlocks the desktop session on a paired PC. Requires unlocking this device first."
    )
  )
  static var openAppWhenRun: Bool = false

  /// The security decision in this file.
  ///
  /// Shortcuts can be run from the Lock Screen, Control Center and the Action
  /// Button, none of which require the phone to be unlocked. Without this, a
  /// shortcut sitting in Control Center would be a one-tap way into a desktop
  /// session for whoever is holding the phone -- exactly what the Face ID gate
  /// in the app exists to prevent.
  static var authenticationPolicy: IntentAuthenticationPolicy = .requiresAuthentication

  @Parameter(title: LocalizedStringResource("entity.pc", defaultValue: "PC"))
  var target: PCEntity?

  init() {}
  init(target: PCEntity?) { self.target = target }

  func perform() async throws -> some IntentResult & ProvidesDialog & ReturnsValue<String> {
    let pc = try resolve(target)
    guard pc.canUnlock else { throw IntentFailure.cannotUnlock }

    let message: String
    do {
      let outcome = try await WUClient.unlock(pc: pc)
      message = outcome.wasLocked
        ? String(localized: "intent.unlock.done", defaultValue: "Unlocked \(pc.name).")
        : String(
            localized: "intent.unlock.alreadyUnlocked",
            defaultValue: "\(pc.name) was already unlocked."
          )
    } catch {
      message = String(
        localized: "intent.failure",
        defaultValue: "\(pc.name): \(error.localizedDescription)"
      )
    }
    return .result(value: message, dialog: IntentDialog(stringLiteral: message))
  }
}

// MARK: - Siri phrases

/// Phrases are localized through `AppShortcuts.strings`, keyed by the English
/// phrase verbatim, `${applicationName}` token and all. They cannot use
/// `LocalizedStringResource`: Siri needs every language's phrasing at once, not
/// whichever one the device happens to be set to.
struct PCUnlockShortcuts: AppShortcutsProvider {
  static var appShortcuts: [AppShortcut] {
    AppShortcut(
      intent: WakePCIntent(),
      phrases: [
        "Wake my PC with \(.applicationName)",
        "Wake my computer with \(.applicationName)",
      ],
      shortTitle: LocalizedStringResource("shortcut.wake", defaultValue: "Wake PC"),
      systemImageName: "power"
    )
    AppShortcut(
      intent: PCStatusIntent(),
      phrases: [
        "Check my PC with \(.applicationName)",
        "Is my PC awake in \(.applicationName)",
      ],
      shortTitle: LocalizedStringResource("shortcut.status", defaultValue: "PC status"),
      systemImageName: "desktopcomputer"
    )
    AppShortcut(
      intent: UnlockPCIntent(),
      phrases: [
        "Unlock my PC with \(.applicationName)",
      ],
      shortTitle: LocalizedStringResource("shortcut.unlock", defaultValue: "Unlock PC"),
      systemImageName: "lock.open"
    )
  }
}

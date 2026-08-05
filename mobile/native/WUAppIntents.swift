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

import AppIntents
import Foundation

// MARK: - The thing intents act on

struct PCEntity: AppEntity {
  let id: String
  let name: String

  static var typeDisplayRepresentation: TypeDisplayRepresentation = "PC"
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
      return "No PC is paired. Open PC Unlock and pair one first."
    case .cannotUnlock:
      return "That PC doesn't offer unlocking."
    case .wakeFailed(let reason):
      return "Couldn't send the wake packet: \(reason)"
    }
  }
}

private func resolve(_ entity: PCEntity?) throws -> SharedState.PC {
  guard let pc = SharedState.pc(id: entity?.id) else { throw IntentFailure.notPaired }
  return pc
}

// MARK: - Wake

struct WakePCIntent: AppIntent {
  static var title: LocalizedStringResource = "Wake PC"
  static var description = IntentDescription(
    "Sends a Wake-on-LAN magic packet to a paired PC."
  )
  /// No reason to bounce the user into the app for a fire-and-forget UDP packet.
  static var openAppWhenRun: Bool = false

  @Parameter(title: "PC")
  var target: PCEntity?

  init() {}
  init(target: PCEntity?) { self.target = target }

  func perform() async throws -> some IntentResult & ProvidesDialog & ReturnsValue<String> {
    let pc = try resolve(target)
    let outcome = MagicPacket.wake(pc: pc)

    guard outcome.packetsSent > 0 else {
      throw IntentFailure.wakeFailed(outcome.error ?? "no packet could be sent")
    }

    let message = outcome.broadcastBlocked
      ? "Sent a wake packet to \(pc.name) (unicast only — iOS blocked broadcast)."
      : "Sent a wake packet to \(pc.name)."
    return .result(value: message, dialog: IntentDialog(stringLiteral: message))
  }
}

// MARK: - Status

struct PCStatusIntent: AppIntent {
  static var title: LocalizedStringResource = "Get PC status"
  static var description = IntentDescription(
    "Asks a paired PC whether it is awake and whether its session is locked."
  )
  static var openAppWhenRun: Bool = false

  @Parameter(title: "PC")
  var target: PCEntity?

  init() {}
  init(target: PCEntity?) { self.target = target }

  func perform() async throws -> some IntentResult & ProvidesDialog & ReturnsValue<String> {
    let pc = try resolve(target)

    let message: String
    do {
      let status = try await WUClient.status(pc: pc)
      switch status.locked {
      case .some(true): message = "\(pc.name) is locked."
      case .some(false): message = "\(pc.name) is unlocked."
      case nil: message = "\(pc.name) is awake, but nobody is logged in."
      }
    } catch {
      message = "\(pc.name): \(error.localizedDescription)"
    }
    return .result(value: message, dialog: IntentDialog(stringLiteral: message))
  }
}

// MARK: - Unlock

struct UnlockPCIntent: AppIntent {
  static var title: LocalizedStringResource = "Unlock PC session"
  static var description = IntentDescription(
    "Unlocks the desktop session on a paired PC. Requires unlocking this device first."
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

  @Parameter(title: "PC")
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
        ? "Unlocked \(pc.name)."
        : "\(pc.name) was already unlocked."
    } catch {
      message = "\(pc.name): \(error.localizedDescription)"
    }
    return .result(value: message, dialog: IntentDialog(stringLiteral: message))
  }
}

// MARK: - Siri phrases

struct PCUnlockShortcuts: AppShortcutsProvider {
  static var appShortcuts: [AppShortcut] {
    AppShortcut(
      intent: WakePCIntent(),
      phrases: [
        "Wake my PC with \(.applicationName)",
        "Wake my computer with \(.applicationName)",
      ],
      shortTitle: "Wake PC",
      systemImageName: "power"
    )
    AppShortcut(
      intent: PCStatusIntent(),
      phrases: [
        "Check my PC with \(.applicationName)",
        "Is my PC awake in \(.applicationName)",
      ],
      shortTitle: "PC status",
      systemImageName: "desktopcomputer"
    )
    AppShortcut(
      intent: UnlockPCIntent(),
      phrases: [
        "Unlock my PC with \(.applicationName)",
      ],
      shortTitle: "Unlock PC",
      systemImageName: "lock.open"
    )
  }
}

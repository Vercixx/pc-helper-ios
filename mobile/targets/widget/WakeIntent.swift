//
//  WakeIntent.swift
//  The one action a widget can perform.
//
//  Wake only. A magic packet is unauthenticated UDP that anyone on the LAN can
//  already send, so exposing it on the Lock Screen gives away nothing that was
//  protected. Unlocking is a different matter -- it stays in the app behind Face
//  ID, because Control Center and Lock Screen buttons are reachable without
//  unlocking the phone at all.
//

import AppIntents
import WidgetKit

struct WakePCIntent: AppIntent {
  static var title = LocalizedStringResource("intent.wake.title", defaultValue: "Wake PC")
  static var description = IntentDescription(
    LocalizedStringResource(
      "intent.wake.description",
      defaultValue: "Sends a Wake-on-LAN magic packet to your paired PC."
    )
  )
  /// Runs in the background: no reason to bounce the user into the app for a
  /// fire-and-forget UDP packet.
  static var openAppWhenRun: Bool = false

  @Parameter(title: LocalizedStringResource("entity.pc", defaultValue: "PC"))
  var pcId: String?

  init() {}

  init(pcId: String?) {
    self.pcId = pcId
  }

  @MainActor
  func perform() async throws -> some IntentResult {
    guard let pc = pcId.flatMap(SharedState.pc(id:)) ?? SharedState.primaryPC() else {
      throw WakeIntentError.notPaired
    }

    let result = MagicPacket.wake(pc: pc)
    guard result.packetsSent > 0 else {
      throw WakeIntentError.sendFailed(
        result.error
          ?? String(localized: "intent.wake.nothingSent", defaultValue: "no packet could be sent")
      )
    }

    // Nudge the timeline so the widget starts showing "Waking…" rather than a
    // stale "Asleep" until its next scheduled refresh.
    WidgetCenter.shared.reloadAllTimelines()
    return .result()
  }
}

enum WakeIntentError: Error, CustomLocalizedStringResourceConvertible {
  case notPaired
  case sendFailed(String)

  var localizedStringResource: LocalizedStringResource {
    switch self {
    case .notPaired:
      return LocalizedStringResource(
        "intent.error.notPaired",
        defaultValue: "No PC is paired yet. Open PC Unlock and pair one first."
      )
    case .sendFailed(let reason):
      return LocalizedStringResource(
        "intent.error.wakeFailed",
        defaultValue: "Couldn't send the wake packet: \(reason)"
      )
    }
  }
}

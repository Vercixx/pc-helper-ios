//
//  WakeControl.swift
//  Control Center / Lock Screen / Action Button entry point.
//
//  Wake only, by design. These surfaces are reachable without unlocking the
//  phone, so anything placed here is effectively unauthenticated -- fine for a
//  magic packet, which anyone on the LAN can already send, and not fine for
//  unlocking a desktop session.
//

import AppIntents
import SwiftUI
import WidgetKit

@available(iOS 18.0, *)
struct WakeControl: ControlWidget {
  static let kind = "com.vercixx.wolunlock.wake"

  var body: some ControlWidgetConfiguration {
    StaticControlConfiguration(kind: Self.kind) {
      ControlWidgetButton(action: WakePCIntent()) {
        Label("Wake PC", systemImage: "power")
      }
    }
    .displayName("Wake PC")
    .description("Send a Wake-on-LAN packet to your paired PC.")
  }
}

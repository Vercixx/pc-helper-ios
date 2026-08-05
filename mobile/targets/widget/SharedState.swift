//
//  SharedState.swift
//  What the app publishes into the App Group for the extension to read.
//
//  Nothing secret goes through here. The Ed25519 seed stays in the keychain
//  (see DeviceKey.swift); this container holds only what the app already keeps
//  in unencrypted AsyncStorage -- addresses, public identities, and the last
//  known lock state.
//
//  The JSON shape is written by `mobile/src/state/widgetBridge.ts`. The two must
//  agree; `v` guards against a stale extension reading a newer payload.
//

import Foundation

enum SharedState {
  static let appGroup = "group.com.vercixx.wolunlock"
  static let stateKey = "wolunlock.state"
  static let currentVersion = 1

  struct Endpoint {
    let host: String
    let port: Int
  }

  struct Snapshot: Codable {
    let reachable: Bool
    let locked: Bool?
    /// Unix seconds.
    let checkedAt: Double
  }

  struct PC: Codable, Identifiable {
    let id: String
    let name: String
    let hostname: String
    let port: Int
    let lastIp: String?
    let deviceId: String
    let keyAlias: String
    let serverFp: String
    let serverPubKey: String
    let macs: [String]
    let broadcast: String
    let wakePort: Int
    let canUnlock: Bool
    let status: Snapshot?

    /// Addresses to try, best first.
    ///
    /// The last address that worked leads, because resolving a `.local` name
    /// costs an mDNS round trip that a widget refresh can ill afford -- and a
    /// widget gets a few seconds of wall clock at most.
    var endpoints: [Endpoint] {
      var out: [Endpoint] = []
      if let lastIp, !lastIp.isEmpty { out.append(Endpoint(host: lastIp, port: port)) }
      if !hostname.isEmpty, hostname != lastIp {
        out.append(Endpoint(host: hostname, port: port))
      }
      return out
    }
  }

  struct Payload: Codable {
    let v: Int
    let pcs: [PC]
    let updatedAt: Double
  }

  /// Read the published state, or nil when the app has never run, the App Group
  /// entitlement is missing, or the payload is from a newer app than this
  /// extension understands.
  static func load() -> Payload? {
    guard let defaults = UserDefaults(suiteName: appGroup),
          let raw = defaults.string(forKey: stateKey),
          let data = raw.data(using: .utf8),
          let payload = try? JSONDecoder().decode(Payload.self, from: data),
          payload.v == currentVersion
    else { return nil }
    return payload
  }

  /// The PC a widget acts on.
  ///
  /// Single-PC selection for now. Choosing between several needs an
  /// `AppIntentConfiguration` so the user can pick one per widget instance.
  static func primaryPC() -> PC? {
    load()?.pcs.first
  }

  static func pc(id: String) -> PC? {
    guard let pcs = load()?.pcs else { return nil }
    return pcs.first { $0.id == id } ?? pcs.first
  }
}

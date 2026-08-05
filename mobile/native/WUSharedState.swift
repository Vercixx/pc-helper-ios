//
//  WUSharedState.swift
//  What the JS side publishes for native code to read.
//
//  Two sources, in order:
//
//    1. A JSON file in the app's own Documents directory. This always works --
//       same process, same container, no entitlement involved. It is what the
//       App Intents actually run on.
//    2. App Group UserDefaults, if the entitlement happens to be live. Only the
//       widget extension needs this, and on a free-account sideload it usually
//       is not there.
//
//  Written by `src/state/widgetBridge.ts`; the shapes must agree.
//
//  Nothing secret is here. Every field is already in AsyncStorage unencrypted --
//  addresses, public identities, last known lock state. The Ed25519 seed stays
//  in the keychain and is reached separately, by alias (WUDeviceKey.swift).
//

import Foundation

enum SharedState {
  static let appGroup = "group.com.vercixx.wolunlock"
  static let stateKey = "wolunlock.state"
  /// Relative to the app's Documents directory. Matches `STATE_FILE` in
  /// `src/state/widgetBridge.ts`.
  static let stateFileName = "wolunlock-state.json"
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

    /// Addresses to try, best first: the one that worked last leads, because
    /// resolving a `.local` name costs an mDNS round trip.
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

  private static func decode(_ data: Data) -> Payload? {
    guard let payload = try? JSONDecoder().decode(Payload.self, from: data),
          payload.v == currentVersion
    else { return nil }
    return payload
  }

  private static var stateFileURL: URL? {
    FileManager.default
      .urls(for: .documentDirectory, in: .userDomainMask)
      .first?
      .appendingPathComponent(stateFileName)
  }

  /// The published state, or nil when the app has never written it.
  static func load() -> Payload? {
    if let url = stateFileURL,
       let data = try? Data(contentsOf: url),
       let payload = decode(data) {
      return payload
    }
    if let defaults = UserDefaults(suiteName: appGroup),
       let raw = defaults.string(forKey: stateKey),
       let data = raw.data(using: .utf8),
       let payload = decode(data) {
      return payload
    }
    return nil
  }

  static func allPCs() -> [PC] {
    load()?.pcs ?? []
  }

  /// The PC an action should act on: the one named, or the only one there is.
  static func pc(id: String?) -> PC? {
    let pcs = allPCs()
    guard let id else { return pcs.first }
    return pcs.first { $0.id == id } ?? pcs.first
  }
}

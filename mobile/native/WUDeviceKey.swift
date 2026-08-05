//
//  DeviceKey.swift
//  Reading the app's Ed25519 seed from the shared keychain.
//
//  The app writes the seed through `expo-secure-store`, which stores a generic
//  password whose attributes are decided by that library, not by us. The query
//  below reproduces them exactly:
//
//    kSecAttrService  "app:no-auth"   -- `keychainService ?? "app"` plus a
//                                       suffix for whether the item is behind
//                                       biometrics. Ours is not; the biometric
//                                       gate sits on the unlock action instead.
//    kSecAttrAccount  UTF-8 of the key, i.e. "wolunlock.seed.<alias>"
//    kSecAttrGeneric  the same bytes again
//
//  If expo-secure-store ever changes those, this read returns nil and the widget
//  falls back to cached status -- it does not crash or silently show something
//  wrong.
//
//  Availability: the seed is stored `WhenUnlockedThisDeviceOnly`, so this fails
//  while the phone is locked. That is deliberate and is why nothing on the Lock
//  Screen depends on it.
//

import Foundation

enum DeviceKey {
  /// Matches `optionsFor()` in `mobile/src/crypto/keys.ts`.
  private static let service = "app:no-auth"
  private static let keyPrefix = "wolunlock.seed."

  enum Failure: Error, LocalizedError {
    case notFound
    case unreadable(OSStatus)
    case malformed

    var errorDescription: String? {
      switch self {
      case .notFound: return "no key for this PC"
      case .unreadable(let status): return "keychain error \(status)"
      case .malformed: return "stored key is not a 32-byte seed"
      }
    }
  }

  /// The 32-byte Ed25519 seed for a paired PC.
  ///
  /// Tries the shared App Group access group first, then the app's private
  /// default. The fallback matters: if the App Group entitlement is stripped at
  /// signing time the app keeps working with a private item, and this read
  /// simply fails rather than the app breaking.
  static func seed(alias: String) throws -> Data {
    let account = Data((keyPrefix + alias).utf8)

    for group in [SharedState.appGroup, nil] as [String?] {
      var query: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: service,
        kSecAttrGeneric as String: account,
        kSecAttrAccount as String: account,
        kSecMatchLimit as String: kSecMatchLimitOne,
        kSecReturnData as String: true,
      ]
      if let group { query[kSecAttrAccessGroup as String] = group }

      var item: CFTypeRef?
      let status = SecItemCopyMatching(query as CFDictionary, &item)

      switch status {
      case errSecSuccess:
        guard let data = item as? Data,
              let encoded = String(data: data, encoding: .utf8),
              let seed = try? Base64URL.decode(encoded, expect: WUProtocol.seedBytes)
        else { throw Failure.malformed }
        return seed
      case errSecItemNotFound:
        continue
      default:
        // Missing-entitlement shows up as errSecMissingEntitlement (-34018);
        // keep going so the private-group attempt still gets a turn.
        continue
      }
    }

    throw Failure.notFound
  }
}

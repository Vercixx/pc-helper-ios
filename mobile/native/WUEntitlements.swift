//
//  WUEntitlements.swift
//  Finding out what this build was *actually* signed with.
//
//  The identifiers compiled into an app are not necessarily the ones it runs
//  under. Sideloading tools re-sign with their own team and rewrite bundle
//  identifiers to keep them unique -- SideStore appends the team ID, turning
//  `com.vercixx.wolunlock` into `com.vercixx.wolunlock.QMNZ42…` and the widget
//  into `….widget`. App Groups are rewritten to match, because a group can only
//  be registered under a team that owns it.
//
//  A hardcoded `group.com.vercixx.wolunlock` therefore names a container that
//  does not exist: `UserDefaults(suiteName:)` returns nil, the keychain access
//  group is refused, and the extension sees nothing. Which is exactly what
//  happened.
//
//  There is no public API on iOS to read your own entitlements
//  (`SecTaskCopyValueForEntitlement` is macOS-only), but every signed bundle
//  carries `embedded.mobileprovision`: a CMS blob with an XML plist inside it.
//  Scanning for the plist and reading its `Entitlements` dictionary is the
//  standard way to answer this, and it works in the app and in an extension
//  alike -- each is signed with its own profile.
//

import Foundation

enum Entitlements {
  /// What the source was written against, used when there is no profile to read
  /// -- a simulator build, or a build signed with the real team ID.
  static let fallbackAppGroup = "group.com.vercixx.wolunlock"

  /// App Groups this bundle is actually entitled to, in profile order.
  static func appGroups(in bundle: Bundle = .main) -> [String] {
    guard let entitlements = provisioningEntitlements(in: bundle),
          let groups = entitlements["com.apple.security.application-groups"] as? [String],
          !groups.isEmpty
    else {
      return []
    }
    return groups
  }

  /// The group to use for shared storage.
  ///
  /// Prefers one that looks like ours, so a tool that adds its own group (as
  /// AltStore-family installers do for their own bookkeeping) does not win the
  /// pick.
  static func sharedAppGroup(in bundle: Bundle = .main) -> String {
    let groups = appGroups(in: bundle)
    if let mine = groups.first(where: { $0.contains("wolunlock") }) {
      return mine
    }
    return groups.first ?? fallbackAppGroup
  }

  /// Whether a shared container for `group` actually exists for this process.
  ///
  /// The obvious test -- `UserDefaults(suiteName:)` returning non-nil -- is not
  /// one. That initialiser returns nil only for the main bundle identifier or a
  /// global domain; for a group this process is not entitled to, and for "", it
  /// hands back a live object whose writes cfprefsd quietly discards. Asking the
  /// file system for the container is the check that can actually fail.
  static func hasContainer(_ group: String) -> Bool {
    guard !group.isEmpty else { return false }
    return FileManager.default
      .containerURL(forSecurityApplicationGroupIdentifier: group) != nil
  }

  /// Keychain access groups, which are subject to the same rewriting.
  static func keychainAccessGroups(in bundle: Bundle = .main) -> [String] {
    guard let entitlements = provisioningEntitlements(in: bundle),
          let groups = entitlements["keychain-access-groups"] as? [String]
    else {
      return []
    }
    return groups
  }

  // MARK: - Reading embedded.mobileprovision

  private static func provisioningEntitlements(in bundle: Bundle) -> [String: Any]? {
    guard let url = bundle.url(forResource: "embedded", withExtension: "mobileprovision"),
          let data = try? Data(contentsOf: url),
          let plist = extractPlist(from: data),
          let profile = try? PropertyListSerialization.propertyList(
            from: plist, options: [], format: nil
          ) as? [String: Any]
    else { return nil }
    return profile["Entitlements"] as? [String: Any]
  }

  /// Carve the XML plist out of the CMS envelope.
  ///
  /// Located by its markers rather than by parsing PKCS#7: the signature is not
  /// being verified here -- iOS already did that, or the bundle would not be
  /// running -- only read.
  private static func extractPlist(from data: Data) -> Data? {
    guard let start = data.range(of: Data("<?xml".utf8)),
          let end = data.range(
            of: Data("</plist>".utf8),
            options: .backwards,
            in: start.lowerBound..<data.endIndex
          )
    else { return nil }
    return data.subdata(in: start.lowerBound..<end.upperBound)
  }
}

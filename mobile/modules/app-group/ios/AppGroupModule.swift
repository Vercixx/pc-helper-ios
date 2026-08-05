import ExpoModulesCore
import Foundation
import WidgetKit

// Bridges the App Group this build was *actually* signed with to JavaScript.
//
// The identifiers compiled into an app are not necessarily the ones it runs
// under. Sideloading tools re-sign with their own team and rewrite bundle
// identifiers to keep them unique -- SideStore appends the team ID, turning
// `com.vercixx.wolunlock` into `com.vercixx.wolunlock.QMNZ42…`. App Groups are
// rewritten to match, since a group can only be registered under a team that
// owns it. A hardcoded `group.com.vercixx.wolunlock` then names a container
// that does not exist.
//
// NOTE: `ProvisioningEntitlements` below is deliberately duplicated from
// `native/WUEntitlements.swift`. This file compiles into a CocoaPods static
// library and that one into the app target, and the app target's App Intents
// need the same answer; a pod cannot see app-target symbols. The widget
// extension carries a third copy for the same reason. Any change here belongs
// in all of them.

/// Reads `Entitlements` out of the bundle's `embedded.mobileprovision`.
///
/// There is no public API on iOS to read your own entitlements
/// (`SecTaskCopyValueForEntitlement` is macOS-only), but every signed bundle
/// carries its profile, and the profile is a CMS blob with an XML plist inside.
enum ProvisioningEntitlements {
  static let fallbackAppGroup = "group.com.vercixx.wolunlock"

  static func appGroups(in bundle: Bundle = .main) -> [String] {
    guard let entitlements = read(in: bundle),
          let groups = entitlements["com.apple.security.application-groups"] as? [String]
    else { return [] }
    return groups
  }

  /// Prefers a group that looks like ours, so a tool that adds its own group
  /// for bookkeeping does not win the pick.
  ///
  /// Returns "" rather than the compile-time fallback when nothing was granted:
  /// callers need "there is no container" to be distinguishable from "here is a
  /// container", and handing back an identifier this build does not hold makes
  /// every write fail in a way that looks like a different bug.
  static func sharedAppGroup(in bundle: Bundle = .main) -> String {
    let groups = appGroups(in: bundle)
    return groups.first { $0.contains("wolunlock") } ?? groups.first ?? ""
  }

  /// Which entitlements the profile actually carries.
  ///
  /// The one question the previous diagnostic could not answer: an empty group
  /// list means either that the profile was stripped of app groups or that it
  /// was never read. Keys present means it was read.
  static func entitlementKeys(in bundle: Bundle = .main) -> [String] {
    guard let entitlements = read(in: bundle) else { return [] }
    return entitlements.keys.sorted()
  }

  static func hasProfile(in bundle: Bundle = .main) -> Bool {
    bundle.url(forResource: "embedded", withExtension: "mobileprovision") != nil
  }

  static func read(in bundle: Bundle) -> [String: Any]? {
    guard let url = bundle.url(forResource: "embedded", withExtension: "mobileprovision"),
          let data = try? Data(contentsOf: url),
          let plist = extractPlist(from: data),
          let profile = try? PropertyListSerialization.propertyList(
            from: plist, options: [], format: nil
          ) as? [String: Any]
    else { return nil }
    return profile["Entitlements"] as? [String: Any]
  }

  /// Carve the XML plist out of the CMS envelope, by markers rather than by
  /// parsing PKCS#7. The signature is not being verified here -- iOS already
  /// did that, or the bundle would not be running -- only read.
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

public final class AppGroupModule: Module {
  public func definition() -> ModuleDefinition {
    Name("AppGroup")

    // Empty means the entitlement did not survive signing. Worth surfacing
    // rather than hiding: it is the difference between "widgets are broken" and
    // "this build cannot have widgets".
    Function("appGroups") { () -> [String] in
      ProvisioningEntitlements.appGroups()
    }

    /// The identifier to use for shared storage, including as a keychain
    /// access group.
    Function("sharedAppGroup") { () -> String in
      ProvisioningEntitlements.sharedAppGroup()
    }

    Function("bundleIdentifier") { () -> String in
      Bundle.main.bundleIdentifier ?? ""
    }

    // Distinguishes "no groups in the profile" from "no profile read at all".
    Function("entitlementKeys") { () -> [String] in
      ProvisioningEntitlements.entitlementKeys()
    }

    Function("hasProvisioningProfile") { () -> Bool in
      ProvisioningEntitlements.hasProfile()
    }

    // Writing and reloading happen here, against one discovered identifier, so
    // there is no chance of the write and the reload disagreeing. Returns false
    // when there is no usable container, so JS can tell "published" from
    // "silently went nowhere".
    Function("publish") { (json: String) -> Bool in
      let group = ProvisioningEntitlements.sharedAppGroup()
      guard let defaults = UserDefaults(suiteName: group) else { return false }
      defaults.set(json, forKey: "wolunlock.state")
      WidgetCenter.shared.reloadAllTimelines()
      if #available(iOS 18.0, *) {
        ControlCenter.shared.reloadAllControls()
      }
      return true
    }
  }
}

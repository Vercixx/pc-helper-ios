import ExpoModulesCore
import Network
import Darwin

// Two capabilities that plain React Native cannot provide, and that the whole
// product depends on:
//
//   1. Bonjour browsing for _wol-unlock._tcp, so the app can find PCs.
//   2. A UDP broadcast socket for Wake-on-LAN.
//
// (2) has to live here rather than on the PC. When the PC is asleep its service
// is not running, so there is nobody to receive a "please wake up" request --
// the magic packet must originate on the phone. Network.framework does not
// expose SO_BROADCAST, so this uses a BSD socket directly.
//
// Both paths require the user to have granted Local Network permission, which
// iOS prompts for on first use.

private let defaultServiceType = "_wol-unlock._tcp"
private let defaultDomain = "local."

public final class LanDiscoveryModule: Module {
  private var browser: NWBrowser?
  private let queue = DispatchQueue(label: "dev.wolunlock.lanDiscovery")

  public func definition() -> ModuleDefinition {
    Name("LanDiscovery")

    Events("onServiceFound", "onServiceLost", "onBrowseStateChange")

    AsyncFunction("startBrowsing") { (serviceType: String?) in
      self.startBrowsing(serviceType: serviceType ?? defaultServiceType)
    }

    AsyncFunction("stopBrowsing") {
      self.stopBrowsing()
    }

    AsyncFunction("resolve") { (name: String, serviceType: String?, promise: Promise) in
      self.resolve(
        name: name,
        serviceType: serviceType ?? defaultServiceType,
        promise: promise
      )
    }

    AsyncFunction("getBroadcastAddresses") { () -> [[String: Any]] in
      Self.broadcastAddresses()
    }

    AsyncFunction("sendMagicPacket") {
      (mac: String, broadcast: String, port: Int, secureOn: String?) -> Int in
      try Self.sendMagicPacket(
        mac: mac,
        broadcast: broadcast,
        port: port,
        secureOn: secureOn
      )
    }

    OnDestroy {
      self.stopBrowsing()
    }
  }

  // MARK: - Browsing

  private func startBrowsing(serviceType: String) {
    stopBrowsing()

    let parameters = NWParameters()
    // Peer-to-peer would also search over AWDL/Wi-Fi Direct, which this service
    // never uses and which slows discovery down.
    parameters.includePeerToPeer = false

    let browser = NWBrowser(
      for: .bonjourWithTXTRecord(type: serviceType, domain: nil),
      using: parameters
    )

    browser.stateUpdateHandler = { [weak self] state in
      switch state {
      case .ready:
        self?.sendEvent("onBrowseStateChange", ["state": "ready"])
      case .failed(let error):
        self?.sendEvent("onBrowseStateChange", [
          "state": "failed",
          "error": error.localizedDescription
        ])
      case .cancelled:
        self?.sendEvent("onBrowseStateChange", ["state": "cancelled"])
      case .waiting(let error):
        // Usually means Local Network permission has not been granted yet.
        self?.sendEvent("onBrowseStateChange", [
          "state": "waiting",
          "error": error.localizedDescription
        ])
      default:
        break
      }
    }

    browser.browseResultsChangedHandler = { [weak self] _, changes in
      guard let self else { return }
      for change in changes {
        switch change {
        case .added(let result):
          if let payload = Self.describe(result) {
            self.sendEvent("onServiceFound", payload)
          }
        case .changed(_, let new, _):
          if let payload = Self.describe(new) {
            self.sendEvent("onServiceFound", payload)
          }
        case .removed(let result):
          if let name = Self.instanceName(of: result) {
            self.sendEvent("onServiceLost", ["name": name])
          }
        default:
          break
        }
      }
    }

    self.browser = browser
    browser.start(queue: queue)
  }

  private func stopBrowsing() {
    browser?.cancel()
    browser = nil
  }

  private static func instanceName(of result: NWBrowser.Result) -> String? {
    if case .service(let name, _, _, _) = result.endpoint {
      return name
    }
    return nil
  }

  /// Flatten a browse result into the shape the JS layer consumes.
  ///
  /// The TXT record carries everything the discovery list needs (display name,
  /// fingerprint, capabilities, whether a pairing window is open). Host and port
  /// come from the SRV record, which only `resolve` fetches -- there is no point
  /// paying for that until the user actually taps a row.
  private static func describe(_ result: NWBrowser.Result) -> [String: Any]? {
    guard case .service(let name, let type, let domain, _) = result.endpoint else {
      return nil
    }

    var txt: [String: String] = [:]
    if case .bonjour(let record) = result.metadata {
      for (key, value) in record.dictionary {
        txt[key] = value
      }
    }

    return [
      "name": name,
      "type": type,
      "domain": domain,
      "txt": txt,
      // The PC advertises its instance under its hostname, so this is the
      // address that keeps working across DHCP lease changes.
      "hostname": "\(name).local"
    ]
  }

  // MARK: - Resolution

  /// Resolve an instance name to a concrete host and port.
  ///
  /// NWBrowser deliberately does not resolve SRV records while browsing. The
  /// supported way to get an address is to open a connection to the service
  /// endpoint and read the resolved path once it is ready.
  private func resolve(name: String, serviceType: String, promise: Promise) {
    let endpoint = NWEndpoint.service(
      name: name,
      type: serviceType,
      domain: defaultDomain,
      interface: nil
    )

    let parameters = NWParameters.tcp
    parameters.includePeerToPeer = false
    let connection = NWConnection(to: endpoint, using: parameters)

    // Guarantees the promise settles exactly once no matter which handler fires.
    let settled = ManagedAtomicFlag()

    let finish: (Result<[String: Any], Error>) -> Void = { outcome in
      guard settled.testAndSet() else { return }
      connection.cancel()
      switch outcome {
      case .success(let value):
        promise.resolve(value)
      case .failure(let error):
        promise.reject("ERR_RESOLVE_FAILED", error.localizedDescription)
      }
    }

    connection.stateUpdateHandler = { state in
      switch state {
      case .ready:
        guard
          let remote = connection.currentPath?.remoteEndpoint,
          case .hostPort(let host, let port) = remote
        else {
          finish(.failure(LanDiscoveryError.unresolved))
          return
        }
        finish(.success([
          "name": name,
          "host": Self.describeHost(host),
          "hostname": "\(name).local",
          "port": Int(port.rawValue)
        ]))
      case .failed(let error):
        finish(.failure(error))
      case .cancelled:
        finish(.failure(LanDiscoveryError.unresolved))
      default:
        break
      }
    }

    queue.asyncAfter(deadline: .now() + 6) {
      finish(.failure(LanDiscoveryError.timedOut))
    }

    connection.start(queue: queue)
  }

  private static func describeHost(_ host: NWEndpoint.Host) -> String {
    switch host {
    case .name(let name, _):
      return name
    case .ipv4(let address):
      // "192.168.0.5%en0" -- strip the interface scope, it is not part of a URL.
      return String(describing: address).components(separatedBy: "%").first ?? ""
    case .ipv6(let address):
      return String(describing: address).components(separatedBy: "%").first ?? ""
    @unknown default:
      return String(describing: host)
    }
  }

  // MARK: - Interfaces

  /// Every up, non-loopback IPv4 interface that supports broadcast, with the
  /// subnet-directed broadcast address the magic packet should go to.
  private static func broadcastAddresses() -> [[String: Any]] {
    var results: [[String: Any]] = []
    var head: UnsafeMutablePointer<ifaddrs>?

    guard getifaddrs(&head) == 0, let first = head else { return results }
    defer { freeifaddrs(head) }

    for pointer in sequence(first: first, next: { $0.pointee.ifa_next }) {
      let interface = pointer.pointee
      guard let addr = interface.ifa_addr,
            addr.pointee.sa_family == UInt8(AF_INET) else { continue }

      let flags = Int32(interface.ifa_flags)
      guard flags & IFF_UP == IFF_UP,
            flags & IFF_LOOPBACK == 0,
            flags & IFF_BROADCAST == IFF_BROADCAST else { continue }

      let name = String(cString: interface.ifa_name)
      guard let address = Self.ipv4String(addr) else { continue }
      // For a broadcast interface the kernel stores the broadcast address in the
      // union that ifa_dstaddr points at.
      let broadcast = interface.ifa_dstaddr.flatMap { Self.ipv4String($0) }

      results.append([
        "name": name,
        "address": address,
        "broadcast": broadcast ?? "255.255.255.255",
        // en0 is Wi-Fi on every iOS device; surfacing it lets the UI prefer it.
        "isWiFi": name == "en0"
      ])
    }

    return results
  }

  private static func ipv4String(_ addr: UnsafeMutablePointer<sockaddr>) -> String? {
    var buffer = [CChar](repeating: 0, count: Int(INET_ADDRSTRLEN))
    var sin = UnsafeRawPointer(addr).assumingMemoryBound(to: sockaddr_in.self).pointee
    guard inet_ntop(AF_INET, &sin.sin_addr, &buffer, socklen_t(INET_ADDRSTRLEN)) != nil else {
      return nil
    }
    return String(cString: buffer)
  }

  // MARK: - Wake-on-LAN

  /// FF * 6 followed by the target MAC repeated 16 times (102 bytes), plus an
  /// optional 6-byte SecureOn password (108 bytes). See PROTOCOL.md section 7;
  /// the byte-for-byte vectors are in section 11.6.
  static func buildMagicPacket(mac: String, secureOn: String?) throws -> [UInt8] {
    let target = try parseMac(mac)
    var packet = [UInt8](repeating: 0xFF, count: 6)
    for _ in 0..<16 {
      packet.append(contentsOf: target)
    }
    if let secureOn, !secureOn.isEmpty {
      packet.append(contentsOf: try parseMac(secureOn))
    }
    return packet
  }

  /// Accepts "aa:bb:cc:dd:ee:ff", "aa-bb-...", or bare hex.
  private static func parseMac(_ value: String) throws -> [UInt8] {
    let cleaned = value
      .lowercased()
      .replacingOccurrences(of: ":", with: "")
      .replacingOccurrences(of: "-", with: "")
      .replacingOccurrences(of: ".", with: "")

    guard cleaned.count == 12 else { throw LanDiscoveryError.badMac(value) }

    var bytes: [UInt8] = []
    bytes.reserveCapacity(6)
    var index = cleaned.startIndex
    while index < cleaned.endIndex {
      let next = cleaned.index(index, offsetBy: 2)
      guard let byte = UInt8(cleaned[index..<next], radix: 16) else {
        throw LanDiscoveryError.badMac(value)
      }
      bytes.append(byte)
      index = next
    }
    return bytes
  }

  @discardableResult
  static func sendMagicPacket(
    mac: String,
    broadcast: String,
    port: Int,
    secureOn: String?
  ) throws -> Int {
    guard (1...65535).contains(port) else { throw LanDiscoveryError.badPort(port) }
    let packet = try buildMagicPacket(mac: mac, secureOn: secureOn)

    let fd = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP)
    guard fd >= 0 else { throw LanDiscoveryError.socketFailed(errno) }
    defer { close(fd) }

    // Without SO_BROADCAST the kernel refuses to send to a broadcast address.
    // Network.framework offers no way to set this, which is why this is a BSD
    // socket rather than an NWConnection.
    var enable: Int32 = 1
    guard setsockopt(
      fd, SOL_SOCKET, SO_BROADCAST, &enable, socklen_t(MemoryLayout<Int32>.size)
    ) == 0 else {
      throw LanDiscoveryError.socketFailed(errno)
    }

    var destination = sockaddr_in()
    destination.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
    destination.sin_family = sa_family_t(AF_INET)
    destination.sin_port = UInt16(port).bigEndian
    guard inet_pton(AF_INET, broadcast, &destination.sin_addr) == 1 else {
      throw LanDiscoveryError.badAddress(broadcast)
    }

    let sent = withUnsafePointer(to: &destination) { pointer in
      pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { sockaddrPointer in
        sendto(
          fd,
          packet,
          packet.count,
          0,
          sockaddrPointer,
          socklen_t(MemoryLayout<sockaddr_in>.size)
        )
      }
    }

    guard sent >= 0 else { throw LanDiscoveryError.sendFailed(errno) }
    return sent
  }
}

// MARK: - Support types

private enum LanDiscoveryError: Error, LocalizedError {
  case badMac(String)
  case badPort(Int)
  case badAddress(String)
  case socketFailed(Int32)
  case sendFailed(Int32)
  case unresolved
  case timedOut

  var errorDescription: String? {
    switch self {
    case .badMac(let value):
      return "'\(value)' is not a MAC address"
    case .badPort(let value):
      return "port \(value) is out of range"
    case .badAddress(let value):
      return "'\(value)' is not an IPv4 address"
    case .socketFailed(let code):
      return "could not open a broadcast socket (errno \(code))"
    case .sendFailed(let code):
      return "could not send the magic packet (errno \(code))"
    case .unresolved:
      return "the service did not resolve to an address"
    case .timedOut:
      return "timed out resolving the service"
    }
  }
}

/// Minimal thread-safe once-flag, so the resolve promise settles exactly once
/// even though several connection callbacks can race on the browse queue.
private final class ManagedAtomicFlag {
  private var value = false
  private let lock = NSLock()

  /// Returns true the first time it is called, false afterwards.
  func testAndSet() -> Bool {
    lock.lock()
    defer { lock.unlock() }
    if value { return false }
    value = true
    return true
  }
}

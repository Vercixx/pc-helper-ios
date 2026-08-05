//
//  MagicPacket.swift
//  Wake-on-LAN from the extension.
//
//  A port of the sender in `modules/lan-discovery/ios/LanDiscoveryModule.swift`.
//  Duplicated rather than shared because each target the config plugin generates
//  compiles on its own; the two are pinned by the same vectors in PROTOCOL.md
//  section 11.6.
//
//  Note what this does *not* need: no key, no pairing, no server. A magic packet
//  is unauthenticated by design, which is why wake is the only action safe to
//  expose on the Lock Screen and in Control Center.
//

import Darwin
import Foundation

enum MagicPacketError: Error, LocalizedError {
  case badMac(String)
  case badAddress(String)
  case socketFailed(Int32)
  case sendFailed(Int32)
  case nothingToSend

  var errorDescription: String? {
    switch self {
    case .badMac(let value): return "not a MAC address: \(value)"
    case .badAddress(let value): return "not an IPv4 address: \(value)"
    case .socketFailed(let code): return "socket error \(code)"
    case .sendFailed(let code):
      // EACCES is what iOS returns for a broadcast send without the multicast
      // entitlement, which needs a paid team and Apple's approval.
      return code == EACCES ? "iOS blocked the broadcast" : "send error \(code)"
    case .nothingToSend: return "no MAC address configured"
    }
  }
}

enum MagicPacket {
  /// 6 bytes of 0xFF followed by the target MAC repeated 16 times.
  static func build(mac: String) throws -> [UInt8] {
    let target = try parseMac(mac)
    var packet = [UInt8](repeating: 0xFF, count: 6)
    for _ in 0..<16 { packet.append(contentsOf: target) }
    return packet
  }

  /// Accepts "aa:bb:cc:dd:ee:ff", "aa-bb-…", or bare hex.
  private static func parseMac(_ value: String) throws -> [UInt8] {
    let cleaned = value.lowercased()
      .replacingOccurrences(of: ":", with: "")
      .replacingOccurrences(of: "-", with: "")
      .replacingOccurrences(of: ".", with: "")
    guard cleaned.count == 12 else { throw MagicPacketError.badMac(value) }

    var bytes: [UInt8] = []
    bytes.reserveCapacity(6)
    var index = cleaned.startIndex
    while index < cleaned.endIndex {
      let next = cleaned.index(index, offsetBy: 2)
      guard let byte = UInt8(cleaned[index..<next], radix: 16) else {
        throw MagicPacketError.badMac(value)
      }
      bytes.append(byte)
      index = next
    }
    return bytes
  }

  @discardableResult
  private static func send(packet: [UInt8], to address: String, port: Int) throws -> Int {
    let fd = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP)
    guard fd >= 0 else { throw MagicPacketError.socketFailed(errno) }
    defer { close(fd) }

    // Without SO_BROADCAST the kernel refuses a broadcast destination.
    // Network.framework offers no way to set this, hence the BSD socket.
    var enable: Int32 = 1
    guard setsockopt(fd, SOL_SOCKET, SO_BROADCAST, &enable, socklen_t(MemoryLayout<Int32>.size)) == 0
    else { throw MagicPacketError.socketFailed(errno) }

    var destination = sockaddr_in()
    destination.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
    destination.sin_family = sa_family_t(AF_INET)
    destination.sin_port = UInt16(port).bigEndian
    guard inet_pton(AF_INET, address, &destination.sin_addr) == 1 else {
      throw MagicPacketError.badAddress(address)
    }

    let sent = withUnsafePointer(to: &destination) { pointer in
      pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { addr in
        sendto(fd, packet, packet.count, 0, addr, socklen_t(MemoryLayout<sockaddr_in>.size))
      }
    }
    guard sent >= 0 else { throw MagicPacketError.sendFailed(errno) }
    return sent
  }

  struct WakeOutcome {
    let packetsSent: Int
    let broadcastBlocked: Bool
    let error: String?
  }

  /// Send to every configured MAC, unicast first.
  ///
  /// Unicast leads because iOS gates UDP broadcast behind the multicast
  /// entitlement. It only works while the router still holds an ARP entry for
  /// the sleeping PC, so the broadcast attempt still follows as a fallback.
  static func wake(pc: SharedState.PC) -> WakeOutcome {
    guard !pc.macs.isEmpty else {
      return WakeOutcome(packetsSent: 0, broadcastBlocked: false, error: MagicPacketError.nothingToSend.localizedDescription)
    }

    var destinations: [String] = []
    if let lastIp = pc.lastIp, !lastIp.isEmpty { destinations.append(lastIp) }
    if !pc.broadcast.isEmpty, !destinations.contains(pc.broadcast) {
      destinations.append(pc.broadcast)
    }

    var sent = 0
    var blocked = false
    var firstError: String?

    for mac in pc.macs {
      guard let packet = try? build(mac: mac) else { continue }
      for address in destinations {
        do {
          try send(packet: packet, to: address, port: pc.wakePort)
          sent += 1
        } catch let error as MagicPacketError {
          if case .sendFailed(let code) = error, code == EACCES { blocked = true }
          if firstError == nil { firstError = error.localizedDescription }
        } catch {
          if firstError == nil { firstError = error.localizedDescription }
        }
      }
    }

    return WakeOutcome(packetsSent: sent, broadcastBlocked: blocked, error: sent == 0 ? firstError : nil)
  }
}

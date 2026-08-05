//
//  Protocol.swift
//  Canonical byte strings and encodings for wol-unlock protocol v1.
//
//  This is a third implementation of the same normative spec, alongside
//  `pc-service/src/wol_unlock/crypto/canonical.py` and
//  `mobile/src/crypto/canonical.ts`. It is pinned by the vectors in
//  `docs/PROTOCOL.md` section 11 and asserted by `ProtocolTests.swift`.
//  Changing anything here is a protocol break.
//

import CryptoKit
import Foundation
import Security

enum WUProtocol {
  static let domainRequest = "wol-unlock/v1/request"
  static let domainResponse = "wol-unlock/v1/response"

  static let nonceBytes = 16
  static let signatureBytes = 64
  static let pubkeyBytes = 32
  static let seedBytes = 32
}

enum ProtocolError: Error, LocalizedError {
  case notBase64URL(String)
  case nonCanonicalBase64URL
  case wrongLength(expected: Int, got: Int)
  case newlineInField(String)

  var errorDescription: String? {
    switch self {
    case .notBase64URL(let text): return "not base64url: \(text.prefix(16))…"
    case .nonCanonicalBase64URL: return "non-canonical base64url"
    case .wrongLength(let expected, let got): return "expected \(expected) bytes, got \(got)"
    case .newlineInField(let name): return "canonical field '\(name)' contains a newline"
    }
  }
}

// MARK: - base64url

enum Base64URL {
  /// Encode without padding.
  static func encode(_ data: Data) -> String {
    data.base64EncodedString()
      .replacingOccurrences(of: "+", with: "-")
      .replacingOccurrences(of: "/", with: "_")
      .replacingOccurrences(of: "=", with: "")
  }

  /// Strict decode.
  ///
  /// Rejects padding, characters outside the alphabet, impossible lengths, and
  /// non-canonical encodings -- trailing bits a correct encoder would have
  /// zeroed. Leniency would let one key or signature be spelled several ways,
  /// which turns an identifier into a set rather than a value.
  static func decode(_ text: String, expect: Int? = nil) throws -> Data {
    guard !text.contains("="),
          text.allSatisfy({ $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "-" || $0 == "_") })
    else {
      throw ProtocolError.notBase64URL(text)
    }
    guard text.count % 4 != 1 else { throw ProtocolError.notBase64URL(text) }

    var padded = text
      .replacingOccurrences(of: "-", with: "+")
      .replacingOccurrences(of: "_", with: "/")
    padded += String(repeating: "=", count: (4 - padded.count % 4) % 4)

    guard let data = Data(base64Encoded: padded) else {
      throw ProtocolError.notBase64URL(text)
    }
    // Round-trip: catches trailing bits that a canonical encoder would zero.
    guard encode(data) == text else { throw ProtocolError.nonCanonicalBase64URL }

    if let expect, data.count != expect {
      throw ProtocolError.wrongLength(expected: expect, got: data.count)
    }
    return data
  }
}

// MARK: - Digests

enum Digest {
  /// b64u(SHA-256(bytes)) -- the body-hash form used in canonical strings.
  static func sha256B64u(_ data: Data) -> String {
    Base64URL.encode(Data(SHA256.hash(data: data)))
  }

  /// Public identity of a key: b64u(SHA-256(pubkey)), 43 characters.
  static func fingerprint(_ pubkey: Data) throws -> String {
    guard pubkey.count == WUProtocol.pubkeyBytes else {
      throw ProtocolError.wrongLength(expected: WUProtocol.pubkeyBytes, got: pubkey.count)
    }
    return Base64URL.encode(Data(SHA256.hash(data: pubkey)))
  }
}

// MARK: - Canonical strings

enum Canonical {
  private static func field(_ name: String, _ value: String) throws -> String {
    guard !value.contains("\n"), !value.contains("\r") else {
      throw ProtocolError.newlineInField(name)
    }
    return value
  }

  /// Bytes the device signs for an authenticated request (PROTOCOL.md 2.1).
  ///
  /// `serverFp` is part of the signature on purpose: it binds the request to
  /// one PC, so a captured request replayed against a different machine fails
  /// verification there.
  static func request(
    method: String,
    path: String,
    timestamp: Int,
    nonce: String,
    bodySHA256: String,
    deviceId: String,
    serverFp: String
  ) throws -> Data {
    let parts = [
      WUProtocol.domainRequest,
      try field("method", method.uppercased()),
      try field("path", path),
      try field("timestamp", String(timestamp)),
      try field("nonce", nonce),
      try field("bodySha256", bodySHA256),
      try field("deviceId", deviceId),
      try field("serverFp", serverFp),
    ]
    return Data((parts.joined(separator: "\n") + "\n").utf8)
  }

  /// Bytes the server signs for a response (PROTOCOL.md 2.2).
  static func response(
    status: Int,
    nonceEcho: String,
    bodySHA256: String,
    serverFp: String
  ) throws -> Data {
    let parts = [
      WUProtocol.domainResponse,
      try field("status", String(status)),
      try field("nonceEcho", nonceEcho),
      try field("bodySha256", bodySHA256),
      try field("serverFp", serverFp),
    ]
    return Data((parts.joined(separator: "\n") + "\n").utf8)
  }
}

// MARK: - Signing

enum Signer {
  /// Ed25519 over a 32-byte seed.
  ///
  /// CryptoKit's `rawRepresentation` for Curve25519 signing keys *is* the RFC
  /// 8032 seed, so this consumes exactly what the app stored and produces the
  /// same 64 bytes `@noble/ed25519` would.
  static func sign(message: Data, seed: Data) throws -> Data {
    let key = try Curve25519.Signing.PrivateKey(rawRepresentation: seed)
    return try key.signature(for: message)
  }

  static func verify(signature: Data, message: Data, publicKey: Data) -> Bool {
    guard signature.count == WUProtocol.signatureBytes,
          let key = try? Curve25519.Signing.PublicKey(rawRepresentation: publicKey)
    else { return false }
    return key.isValidSignature(signature, for: message)
  }

  static func randomNonce() -> String {
    var bytes = [UInt8](repeating: 0, count: WUProtocol.nonceBytes)
    // Fall back to the Swift RNG only if the system CSPRNG refuses, which does
    // not happen in practice; both are cryptographically secure.
    if SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) != errSecSuccess {
      bytes = (0..<WUProtocol.nonceBytes).map { _ in UInt8.random(in: 0...255) }
    }
    return Base64URL.encode(Data(bytes))
  }
}

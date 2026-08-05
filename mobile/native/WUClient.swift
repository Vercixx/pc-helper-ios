//
//  WUClient.swift
//  Signed, verified requests to a paired PC.
//
//  Both directions are authenticated, exactly as in `src/api/client.ts`: the
//  request is signed with this device's key, and the response signature is
//  verified against the server key pinned at pairing time *before* the body is
//  parsed. Skipping the second half would let anything on the LAN answer on the
//  PC's behalf -- and for `/v1/unlock`, claim success it never performed.
//

import Foundation

struct SessionStatus {
  let locked: Bool?
  let sessionId: String?
  let desktop: String?
}

struct UnlockOutcome {
  let sessionId: String?
  let wasLocked: Bool
  let desktop: String?
}

enum ClientError: Error, LocalizedError {
  case unreachable
  case unsignedResponse
  case badSignature
  case malformed
  case server(code: String, message: String)

  var errorDescription: String? {
    switch self {
    case .unreachable:
      return "Can't reach this PC. Is it awake and on the same Wi-Fi?"
    case .unsignedResponse, .badSignature:
      return "The reply wasn't signed by this PC. Someone may be impersonating it."
    case .malformed:
      return "The PC sent something unexpected."
    case .server(let code, let message):
      switch code {
      case "no_session":
        return "Nobody is logged in on that PC, so there's no session to unlock."
      case "device_revoked", "unknown_device":
        return "This phone's access was revoked. Pair with the PC again."
      case "timestamp_out_of_window":
        return "Your phone's clock is out of sync with the PC."
      default:
        return message
      }
    }
  }
}

enum WUClient {
  /// Short: an intent invoked from Shortcuts or Siri should not hang.
  private static let timeout: TimeInterval = 6

  static func status(pc: SharedState.PC) async throws -> SessionStatus {
    let envelope = try await call(pc: pc, method: "GET", path: "/v1/status", body: nil)
    let session = envelope.data?.session
    return SessionStatus(locked: session?.locked, sessionId: session?.id, desktop: session?.desktop)
  }

  static func unlock(pc: SharedState.PC) async throws -> UnlockOutcome {
    let body = Data(#"{"session_id":null}"#.utf8)
    let envelope = try await call(pc: pc, method: "POST", path: "/v1/unlock", body: body)
    return UnlockOutcome(
      sessionId: envelope.data?.session_id,
      wasLocked: envelope.data?.was_locked ?? false,
      desktop: envelope.data?.desktop
    )
  }

  // MARK: - Transport

  private static func call(
    pc: SharedState.PC,
    method: String,
    path: String,
    body: Data?
  ) async throws -> Envelope {
    let seed = try DeviceKey.seed(alias: pc.keyAlias)
    defer { /* CryptoKit copies the seed; nothing to zero here. */ }
    let serverPubKey = try Base64URL.decode(pc.serverPubKey, expect: WUProtocol.pubkeyBytes)

    var lastError: Error = ClientError.unreachable
    for endpoint in pc.endpoints {
      do {
        return try await send(
          pc: pc,
          endpoint: endpoint,
          method: method,
          path: path,
          body: body,
          seed: seed,
          serverPubKey: serverPubKey
        )
      } catch let error as ClientError {
        // A signature or protocol failure is conclusive: trying the PC's other
        // address will produce the same answer, and retrying a rejected unlock
        // is not something to do quietly.
        if case .unreachable = error {
          lastError = error
          continue
        }
        throw error
      } catch {
        lastError = error
      }
    }
    throw lastError
  }

  private static func send(
    pc: SharedState.PC,
    endpoint: SharedState.Endpoint,
    method: String,
    path: String,
    body: Data?,
    seed: Data,
    serverPubKey: Data
  ) async throws -> Envelope {
    let payload = body ?? Data()
    let nonce = Signer.randomNonce()
    let timestamp = Int(Date().timeIntervalSince1970)

    let message = try Canonical.request(
      method: method,
      path: path,
      timestamp: timestamp,
      nonce: nonce,
      bodySHA256: Digest.sha256B64u(payload),
      deviceId: pc.deviceId,
      serverFp: pc.serverFp
    )
    let signature = try Signer.sign(message: message, seed: seed)

    guard let url = URL(string: "http://\(endpoint.host):\(endpoint.port)\(path)") else {
      throw ClientError.unreachable
    }

    var request = URLRequest(url: url, timeoutInterval: timeout)
    request.httpMethod = method
    request.setValue("1", forHTTPHeaderField: "X-WU-Version")
    request.setValue(pc.deviceId, forHTTPHeaderField: "X-WU-Device")
    request.setValue(String(timestamp), forHTTPHeaderField: "X-WU-Timestamp")
    request.setValue(nonce, forHTTPHeaderField: "X-WU-Nonce")
    request.setValue(Base64URL.encode(signature), forHTTPHeaderField: "X-WU-Signature")
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    if body != nil { request.httpBody = payload }

    let configuration = URLSessionConfiguration.ephemeral
    configuration.timeoutIntervalForRequest = timeout
    configuration.waitsForConnectivity = false

    let data: Data
    let response: URLResponse
    do {
      (data, response) = try await URLSession(configuration: configuration).data(for: request)
    } catch {
      throw ClientError.unreachable
    }
    guard let http = response as? HTTPURLResponse else { throw ClientError.malformed }

    try verify(http: http, body: data, nonce: nonce, serverPubKey: serverPubKey)

    guard let envelope = try? JSONDecoder().decode(Envelope.self, from: data) else {
      throw ClientError.malformed
    }
    guard envelope.ok else {
      throw ClientError.server(
        code: envelope.error?.code ?? "internal_error",
        message: envelope.error?.message ?? "unknown error"
      )
    }
    return envelope
  }

  /// Verify `X-WU-Server-Signature` over the exact bytes received.
  ///
  /// The fingerprint in the canonical string is derived from the key pinned at
  /// pairing time, never read off the wire -- otherwise an impostor could assert
  /// its own identity and sign consistently with it.
  private static func verify(
    http: HTTPURLResponse,
    body: Data,
    nonce: String,
    serverPubKey: Data
  ) throws {
    guard let header = http.value(forHTTPHeaderField: "X-WU-Server-Signature") else {
      throw ClientError.unsignedResponse
    }
    guard let signature = try? Base64URL.decode(header, expect: WUProtocol.signatureBytes) else {
      throw ClientError.badSignature
    }

    let signed = try Canonical.response(
      status: http.statusCode,
      nonceEcho: nonce,
      bodySHA256: Digest.sha256B64u(body),
      serverFp: try Digest.fingerprint(serverPubKey)
    )

    guard Signer.verify(signature: signature, message: signed, publicKey: serverPubKey) else {
      throw ClientError.badSignature
    }
  }

  struct Envelope: Decodable {
    struct Session: Decodable {
      let id: String?
      let locked: Bool?
      let desktop: String?
    }
    struct Payload: Decodable {
      let session: Session?
      let session_id: String?
      let was_locked: Bool?
      let desktop: String?
    }
    struct Failure: Decodable {
      let code: String
      let message: String
    }
    let ok: Bool
    let data: Payload?
    let error: Failure?
  }
}

//
//  StatusClient.swift
//  A signed, verified GET /v1/status for the widget.
//
//  Deliberately read-only. The widget can ask a PC how it is; it cannot unlock
//  one. Unlocking stays in the app, behind Face ID, because a widget's buttons
//  are reachable from places the phone considers less private than the app is.
//
//  Both directions are authenticated, exactly as in `src/api/client.ts`:
//  the request is signed with this device's key, and the response signature is
//  verified against the server key pinned at pairing time *before* the body is
//  parsed. Skipping the second half would let anything on the LAN tell the
//  widget the PC is awake.
//

import Foundation

struct SessionStatus {
  let locked: Bool?
  let sessionId: String?
  let desktop: String?
}

enum StatusClientError: Error, LocalizedError {
  case unreachable
  case unsignedResponse
  case badSignature
  case malformed
  case server(code: String, message: String)

  var errorDescription: String? {
    switch self {
    case .unreachable: return "No answer"
    case .unsignedResponse: return "Unsigned reply"
    case .badSignature: return "Bad signature"
    case .malformed: return "Bad reply"
    case .server(_, let message): return message
    }
  }
}

enum StatusClient {
  /// A widget refresh has to finish fast; a sleeping PC should read as asleep
  /// rather than hold the timeline open.
  private static let timeout: TimeInterval = 4

  static func fetch(pc: SharedState.PC) async throws -> SessionStatus {
    let seed = try DeviceKey.seed(alias: pc.keyAlias)
    let serverPubKey = try Base64URL.decode(pc.serverPubKey, expect: WUProtocol.pubkeyBytes)

    var lastError: Error = StatusClientError.unreachable
    for endpoint in pc.endpoints {
      do {
        return try await request(
          pc: pc, endpoint: endpoint, seed: seed, serverPubKey: serverPubKey
        )
      } catch {
        lastError = error
      }
    }
    throw lastError
  }

  private static func request(
    pc: SharedState.PC,
    endpoint: SharedState.Endpoint,
    seed: Data,
    serverPubKey: Data
  ) async throws -> SessionStatus {
    let path = "/v1/status"
    let nonce = Signer.randomNonce()
    let timestamp = Int(Date().timeIntervalSince1970)
    let bodyHash = Digest.sha256B64u(Data())

    let message = try Canonical.request(
      method: "GET",
      path: path,
      timestamp: timestamp,
      nonce: nonce,
      bodySHA256: bodyHash,
      deviceId: pc.deviceId,
      serverFp: pc.serverFp
    )
    let signature = try Signer.sign(message: message, seed: seed)

    guard let url = URL(string: "http://\(endpoint.host):\(endpoint.port)\(path)") else {
      throw StatusClientError.unreachable
    }

    var request = URLRequest(url: url, timeoutInterval: timeout)
    request.httpMethod = "GET"
    request.setValue("1", forHTTPHeaderField: "X-WU-Version")
    request.setValue(pc.deviceId, forHTTPHeaderField: "X-WU-Device")
    request.setValue(String(timestamp), forHTTPHeaderField: "X-WU-Timestamp")
    request.setValue(nonce, forHTTPHeaderField: "X-WU-Nonce")
    request.setValue(Base64URL.encode(signature), forHTTPHeaderField: "X-WU-Signature")

    let configuration = URLSessionConfiguration.ephemeral
    configuration.timeoutIntervalForRequest = timeout
    configuration.waitsForConnectivity = false
    let session = URLSession(configuration: configuration)

    let (data, response): (Data, URLResponse)
    do {
      (data, response) = try await session.data(for: request)
    } catch {
      throw StatusClientError.unreachable
    }
    guard let http = response as? HTTPURLResponse else { throw StatusClientError.malformed }

    try verify(http: http, body: data, nonce: nonce, serverPubKey: serverPubKey)
    return try parse(body: data)
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
      throw StatusClientError.unsignedResponse
    }
    guard let signature = try? Base64URL.decode(header, expect: WUProtocol.signatureBytes) else {
      throw StatusClientError.badSignature
    }

    let signed = try Canonical.response(
      status: http.statusCode,
      nonceEcho: nonce,
      bodySHA256: Digest.sha256B64u(body),
      serverFp: try Digest.fingerprint(serverPubKey)
    )

    guard Signer.verify(signature: signature, message: signed, publicKey: serverPubKey) else {
      throw StatusClientError.badSignature
    }
  }

  private struct Envelope: Decodable {
    struct Session: Decodable {
      let id: String?
      let locked: Bool?
      let desktop: String?
    }
    struct Payload: Decodable {
      let session: Session?
    }
    struct Failure: Decodable {
      let code: String
      let message: String
    }
    let ok: Bool
    let data: Payload?
    let error: Failure?
  }

  private static func parse(body: Data) throws -> SessionStatus {
    guard let envelope = try? JSONDecoder().decode(Envelope.self, from: body) else {
      throw StatusClientError.malformed
    }
    guard envelope.ok else {
      let failure = envelope.error
      throw StatusClientError.server(
        code: failure?.code ?? "internal_error",
        message: failure?.message ?? "unknown error"
      )
    }
    let session = envelope.data?.session
    return SessionStatus(
      locked: session?.locked,
      sessionId: session?.id,
      desktop: session?.desktop
    )
  }
}

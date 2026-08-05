# wol-unlock protocol — v1

Normative specification. Both the Python service (`pc-service/`) and the iOS app
(`mobile/`) implement exactly this document. Every construction below has a test
vector in [§9](#9-test-vectors); an implementation that reproduces those bytes is
interoperable.

---

## 1. Conventions

| Item | Rule |
|---|---|
| Binary encoding | **base64url without padding** (RFC 4648 §5, `=` stripped). Written `b64u(x)` below. |
| Signature algorithm | Ed25519 (RFC 8032). Raw 32-byte public keys, raw 64-byte signatures. |
| Hash | SHA-256. |
| Timestamps | Unix seconds, decimal, no leading zeros. |
| Character set | Canonical strings are ASCII. Every interpolated field is drawn from a charset that excludes `\n`, so newline separation is unambiguous and no length prefixes are needed. |
| Transport | HTTP/1.1, cleartext, LAN only. TLS is **not** the trust anchor; signatures are. |

### 1.1 Derived identifiers

```
fp(pubkey)        = b64u(SHA-256(pubkey_raw_32))            43 chars
device_id(pubkey) = b64u(SHA-256(pubkey_raw_32)[0:16])      22 chars
```

`device_id` is always **derived by the server** from the enrolled public key. A
client never chooses its own id, so two devices cannot collide onto one record and
a client cannot claim another device's identity.

An Ed25519 private key is exactly 32 uniformly random bytes; both sides generate
keys by drawing 32 bytes from the platform CSPRNG and using them directly as the
seed.

---

## 2. Canonical strings

Three domain-separated constructions. The domain tag on line 1 makes it impossible
to take a signature produced for one purpose and present it as another.

### 2.1 Request

Signed by the **device** private key, sent in `X-WU-Signature`.

```
wol-unlock/v1/request\n
<METHOD>\n
<PATH>\n
<TIMESTAMP>\n
<NONCE>\n
<BODY_SHA256>\n
<DEVICE_ID>\n
<SERVER_FP>\n
```

| Field | Definition |
|---|---|
| `METHOD` | `GET` or `POST`, uppercase |
| `PATH` | request path, e.g. `/v1/unlock`. **No query string** — the server rejects any request carrying one, so there is no unsigned input channel |
| `TIMESTAMP` | unix seconds |
| `NONCE` | `b64u(16 random bytes)`, 22 chars |
| `BODY_SHA256` | `b64u(SHA-256(raw request body))`; for an empty body, the hash of the empty string |
| `DEVICE_ID` | the requesting device's id |
| `SERVER_FP` | `fp` of the server the client believes it is talking to |

`SERVER_FP` is what makes a captured request useless anywhere else: a signature
minted for PC-A does not verify against PC-B's `SERVER_FP`, even when the same
phone is paired to both.

### 2.2 Response

Signed by the **server** private key, sent in `X-WU-Server-Signature` on every
response including errors.

```
wol-unlock/v1/response\n
<STATUS>\n            HTTP status code, decimal
<NONCE_ECHO>\n        the nonce from the request being answered
<BODY_SHA256>\n       b64u(SHA-256(raw response body))
<SERVER_FP>\n
```

Echoing the request nonce binds the response to that exact request, so a recorded
response cannot be replayed against a later one.

`NONCE_ECHO` is taken from the `X-WU-Nonce` **request header** whenever that
header is syntactically valid (22 base64url characters decoding to 16 bytes), and
is the empty string otherwise — including on `GET /v1/server-info` and
`POST /v1/pair`, which carry no nonce. The line is always present, so the field
count never varies.

Deriving the echo from the header rather than from the authenticated context is
deliberate. Responses rejected *before* authentication runs — a rate limit, a
network-allowlist refusal, a query string on a signed route — must still be
verifiable, since those are exactly the errors a client most needs to trust.
Echoing a value an attacker chose costs nothing: it is not secret, and this
construction is domain-separated from every other signed string.

### 2.3 Pairing proof

Signed by the **device** private key being enrolled, sent as `proof` in the
`/v1/pair` body.

```
wol-unlock/v1/pair\n
<CODE>\n                  the 8-character pairing code, uppercase
<DEVICE_PUBKEY_B64URL>\n  b64u of the 32-byte key being enrolled
<SERVER_FP>\n
```

Proves possession of the private key and binds enrollment to one code on one
server, so an observed `/v1/pair` body can neither be replayed at a different PC
nor rewritten to enroll a different key.

---

## 3. Authenticated request format

### 3.1 Headers

```
X-WU-Version:   1
X-WU-Device:    <device_id>                   22 chars
X-WU-Timestamp: <unix seconds>
X-WU-Nonce:     <b64u 16 bytes>               22 chars
X-WU-Signature: <b64u 64-byte signature>      86 chars
Content-Type:   application/json              (when a body is present)
```

### 3.2 Server verification order

Fail closed; the first failure wins. All comparisons involving secrets use a
constant-time compare.

1. Peer IP ∈ `http.allowed_networks` → else `403 forbidden_network`
2. Token bucket, per device and per source IP → else `429 rate_limited`
3. Header presence and shape; no query string; body ≤ `max_body_bytes` (8 KiB) → else `400 bad_request`
4. `device_id` known → else `401 unknown_device`; not revoked → else `403 device_revoked`
5. `|now − timestamp| ≤ timestamp_skew_s` (30 s) → else `401 timestamp_out_of_window`
6. Nonce not already recorded → else `401 replayed_nonce`
7. Recomputed `SHA-256(body)` equals the value that was signed → else `401 body_hash_mismatch`
8. `Ed25519.verify(sig, canonical_request, device_pubkey)` → else `401 invalid_signature`
9. Only now: record the nonce, update `last_seen_at`, write the audit row, dispatch.

Steps 5–8 are ordered cheapest-first, and the nonce is recorded only after the
signature verifies — an unauthenticated peer therefore cannot burn nonces to
cause denial of service.

**Replay window across restarts.** Nonces live in SQLite, not memory, with
`expires_at = now + 2 × timestamp_skew_s`. Restarting the service does not reopen
a window in which a captured request becomes valid again. Expired rows are swept
every 30 s.

---

## 4. Response envelope

Every response body is one of:

```json
{ "ok": true,  "ts": 1754390000, "data": { } }
{ "ok": false, "ts": 1754390000, "error": { "code": "invalid_signature", "message": "…" } }
```

Serialized with compact separators (`,` and `:`) and `ensure_ascii=false`. The
client verifies `X-WU-Server-Signature` over the **raw received bytes** before
parsing, so serialization differences can never silently pass.

### 4.1 Error codes

| Code | HTTP | Meaning |
|---|---|---|
| `bad_request` | 400 | malformed headers, body, or JSON |
| `forbidden_network` | 403 | source IP outside `allowed_networks` |
| `unknown_device` | 401 | no such `device_id` |
| `device_revoked` | 403 | device exists but was revoked |
| `timestamp_out_of_window` | 401 | clock skew beyond tolerance |
| `replayed_nonce` | 401 | nonce already used |
| `body_hash_mismatch` | 401 | body does not match the signed hash |
| `invalid_signature` | 401 | Ed25519 verification failed |
| `rate_limited` | 429 | token bucket exhausted |
| `pairing_disabled` | 409 | no pairing window is open |
| `invalid_code` | 401 | wrong pairing code |
| `pairing_expired` | 409 | window elapsed before submission |
| `pairing_denied` | 403 | operator declined at the terminal |
| `pairing_timeout` | 409 | operator did not answer within 60 s |
| `no_session` | 409 | no graphical session found for our uid |
| `unlock_failed` | 500 | `loginctl` failed, or `LockedHint` did not clear |
| `wake_failed` | 500 | socket error sending the magic packet |
| `not_allowed` | 403 | wake target absent from the config allowlist |
| `internal_error` | 500 | unexpected fault |

---

## 5. Endpoints

Base URL `http://<host>:8765`.

### 5.1 `GET /v1/server-info` — unauthenticated

Exposes exactly what the mDNS TXT record already broadcasts, and nothing more.
Rate-limited like every other endpoint.

```json
{ "ok": true, "ts": 1754390000, "data": {
    "v": 1, "api": 1, "name": "My PC",
    "fp": "JPbtasv-EAnAMNfKVnwzykgwkRSYI2tVYabIKr7F3ig",
    "caps": ["wol", "unlock", "status"],
    "pair": false } }
```

### 5.2 `POST /v1/pair` — pairing code + proof

Request:

```json
{ "v": 1,
  "code": "K7M2QX4B",
  "device_pubkey": "A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg",
  "device_name": "My iPhone",
  "platform": "ios",
  "proof": "<b64u 64-byte signature over §2.3>" }
```

The request blocks for up to 60 s while the operator approves at the terminal.

Response `200`:

```json
{ "ok": true, "ts": 1754390000, "data": {
    "device_id": "Vkdap1RjR0wChd9dvyvKtw",
    "server_pubkey": "Kay64UG8yvCyLhqU000LxzYeUm0L_hLIl5S8kyKWbdc",
    "server_fp": "JPbtasv-EAnAMNfKVnwzykgwkRSYI2tVYabIKr7F3ig",
    "name": "My PC", "api": 1,
    "caps": ["wol", "unlock", "status"],
    "wake": { "macs": ["00:00:5e:00:53:01", "00:00:5e:00:53:02"],
              "broadcast": "192.168.1.255", "port": 9 } } }
```

The client pins `server_pubkey` and verifies `fp(server_pubkey) == server_fp` and
that this matches the `f=` parameter from the QR code before storing anything.

### 5.3 `GET /v1/status` — signed

```json
{ "ok": true, "ts": 1754390000, "data": {
    "name": "My PC", "fp": "JPbt…", "api": 1, "uptime_s": 8123,
    "session": { "id": "1", "type": "wayland", "class": "user",
                 "active": true, "locked": false, "desktop": "KDE", "seat": "seat0" },
    "wake_targets": [ { "mac": "00:00:5e:00:53:01", "iface": "enp11s0", "link": "down" },
                      { "mac": "00:00:5e:00:53:02", "iface": "wlp10s0", "link": "up" } ],
    "pairing": { "active": false } } }
```

`session` is `null` when no graphical session exists; this is not an error.

### 5.4 `POST /v1/wake` — signed

Relays a magic packet to another host. **It cannot wake the machine running the
service** — that machine is asleep and nothing is listening. Waking `my-pc`
itself is the phone's job (§7).

```json
{ "target": "self" }
{ "target": "00:00:5e:00:53:01", "broadcast": "192.168.1.255", "port": 9 }
```

`target: "self"` fans out to every configured target. An explicit MAC must appear
in the config allowlist, or the request is refused with `not_allowed` — this
endpoint is not an open UDP broadcast relay.

```json
{ "ok": true, "ts": 1754390000, "data": { "sent": [
    { "mac": "00:00:5e:00:53:01", "via": "192.168.1.255:9", "bytes": 102 },
    { "mac": "00:00:5e:00:53:02", "via": "192.168.1.255:9", "bytes": 102 } ] } }
```

### 5.5 `POST /v1/unlock` — signed

```json
{ "session_id": null }
```

`null` means auto-detect (§6). Response:

```json
{ "ok": true, "ts": 1754390000, "data": {
    "session_id": "1", "was_locked": true, "unlocked": true,
    "type": "wayland", "desktop": "KDE", "seat": "seat0" } }
```

Idempotent: an already-unlocked session returns `ok: true` with
`was_locked: false`, not an error. `unlocked` reflects a **re-read of
`LockedHint` after the call**, so it is a confirmed state change rather than a
zero exit status.

---

## 6. Session selection

1. `loginctl list-sessions --output=json`
2. Keep sessions whose `uid` equals the service's own uid.
3. For each, `loginctl show-session <id> --property=Type --property=Class --property=Active --property=LockedHint --property=Seat --value`
4. Keep `Class == "user"` and `Type ∈ {wayland, x11}` — this drops the
   `Class=manager` session that systemd creates alongside the real one.
5. Rank: `LockedHint == yes` first (that is the one worth unlocking), then
   `Active == yes`, then lowest id. Zero candidates → `no_session`.
6. Validate the chosen id against `^[a-zA-Z0-9]{1,32}$` before it is ever passed
   as an argument.
7. `loginctl unlock-session <id>`, then re-read `LockedHint` to confirm.

All invocations use `create_subprocess_exec` with an absolute path and an argument
vector. No shell is involved anywhere, so no quoting or injection surface exists.

**Why no polkit rule is needed.** `org.freedesktop.login1.policy` defines
`lock-sessions` but no `unlock-session` action. logind consults polkit only when
the caller's uid differs from the session's uid; a service running as the session
owner is authorized implicitly. The service therefore runs with no sudo, no
setuid, and no polkit rule.

**Screen-locker requirement.** `loginctl unlock-session` emits logind's `Unlock`
signal; the locker must act on it. KDE Plasma does — `libKScreenLocker.so.6`
contains `LogindIntegration`, `requestUnlock()`, and the code path logged as
*"Unlocking anyway since forced through logind."* GNOME does too. Bare
`swaylock`/`i3lock` do **not** and are unsupported.

---

## 7. Wake-on-LAN

Magic packet: `FF × 6` followed by the 6-byte target MAC repeated 16 times = **102
bytes**. With an optional 6-byte SecureOn password appended = **108 bytes**.

Sent as UDP to the subnet-directed broadcast address (e.g. `192.168.1.255`) on
port 9, with `SO_BROADCAST` set. Port 7 is also accepted by configuration.
Subnet-directed broadcast is preferred over `255.255.255.255` because it is
routable on-link and is what iOS will actually emit.

**Origin matters.** The service can only relay packets for *other* hosts. The
packet that wakes `my-pc` must come from the phone, which is why the iOS
native module opens its own `AF_INET`/`SOCK_DGRAM` socket rather than calling the
API.

---

## 8. mDNS / DNS-SD

```
service type     _wol-unlock._tcp.local.
instance name    <hostname>._wol-unlock._tcp.local.
target host      <hostname>.local.
port             8765
```

TXT records:

| Key | Example | Meaning |
|---|---|---|
| `v` | `1` | TXT schema version |
| `api` | `1` | HTTP API version |
| `name` | `My PC` | display name |
| `caps` | `wol,unlock,status` | comma-separated capabilities |
| `fp` | 43-char b64u | server public key fingerprint |
| `pair` | `0` / `1` | a pairing window is currently open |

Discovery is **untrusted hinting**. It supplies candidate addresses and lets the
app match a record to an already-paired PC by `fp`; it never establishes identity.
A spoofed record cannot impersonate a paired PC, because the response signature
will not verify against the pinned key.

### 8.1 QR payload

```
wolunlock:1?n=<name>&h=<host>&p=<port>&f=<fp>&c=<code>&m=<mac,mac>&b=<broadcast>
```

Values are percent-encoded; `m` is comma-separated MACs without separators inside
each address. Roughly 150 characters, which fits a version-7 QR and renders
legibly in a terminal.

```
wolunlock:1?n=My%20PC&h=my-pc.local&p=8765&f=JPbtasv-EAnAMNfKVnwzykgwkRSYI2tVYabIKr7F3ig&c=K7M2QX4B&m=00005e005301,00005e005302&b=192.168.1.255
```

---

## 9. Pairing state machine

```
IDLE ──pair.begin──> OPEN ──valid code+proof──> AWAITING_APPROVAL ──approve──> CLOSED(success)
  ^                   │                                │
  │                   │                                └──deny/timeout──> IDLE
  │                   ├──120 s elapsed────────────────────────────────────> IDLE
  │                   └──3 bad codes─────────────────────────────────────> IDLE
  └────────────────────────────────────────────────────────────────────────┘
```

Invariants:

- At most one window exists at a time; a second `pair.begin` is refused.
- The code is single-use and is destroyed on success **and** on denial.
- Expiry is measured against a monotonic clock, so a wall-clock change cannot
  extend a window.
- Three incorrect codes close the window entirely.
- The code is never written to logs or to the audit table.
- `pair.begin` is reachable **only** over the 0600 Unix socket with an
  `SO_PEERCRED` uid check — it has no network-facing route at all. Pairing
  consequently requires local access to the machine by construction, not by
  policy.

---

## 10. Control socket

`$XDG_RUNTIME_DIR/wol-unlock.sock`, mode `0600`, newline-delimited JSON. The
server verifies the peer's uid via `SO_PEERCRED` and closes on mismatch.

Requests `{"id": 1, "cmd": "...", "args": {}}` → responses
`{"id": 1, "ok": true, "data": {}}`. The server also pushes unsolicited events
`{"event": "pair.request", "data": {}}`.

| Command | Purpose |
|---|---|
| `status` | service + session + pairing state |
| `pair.begin` | open a window; returns code, QR payload, expiry |
| `pair.cancel` | close the window |
| `pair.approve` / `pair.deny` | answer a parked enrollment |
| `devices.list` | trusted devices with `last_seen_at` |
| `devices.revoke` | revoke by `device_id` or name prefix |
| `audit.tail` | recent audit rows |

Event `pair.request` carries `{device_name, platform, fp, device_id}` so the
operator can compare the fingerprint shown on the phone before approving.

---

## 11. Test vectors

Deterministic keys, for tests only. **Never use these.**

```
device seed  = 000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f
server seed  = 202122232425262728292a2b2c2d2e2f303132333435363738393a3b3c3d3e3f
```

### 11.1 Derived identifiers

```
device_pubkey     = 03a107bff3ce10be1d70dd18e74bc09967e4d6309ba50d5f1ddc8664125531b8
device_pubkey_b64 = A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg
device_fp         = Vkdap1RjR0wChd9dvyvKtz2mUTWIOem3dIGy6rEHcIw
device_id         = Vkdap1RjR0wChd9dvyvKtw

server_pubkey     = 29acbae141bccaf0b22e1a94d34d0bc7361e526d0bfe12c89794bc9322966dd7
server_pubkey_b64 = Kay64UG8yvCyLhqU000LxzYeUm0L_hLIl5S8kyKWbdc
server_fp         = JPbtasv-EAnAMNfKVnwzykgwkRSYI2tVYabIKr7F3ig
```

### 11.2 Request — `POST /v1/unlock`

```
body            = {"session_id":null}                 (19 bytes)
body_sha256_b64 = ugKkY33US6fv1d7EpbDeofPdvlrqoTRVMiZiUtGq8f0
timestamp       = 1754390000
nonce_bytes     = 000102030405060708090a0b0c0d0e0f
nonce           = AAECAwQFBgcICQoLDA0ODw
```

Canonical string (`\n` shown literally, trailing newline included):

```
wol-unlock/v1/request\nPOST\n/v1/unlock\n1754390000\nAAECAwQFBgcICQoLDA0ODw\nugKkY33US6fv1d7EpbDeofPdvlrqoTRVMiZiUtGq8f0\nVkdap1RjR0wChd9dvyvKtw\nJPbtasv-EAnAMNfKVnwzykgwkRSYI2tVYabIKr7F3ig\n
```

```
SHA-256(canonical) = ba3ab0822e3f159cef71db185c915be8a74591e5dcfbde4704907b53d9500a11
signature          = Fs2VYdYGCpDXJH0X6LtnfgzW1FNXitmbQKa3muzP_Py1CB3iCM-MUgWetLDQEMy4x-S3XkZepO4DX8mwsYHVDg
```

### 11.3 Request — `GET /v1/status` (empty body)

```
empty_body_sha256_b64 = 47DEQpj8HBSa-_TImW-5JCeuQeRkm5NMpJWZG3hSuFU
```

```
wol-unlock/v1/request\nGET\n/v1/status\n1754390000\nAAECAwQFBgcICQoLDA0ODw\n47DEQpj8HBSa-_TImW-5JCeuQeRkm5NMpJWZG3hSuFU\nVkdap1RjR0wChd9dvyvKtw\nJPbtasv-EAnAMNfKVnwzykgwkRSYI2tVYabIKr7F3ig\n
```

```
signature = fCaYE-4yelnVzRq0-VpCQ98jnlZUKAgfmotGaKNVqU9MsFlEPv5WeNl3VqBiLlQz-CMVB4Ei7wwOiMr1dbIUBg
```

### 11.4 Response signature

```
body = {"ok":true,"ts":1754390000,"data":{"session_id":"1","was_locked":true,"unlocked":true,"type":"wayland","desktop":"KDE","seat":"seat0"}}
body_sha256_b64 = mmGXuNks9F6NjLltYp8PGOUV29FKHmt5RF_p9GHMpf4
```

```
wol-unlock/v1/response\n200\nAAECAwQFBgcICQoLDA0ODw\nmmGXuNks9F6NjLltYp8PGOUV29FKHmt5RF_p9GHMpf4\nJPbtasv-EAnAMNfKVnwzykgwkRSYI2tVYabIKr7F3ig\n
```

```
signature = Yvn1rC017_3ALuRNIpasxGz48SpkubMHhy5bYxXztabk_937gnqjoo7eZRTijyXb0Q8j0nx5v7jpBdnLwapuCQ
```

### 11.5 Pairing proof

```
code = K7M2QX4B
```

```
wol-unlock/v1/pair\nK7M2QX4B\nA6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg\nJPbtasv-EAnAMNfKVnwzykgwkRSYI2tVYabIKr7F3ig\n
```

```
proof = f6-18J9mt5LZMvLqis1xTCknnRdjz1kar75-O6TAaeIqfaWcc_GExPsMGAm8_GIaiERrGRzyhrA1g_H16WpeCw
```

### 11.6 Magic packets

`00:00:5e:00:53:01` — 102 bytes:

```
ffffffffffff00005e00530100005e00530100005e00530100005e00530100005e005301
00005e00530100005e00530100005e00530100005e00530100005e00530100005e005301
00005e00530100005e00530100005e00530100005e00530100005e00530100005e005301
```

`00:00:5e:00:53:02` — 102 bytes:

```
ffffffffffff00005e00530200005e00530200005e00530200005e00530200005e005302
00005e00530200005e00530200005e00530200005e00530200005e00530200005e005302
00005e00530200005e00530200005e00530200005e00530200005e00530200005e005302
```

`00:00:5e:00:53:01` with SecureOn `0b:ad:c0:ff:ee:11` — 108 bytes: the 102-byte
packet above with `0badc0ffee11` appended.

---

## 12. Pairing code alphabet

Crockford base32 minus the ambiguous letters: **`0123456789ABCDEFGHJKMNPQRSTVWXYZ`**
(no `I`, `L`, `O`, `U`). Eight characters drawn from `secrets.choice` → 40 bits of
entropy. Displayed grouped as `XXXX-XXXX`; the hyphen is presentational and is
stripped before use. Input is upper-cased and `I→1`, `L→1`, `O→0` are folded
before comparison, so a misread code still works.

Brute force is bounded by the 120-second window, the three-attempt limit, and the
rate limiter — not by the entropy alone.

---

## 13. Threat model

**In scope.** A hostile device on the same LAN. It can observe every byte, replay,
inject, spoof mDNS, and reach the HTTP port.

Such an attacker cannot unlock the session: `/v1/unlock` requires a signature from
an enrolled Ed25519 key, replays are rejected by the persisted nonce cache and the
30-second window, and cross-server replay fails on `SERVER_FP`. It cannot enroll:
pairing requires a code that only ever appears on the PC's own screen, inside a
120-second window that only a local operator can open. It cannot forge results:
responses are signed and bound to the request nonce.

**Out of scope, stated plainly.**

- Anyone holding the *unlocked phone* can unlock the PC. That is the feature.
  `expo-secure-store`'s `requireAuthentication` gates the signing key behind Face
  ID, which is the mitigation.
- Magic packets are unauthenticated by design — anyone on the LAN can wake the
  machine. Waking is not a privileged action.
- Without TLS, an observer learns *which* action was requested and when. They
  cannot forge, replay, or alter it. Noise_IK over the same identities is the
  documented upgrade path.
- Root on the PC, or a compromised iOS device, defeats everything below it.
- WAN exposure is a non-goal. Reach the LAN over a VPN instead. Requests from
  outside `http.allowed_networks` are rejected at step 1 of §3.2, before any
  parsing — but that check is the service's own, not the kernel's.
  `IPAddressDeny=`/`IPAddressAllow=` install a BPF cgroup filter that requires
  root, so systemd ignores them in a `--user` unit; relying on them here would
  claim a guarantee that is not in force.

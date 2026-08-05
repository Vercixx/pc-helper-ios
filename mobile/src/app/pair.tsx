/**
 * Pairing screen.
 *
 * Reached either from a QR scan (everything pre-filled) or from the discovery
 * list / manual entry (the user types the 8-character code). Submitting parks
 * until somebody approves the device at the PC's own keyboard.
 */

import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useMemo, useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { pairWithPC } from "@/actions/pair";
import { fetchServerInfo } from "@/api/client";
import { ApiError } from "@/api/types";
import { CODE_LENGTH, normalizeCode } from "@/crypto/canonical";
import { colors, spacing, styles as shared } from "@/ui/theme";

type Params = {
  host?: string;
  port?: string;
  fp?: string;
  name?: string;
  code?: string;
  instance?: string;
};

type Phase = "form" | "checking" | "waiting" | "done";

export default function PairScreen() {
  const params = useLocalSearchParams<Params>();
  const router = useRouter();

  const [host, setHost] = useState(params.host ?? "");
  const [port, setPort] = useState(params.port ?? "8765");
  const [fingerprint, setFingerprint] = useState(params.fp ?? "");
  const [code, setCode] = useState(params.code ? normalizeCode(params.code) : "");
  const [phase, setPhase] = useState<Phase>("form");
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const scanned = Boolean(params.fp);
  const codeReady = normalizeCode(code).length === CODE_LENGTH;
  const hostReady = host.trim().length > 0;
  const portNumber = Number.parseInt(port, 10);
  const portReady = Number.isInteger(portNumber) && portNumber > 0 && portNumber < 65536;
  const canSubmit = codeReady && hostReady && portReady && phase === "form";

  const endpoint = useMemo(
    () => ({ host: host.trim(), port: portNumber }),
    [host, portNumber],
  );

  async function submit() {
    setError(null);
    setNote(null);

    try {
      // When the user typed the address by hand there is no fingerprint yet, so
      // ask the PC for it. This is trust-on-first-use and is exactly why the QR
      // path -- which carries a fingerprint the user can compare -- is preferred.
      let expected = fingerprint.trim();
      if (!expected) {
        setPhase("checking");
        const info = await fetchServerInfo(endpoint);
        expected = info.fp;
        setFingerprint(expected);
        setNote(`Pairing with "${info.name}".`);
      }

      setPhase("waiting");
      const { pc, usedBiometrics } = await pairWithPC({
        endpoint,
        code: normalizeCode(code),
        expectedFingerprint: expected,
        instanceName: params.instance,
        fallbackName: params.name,
      });

      setPhase("done");
      if (!usedBiometrics) {
        setNote(
          "Paired. Face ID isn't set up on this phone, so the key is protected by the device passcode only.",
        );
      }
      router.replace({ pathname: "/pc/[id]", params: { id: pc.id } });
    } catch (cause) {
      setPhase("form");
      setError(cause instanceof ApiError ? cause.friendly : String(cause));
    }
  }

  return (
    <>
      <Stack.Screen options={{ title: scanned ? "Confirm pairing" : "Pair with a PC" }} />
      <KeyboardAvoidingView
        style={shared.screen}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <ScrollView contentContainerStyle={local.content} keyboardShouldPersistTaps="handled">
          <View style={shared.card}>
            <Text style={local.label}>PAIRING CODE</Text>
            <TextInput
              value={code}
              onChangeText={(text) => setCode(normalizeCode(text).slice(0, CODE_LENGTH))}
              placeholder="K7M2QX4B"
              autoCapitalize="characters"
              autoCorrect={false}
              autoFocus={!params.code}
              maxLength={CODE_LENGTH + 1}
              style={local.codeInput}
              accessibilityLabel="Pairing code"
            />
            <Text style={shared.caption}>
              Shown by <Text style={shared.mono}>wol-unlockctl pair</Text> on the PC. It
              expires after two minutes.
            </Text>
          </View>

          <View style={shared.card}>
            <Text style={local.label}>PC ADDRESS</Text>
            <TextInput
              value={host}
              onChangeText={setHost}
              placeholder="my-pc.local"
              autoCapitalize="none"
              autoCorrect={false}
              keyboardType="url"
              style={local.input}
              accessibilityLabel="PC hostname"
            />
            <TextInput
              value={port}
              onChangeText={setPort}
              placeholder="8765"
              keyboardType="number-pad"
              style={local.input}
              accessibilityLabel="Port"
            />
            {!portReady ? (
              <Text style={[shared.caption, { color: colors.red }]}>
                Port must be between 1 and 65535.
              </Text>
            ) : null}
          </View>

          {fingerprint ? (
            <View style={shared.card}>
              <Text style={local.label}>PC IDENTITY</Text>
              <Text style={shared.mono}>{fingerprint}</Text>
              <Text style={shared.caption}>
                {scanned
                  ? "From the QR code. Pairing stops if the PC presents anything else."
                  : "Check this matches the fingerprint shown on the PC."}
              </Text>
            </View>
          ) : null}

          {phase === "waiting" ? (
            <View style={[shared.card, local.waiting]}>
              <ActivityIndicator />
              <View style={local.grow}>
                <Text style={shared.body}>Waiting for approval</Text>
                <Text style={shared.caption}>
                  Confirm this device at the PC. Compare the fingerprint it shows.
                </Text>
              </View>
            </View>
          ) : null}

          {error ? (
            <View style={shared.card}>
              <Text style={{ color: colors.red }}>{error}</Text>
            </View>
          ) : null}

          {note ? <Text style={[shared.caption, local.center]}>{note}</Text> : null}

          <Pressable
            style={[shared.primaryButton, !canSubmit && local.disabled]}
            disabled={!canSubmit}
            onPress={() => void submit()}
            accessibilityRole="button"
          >
            <Text style={shared.primaryButtonLabel}>
              {phase === "checking"
                ? "Contacting PC…"
                : phase === "waiting"
                  ? "Waiting…"
                  : "Pair"}
            </Text>
          </Pressable>
        </ScrollView>
      </KeyboardAvoidingView>
    </>
  );
}

const local = StyleSheet.create({
  content: { padding: spacing.lg, gap: spacing.md },
  label: { fontSize: 12, letterSpacing: 0.6, color: colors.secondaryLabel },
  input: {
    fontSize: 17,
    color: colors.label,
    paddingVertical: 10,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.separator,
  },
  codeInput: {
    fontSize: 32,
    letterSpacing: 6,
    fontWeight: "600",
    color: colors.label,
    paddingVertical: spacing.sm,
    textAlign: "center",
  },
  waiting: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  grow: { flex: 1, gap: 2 },
  center: { textAlign: "center" },
  disabled: { opacity: 0.4 },
});

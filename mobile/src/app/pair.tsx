/**
 * Pairing screen.
 *
 * Reached either from a QR scan (everything pre-filled) or from the discovery
 * list / manual entry (the user types the 8-character code). Submitting parks
 * until somebody approves the device at the PC's own keyboard.
 *
 * Each field is held twice on purpose. The SwiftUI `TextField` is driven by an
 * `ObservableState`, which lives on the native side and does not re-render
 * React; the plain `useState` beside it is the copy this component validates
 * and submits. `onTextChange` keeps the two in step.
 */

import {
  Button,
  Form,
  HStack,
  ProgressView,
  Section,
  Spacer,
  Text,
  TextField,
  VStack,
  useNativeState,
} from "@expo/ui/swift-ui";
import {
  accessibilityLabel,
  autocorrectionDisabled,
  buttonBorderShape,
  buttonStyle,
  controlSize,
  disabled,
  font,
  foregroundStyle,
  keyboardType,
  kerning,
  lineLimit,
  multilineTextAlignment,
  textInputAutocapitalization,
  textSelection,
} from "@expo/ui/swift-ui/modifiers";
import * as Haptics from "expo-haptics";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useMemo, useState } from "react";

import { pairWithPC } from "@/actions/pair";
import { fetchServerInfo } from "@/api/client";
import { ApiError } from "@/api/types";
import { CODE_LENGTH, normalizeCode } from "@/crypto/canonical";
import { useT } from "@/i18n";
import { PAIR_COMMAND_MARKDOWN } from "@/ui/copy";
import { Screen } from "@/ui/Screen";
import { colors, secondaryText } from "@/ui/theme";

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
  const t = useT();

  const initialCode = params.code ? normalizeCode(params.code) : "";
  const initialHost = params.host ?? "";
  const initialPort = params.port ?? "8765";

  // The native side of each field. `useNativeState` captures its argument on
  // the first render only, which is also the only chance to seed a TextField --
  // it has no `defaultValue`.
  const codeState = useNativeState(initialCode);
  const hostState = useNativeState(initialHost);
  const portState = useNativeState(initialPort);

  const [code, setCode] = useState(initialCode);
  const [host, setHost] = useState(initialHost);
  const [port, setPort] = useState(initialPort);
  const [fingerprint, setFingerprint] = useState(params.fp ?? "");
  const [phase, setPhase] = useState<Phase>("form");
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const scanned = Boolean(params.fp);
  const codeReady = code.length === CODE_LENGTH;
  const hostReady = host.trim().length > 0;
  const portNumber = Number.parseInt(port, 10);
  const portReady = Number.isInteger(portNumber) && portNumber > 0 && portNumber < 65536;
  const canSubmit = codeReady && hostReady && portReady && phase === "form";

  const endpoint = useMemo(
    () => ({ host: host.trim(), port: portNumber }),
    [host, portNumber],
  );

  /**
   * Fold look-alike characters as they are typed.
   *
   * The field only gets written back when normalising actually changed
   * something -- echoing every keystroke would fight the cursor.
   */
  function onCodeChange(text: string) {
    const normalized = normalizeCode(text).slice(0, CODE_LENGTH);
    setCode(normalized);
    if (normalized !== text) codeState.set(normalized);
  }

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
        setNote(t("pair.with", { name: info.name }));
      }

      setPhase("waiting");
      await pairWithPC({
        endpoint,
        code,
        expectedFingerprint: expected,
        instanceName: params.instance,
        fallbackName: params.name,
      });

      setPhase("done");
      // Land on the list, where the new PC is now a row, rather than pushing
      // its detail screen on top of the pairing sheet. The haptic stands in for
      // the confirmation that screen used to provide.
      void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      router.dismissTo("/");
    } catch (cause) {
      setPhase("form");
      setError(cause instanceof ApiError ? cause.friendly : String(cause));
    }
  }

  return (
    <>
      <Stack.Screen
        options={{ title: scanned ? t("nav.confirmPairing") : t("nav.pairWithPC") }}
      />
      {/* No KeyboardAvoidingView: a SwiftUI Form already lifts the focused
          field clear of the keyboard, which is one of the things that stops
          having to be reimplemented here. */}
      <Screen>
        <Form>
          <Section
            title={t("pair.code.label")}
            footer={
              <Text markdownEnabled modifiers={[font({ size: 13 }), secondaryText, lineLimit()]}>
                {t("pair.code.hint", { cmd: PAIR_COMMAND_MARKDOWN })}
              </Text>
            }
          >
            <TextField
              text={codeState}
              placeholder="K7M2QX4B"
              maxLength={CODE_LENGTH}
              autoFocus={!params.code}
              onTextChange={onCodeChange}
              modifiers={[
                font({ size: 28, weight: "semibold", design: "monospaced" }),
                kerning(6),
                multilineTextAlignment("center"),
                textInputAutocapitalization("characters"),
                autocorrectionDisabled(),
                accessibilityLabel(t("pair.code.a11y")),
              ]}
            />
          </Section>

          <Section
            title={t("pair.address.label")}
            footer={
              !portReady ? (
                <Text modifiers={[font({ size: 13 }), foregroundStyle(colors.red)]}>
                  {t("pair.port.range")}
                </Text>
              ) : undefined
            }
          >
            <TextField
              text={hostState}
              placeholder="my-pc.local"
              onTextChange={setHost}
              modifiers={[
                keyboardType("url"),
                textInputAutocapitalization("never"),
                autocorrectionDisabled(),
                accessibilityLabel(t("pair.host.a11y")),
              ]}
            />
            <TextField
              text={portState}
              placeholder="8765"
              onTextChange={setPort}
              modifiers={[keyboardType("numeric"), accessibilityLabel(t("pair.port.a11y"))]}
            />
          </Section>

          {fingerprint ? (
            <Section
              title={t("pair.identity.label")}
              footer={
                <Text modifiers={[font({ size: 13 }), secondaryText, lineLimit()]}>
                  {scanned ? t("pair.identity.scanned") : t("pair.identity.manual")}
                </Text>
              }
            >
              <Text
                modifiers={[
                  font({ size: 12, design: "monospaced" }),
                  lineLimit(),
                  textSelection(true),
                ]}
              >
                {fingerprint}
              </Text>
            </Section>
          ) : null}

          {phase === "waiting" ? (
            <Section>
              <HStack spacing={12}>
                <ProgressView />
                <VStack alignment="leading" spacing={2}>
                  <Text>{t("pair.waiting.title")}</Text>
                  <Text modifiers={[font({ size: 13 }), secondaryText, lineLimit()]}>
                    {t("pair.waiting.body")}
                  </Text>
                </VStack>
                <Spacer />
              </HStack>
            </Section>
          ) : null}

          {error ? (
            <Section>
              <Text modifiers={[foregroundStyle(colors.red), lineLimit()]}>{error}</Text>
            </Section>
          ) : null}

          <Section
            footer={
              note ? (
                <Text modifiers={[font({ size: 13 }), secondaryText]}>{note}</Text>
              ) : undefined
            }
          >
            <HStack>
              <Spacer />
              <Button
                label={
                  phase === "checking"
                    ? t("pair.contacting")
                    : phase === "waiting"
                      ? t("pair.waiting")
                      : t("pair.submit")
                }
                onPress={() => void submit()}
                modifiers={[
                  buttonStyle("glassProminent"),
                  buttonBorderShape("capsule"),
                  controlSize("large"),
                  disabled(!canSubmit),
                ]}
              />
              <Spacer />
            </HStack>
          </Section>
        </Form>
      </Screen>
    </>
  );
}

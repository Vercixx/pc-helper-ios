/**
 * "＋" sheet: PCs found on the network via mDNS, plus the QR fallback.
 *
 * What is shown here is untrusted. It decides what to display and which address
 * to try first; identity is only established when pairing verifies the
 * fingerprint against the one in the code the user scans or types.
 */

import {
  Button,
  Form,
  HStack,
  Image,
  ProgressView,
  Section,
  Spacer,
  Text,
  VStack,
} from "@expo/ui/swift-ui";
import {
  accessibilityLabel,
  buttonStyle,
  font,
  foregroundStyle,
  lineLimit,
} from "@expo/ui/swift-ui/modifiers";
import { Stack, useRouter } from "expo-router";
import { useMemo } from "react";

import { useDiscovery, type DiscoveredPC } from "@/discovery/useDiscovery";
import { useT } from "@/i18n";
import { usePCStore } from "@/state/store";
import { PAIR_COMMAND_MARKDOWN } from "@/ui/copy";
import { Screen } from "@/ui/Screen";
import { accent, secondaryText, tertiaryText } from "@/ui/theme";

export default function DiscoverScreen() {
  const router = useRouter();
  const { available, services, state, error } = useDiscovery(true);
  const pcs = usePCStore((store) => store.pcs);
  const t = useT();

  const pairedFingerprints = useMemo(
    () => new Set(pcs.map((pc) => pc.serverFp)),
    [pcs],
  );

  return (
    <>
      <Stack.Screen options={{ title: t("nav.addPC") }} />
      <Screen>
        <Form>
          <Section>
            <ChoiceRow
              symbol="qrcode.viewfinder"
              title={t("discover.scan.title")}
              onPress={() => router.push("/scan")}
            >
              {/* The command reaches the sentence as a `{cmd}` parameter and is
                  backticked, so SwiftUI's markdown renders it monospaced. It
                  used to be spliced in as a separate React Native <Text>, which
                  has no equivalent here. */}
              <Text
                markdownEnabled
                modifiers={[font({ size: 13 }), secondaryText, lineLimit()]}
              >
                {t("discover.scan.body", { cmd: PAIR_COMMAND_MARKDOWN })}
              </Text>
            </ChoiceRow>

            <ChoiceRow
              symbol="keyboard"
              title={t("discover.manual.title")}
              onPress={() => router.push("/pair")}
            >
              <Text modifiers={[font({ size: 13 }), secondaryText, lineLimit()]}>
                {t("discover.manual.body")}
              </Text>
            </ChoiceRow>
          </Section>

          <Section
            title={t("discover.section")}
            footer={
              <Text modifiers={[font({ size: 13 }), secondaryText]}>
                {t("discover.footnote")}
              </Text>
            }
          >
            {!available ? (
              <VStack alignment="leading" spacing={2}>
                <Text>{t("discover.unavailable.title")}</Text>
                <Text modifiers={[font({ size: 13 }), secondaryText, lineLimit()]}>
                  {error ?? t("discover.unavailable.body")}
                </Text>
              </VStack>
            ) : services.length === 0 ? (
              <HStack spacing={12}>
                {state === "failed" ? null : <ProgressView />}
                <VStack alignment="leading" spacing={2}>
                  <Text>{state === "failed" ? t("discover.failed") : t("discover.looking")}</Text>
                  {error ? (
                    <Text
                      modifiers={[font({ size: 13 }), secondaryText, lineLimit()]}
                    >
                      {error}
                    </Text>
                  ) : null}
                </VStack>
                <Spacer />
              </HStack>
            ) : (
              services.map((service) => (
                <DiscoveredRow
                  key={service.instanceName}
                  service={service}
                  alreadyPaired={pairedFingerprints.has(service.fingerprint)}
                  onPress={() =>
                    router.push({
                      pathname: "/pair",
                      params: {
                        host: service.hostname,
                        instance: service.instanceName,
                        fp: service.fingerprint,
                        name: service.displayName,
                      },
                    })
                  }
                />
              ))
            )}
          </Section>
        </Form>
      </Screen>
    </>
  );
}

/** A tappable row: symbol, title, and a caption supplied as children. */
function ChoiceRow({
  symbol,
  title,
  onPress,
  children,
}: {
  symbol: "qrcode.viewfinder" | "keyboard";
  title: string;
  onPress: () => void;
  children: React.ReactElement;
}) {
  return (
    <Button onPress={onPress} modifiers={[buttonStyle("plain"), accessibilityLabel(title)]}>
      <HStack spacing={14}>
        <Image systemName={symbol} size={26} modifiers={[foregroundStyle(accent)]} />
        <VStack alignment="leading" spacing={2}>
          <Text>{title}</Text>
          {children}
        </VStack>
        <Spacer />
        <Image systemName="chevron.right" size={13} modifiers={[tertiaryText]} />
      </HStack>
    </Button>
  );
}

function DiscoveredRow({
  service,
  alreadyPaired,
  onPress,
}: {
  service: DiscoveredPC;
  alreadyPaired: boolean;
  onPress: () => void;
}) {
  const t = useT();
  return (
    <Button
      onPress={onPress}
      modifiers={[
        buttonStyle("plain"),
        accessibilityLabel(
          alreadyPaired
            ? t("discover.a11y.alreadyPaired", { name: service.displayName })
            : service.displayName,
        ),
      ]}
    >
      <VStack alignment="leading" spacing={2}>
        <HStack>
          <Text>{service.displayName}</Text>
          <Spacer />
          {alreadyPaired ? (
            <Text modifiers={[font({ size: 13 }), foregroundStyle("green")]}>
              {t("discover.paired")}
            </Text>
          ) : service.pairingOpen ? (
            <Text modifiers={[font({ size: 13 }), foregroundStyle(accent)]}>
              {t("discover.pairingOpen")}
            </Text>
          ) : null}
        </HStack>
        <Text modifiers={[font({ size: 13 }), secondaryText]}>
          {service.hostname}
        </Text>
        {service.fingerprint ? (
          <Text
            modifiers={[
              font({ size: 12, design: "monospaced" }),
              secondaryText,
            ]}
          >
            {`${service.fingerprint.slice(0, 24)}…`}
          </Text>
        ) : null}
        {service.capabilities.length > 0 ? (
          <Text modifiers={[font({ size: 13 }), secondaryText]}>
            {service.capabilities.join(" · ")}
          </Text>
        ) : null}
      </VStack>
    </Button>
  );
}

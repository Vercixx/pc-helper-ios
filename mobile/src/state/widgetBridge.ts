/**
 * Publishes the store for native code to read.
 *
 * The Swift App Intents in `native/` run in this same process but cannot see
 * AsyncStorage, so the store is mirrored to two places:
 *
 *  1. A JSON file in the app's Documents directory. This always works -- same
 *     container, no entitlement -- and is what Shortcuts actions run on.
 *  2. App Group UserDefaults, for the widget extension, *if* the entitlement is
 *     live. On a free-account sideload it usually is not, so this is
 *     best-effort and its failure is not allowed to matter.
 *
 * Consumed by `native/WUSharedState.swift`.
 */

import { File, Paths } from "expo-file-system";
import { Platform } from "react-native";

import { usePCStore } from "./store";
import { buildWidgetPayload } from "./widgetPayload";

export const APP_GROUP = "group.com.vercixx.wolunlock";
/** Must match `SharedState.stateKey` in the native sources. */
const STATE_KEY = "wolunlock.state";
/** Must match `SharedState.stateFileName`. */
const STATE_FILE = "wolunlock-state.json";

/** At most one publish per this interval; widget reloads are budgeted by iOS. */
const MIN_PUBLISH_INTERVAL_MS = 2_000;

let lastPublished: string | null = null;
let lastPublishedAt = 0;
let pending: ReturnType<typeof setTimeout> | null = null;

/** The path Shortcuts actions read. Must succeed; everything else is extra. */
function writeStateFile(serialized: string): void {
  try {
    const file = new File(Paths.document, STATE_FILE);
    file.write(serialized);
  } catch {
    /* A failure here costs Shortcuts actions their data, not the app. */
  }
}

/**
 * The App Group path, for the widget extension.
 *
 * Loaded lazily and tolerated failing: `@bacons/apple-targets` is only present
 * while the widget target is enabled, and even then the entitlement may not
 * have survived signing.
 */
function writeAppGroup(serialized: string): void {
  if (Platform.OS !== "ios") return;
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const mod = require("@bacons/apple-targets") as
      | typeof import("@bacons/apple-targets")
      | undefined;
    if (!mod?.ExtensionStorage) return;
    new mod.ExtensionStorage(APP_GROUP).set(STATE_KEY, serialized);
    mod.ExtensionStorage.reloadWidget();
    mod.ExtensionStorage.reloadControls();
  } catch {
    /* No App Group at runtime. Widgets are optional; the app is not. */
  }
}

function write(serialized: string): void {
  writeStateFile(serialized);
  writeAppGroup(serialized);
}

/**
 * Publish the current store contents.
 *
 * Skips writing when nothing the widget can see has changed, so a burst of
 * status updates does not spend the day's widget refresh budget.
 */
export function publishWidgetState(): void {
  const { pcs, statuses } = usePCStore.getState();
  const serialized = JSON.stringify(buildWidgetPayload(pcs, statuses));
  if (serialized === lastPublished) return;

  const elapsed = Date.now() - lastPublishedAt;
  if (elapsed < MIN_PUBLISH_INTERVAL_MS) {
    if (pending) return;
    pending = setTimeout(() => {
      pending = null;
      publishWidgetState();
    }, MIN_PUBLISH_INTERVAL_MS - elapsed);
    return;
  }

  lastPublished = serialized;
  lastPublishedAt = Date.now();
  write(serialized);
}

/** Mirror the store into the App Group for as long as the app is running. */
export function startWidgetSync(): () => void {
  publishWidgetState();
  const unsubscribe = usePCStore.subscribe(() => publishWidgetState());
  return () => {
    unsubscribe();
    if (pending) {
      clearTimeout(pending);
      pending = null;
    }
  };
}

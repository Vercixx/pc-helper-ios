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

import { publishToAppGroup } from "@modules/app-group";

import { usePCStore } from "./store";
import { buildWidgetPayload } from "./widgetPayload";

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
 * The identifier is discovered natively rather than hardcoded: a re-signing
 * tool rewrites it, and addressing the wrong container fails silently.
 */
function writeAppGroup(serialized: string): void {
  lastAppGroupWriteSucceeded = publishToAppGroup(serialized);
}

function write(serialized: string): void {
  writeStateFile(serialized);
  writeAppGroup(serialized);
}

let lastAppGroupWriteSucceeded = false;

/** Whether the last publish reached the shared container. For diagnostics. */
export function isWidgetStorageWorking(): boolean {
  return lastAppGroupWriteSucceeded;
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

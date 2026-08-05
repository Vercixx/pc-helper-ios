/**
 * Keeps the widget extension's copy of the world up to date.
 *
 * The extension cannot read AsyncStorage or the app's keychain items by
 * default; it sees only what is written into the shared App Group container.
 * This mirrors the store there and asks WidgetKit to redraw.
 *
 * Every call is wrapped: if the App Group entitlement is missing -- which is
 * exactly what happens when a sideloading tool strips it -- the native module
 * throws, and the app must carry on working with no widgets rather than fail.
 */

import { ExtensionStorage } from "@bacons/apple-targets";
import { Platform } from "react-native";

import { usePCStore } from "./store";
import { buildWidgetPayload } from "./widgetPayload";

export const APP_GROUP = "group.com.vercixx.wolunlock";
/** Must match `SharedState.stateKey` in the extension. */
const STATE_KEY = "wolunlock.state";

/** At most one publish per this interval; widget reloads are budgeted by iOS. */
const MIN_PUBLISH_INTERVAL_MS = 2_000;

let storage: ExtensionStorage | null = null;
let storageResolved = false;
let lastPublished: string | null = null;
let lastPublishedAt = 0;
let pending: ReturnType<typeof setTimeout> | null = null;

function getStorage(): ExtensionStorage | null {
  if (storageResolved) return storage;
  storageResolved = true;
  if (Platform.OS !== "ios") return null;
  try {
    storage = new ExtensionStorage(APP_GROUP);
  } catch {
    storage = null;
  }
  return storage;
}

function write(serialized: string): void {
  const target = getStorage();
  if (!target) return;
  try {
    target.set(STATE_KEY, serialized);
    ExtensionStorage.reloadWidget();
    ExtensionStorage.reloadControls();
  } catch {
    /* No App Group at runtime. Widgets are optional; the app is not. */
  }
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

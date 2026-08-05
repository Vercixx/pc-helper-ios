/**
 * Mocks every suite needs, rather than every suite repeating them.
 *
 * `t()` is callable from anywhere -- `ApiError.friendly`, the wake actions --
 * so the i18n module, and with it the persisted language setting, is reachable
 * from almost any import chain. Without AsyncStorage mocked here, a test that
 * merely touches an error message fails on a native module that does not exist
 * under Node.
 */

jest.mock("@react-native-async-storage/async-storage", () =>
  require("@react-native-async-storage/async-storage/jest/async-storage-mock"),
);

// Same reasoning: `expo-localization` reads the system language over the
// bridge. Tests run against the English catalogue, which is the fallback.
jest.mock("expo-localization", () => ({
  getLocales: () => [{ languageCode: "en", languageTag: "en-US" }],
}));

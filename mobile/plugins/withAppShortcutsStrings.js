/**
 * Copies `mobile/locales/ios/<lang>.lproj/AppShortcuts.strings` into the app
 * target and registers each one as a resource.
 *
 * Everything else this app localizes is already handled: `ios.entitlements`-style
 * Info.plist strings and `Localizable.strings` both come from the `locales`
 * field in app.json, which Expo's own config plugin writes into
 * `ios/<Project>/Supporting/<lang>.lproj/` and adds to the project. But Expo
 * writes exactly those two file names, and Siri phrases have to be in a third,
 * `AppShortcuts.strings` -- Apple resolves phrases by looking that file up by
 * name.
 *
 * So this drops the extra file into the same `.lproj` directories Expo made and
 * registers it the same way. It deliberately runs *after* `withLocales` (which
 * `expo-localization` and the base config schedule), because `addResourceFileToGroup`
 * needs the group to exist.
 */

const { IOSConfig, withXcodeProject } = require("expo/config-plugins");
const fs = require("fs");
const path = require("path");

/** Where the .lproj folders live in the repo, relative to the Expo project root. */
const SOURCE_DIR = path.join("locales", "ios");
const FILE_NAME = "AppShortcuts.strings";

function languages(sourceDir) {
  if (!fs.existsSync(sourceDir)) return [];
  return fs
    .readdirSync(sourceDir)
    .filter((name) => name.endsWith(".lproj"))
    .filter((name) => fs.existsSync(path.join(sourceDir, name, FILE_NAME)))
    .sort();
}

module.exports = function withAppShortcutsStrings(config) {
  return withXcodeProject(config, (cfg) => {
    const { projectRoot, platformProjectRoot } = cfg.modRequest;
    const projectName = IOSConfig.XcodeUtils.getProjectName(projectRoot);
    const source = path.join(projectRoot, SOURCE_DIR);
    // The same directory Expo's `locales` support writes InfoPlist.strings to.
    const supporting = path.join(platformProjectRoot, projectName, "Supporting");

    const found = languages(source);
    if (found.length === 0) {
      throw new Error(`[withAppShortcutsStrings] no <lang>.lproj/${FILE_NAME} under ${source}`);
    }

    for (const lproj of found) {
      const destination = path.join(supporting, lproj);
      fs.mkdirSync(destination, { recursive: true });
      fs.copyFileSync(
        path.join(source, lproj, FILE_NAME),
        path.join(destination, FILE_NAME),
      );

      const groupName = `${projectName}/Supporting/${lproj}`;
      const group = IOSConfig.XcodeUtils.ensureGroupRecursively(cfg.modResults, groupName);
      // Adding it twice would produce a duplicate build file and a warning
      // about the same resource being copied more than once.
      if (group?.children.some(({ comment }) => comment === FILE_NAME)) continue;

      IOSConfig.XcodeUtils.addResourceFileToGroup({
        filepath: path.join(lproj, FILE_NAME),
        groupName,
        project: cfg.modResults,
        isBuildFile: true,
      });
    }

    return cfg;
  });
};

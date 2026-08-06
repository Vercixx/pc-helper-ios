/**
 * Product strings that are not translated, only substituted.
 *
 * The pairing command is the same in every language, but it appears inside
 * three different translated sentences, so it goes in as a `{cmd}` parameter
 * rather than being spliced around.
 */

/** What the user runs on the PC. */
export const PAIR_COMMAND = "wol-unlockctl pair";

/**
 * The same command, fenced for a SwiftUI `Text` with `markdownEnabled`, which
 * renders backticked spans in a monospaced face. This replaced an earlier
 * split-the-sentence-in-two dance that only worked with React Native `Text`.
 */
export const PAIR_COMMAND_MARKDOWN = `\`${PAIR_COMMAND}\``;

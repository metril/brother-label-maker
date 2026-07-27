import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";
import { globalIgnores } from "eslint/config";

export default tseslint.config(
  globalIgnores(["dist", "coverage"]),
  {
    files: ["**/*.{ts,tsx}"],
    // Deliberately NOT reactHooks.configs.flat.recommended/"recommended-latest":
    // both bundle react-hooks v7's new React Compiler-readiness rule set
    // (purity/immutability/set-state-in-effect/...), which is tuned for
    // compiler-eligibility, not for flagging real bugs -- e.g.
    // set-state-in-effect fires on legitimate "sync local state from an
    // external system" effects (WS events / polled job status in
    // PrintButton.tsx) with no actual issue. Hand-picking just the two
    // well-established correctness rules keeps this "recommended, not
    // strict-pedantic" per the task brief.
    extends: [js.configs.recommended, tseslint.configs.recommended, reactRefresh.configs.vite],
    plugins: { "react-hooks": reactHooks },
    languageOptions: {
      ecmaVersion: 2023,
      globals: globals.browser,
    },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
    },
  },
);

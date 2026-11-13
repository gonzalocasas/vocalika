import { readFileSync } from "node:fs"

import { defineConfig } from "vite"
import vue from "@vitejs/plugin-vue"

import { thirdPartyNotices } from "./thirdParty"

export default defineConfig({
  plugins: [vue(), thirdPartyNotices()],
  define: {
    __APP_VERSION__: JSON.stringify(
      (JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8")) as { version: string }).version,
    ),
  },
  server: {
    // The What's new notes come from the repository's CHANGELOG.md.
    fs: { allow: [".."] },
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
})

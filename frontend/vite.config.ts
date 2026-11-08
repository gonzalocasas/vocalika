import { defineConfig } from "vite"
import vue from "@vitejs/plugin-vue"

import { thirdPartyNotices } from "./thirdParty"

export default defineConfig({
  plugins: [vue(), thirdPartyNotices()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
})

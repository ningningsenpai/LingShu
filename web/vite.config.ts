import { fileURLToPath, URL } from "node:url";

import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    host: "127.0.0.1",
    port: 18766,
    strictPort: true,
    proxy: {
      "/api": "http://127.0.0.1:18765",
    },
  },
  build: {
    outDir: "../src/lingshu/dashboard/static",
    emptyOutDir: true,
  },
  test: {
    environment: "jsdom",
  },
});

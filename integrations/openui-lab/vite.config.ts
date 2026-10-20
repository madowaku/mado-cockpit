import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Loopback-only lab. Only the exact read-only dashboard endpoint is proxied.
// No action or Human Gate write routes are available to this frontend.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 4179,
    strictPort: true,
    proxy: {
      "^/cockpit-read$": {
        target: "http://127.0.0.1:8765",
        changeOrigin: false,
        rewrite: () => "/api/dashboard",
      },
    },
  },
  preview: { host: "127.0.0.1", port: 4180, strictPort: true },
});

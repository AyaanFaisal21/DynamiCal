import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the API runs separately on port 8000. In production the
// FastAPI server serves the built files from frontend/dist.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  build: { outDir: "dist", emptyOutDir: true },
});

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // In development the API runs on :8000; in production CloudFront routes /api/* to the ALB.
    proxy: { "/api": "http://localhost:8000" },
  },
});

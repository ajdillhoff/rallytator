import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies the backend's frame-delivery + annotation-store routes to the
// FastAPI process (default :8099, override with RALLYTATOR_BACKEND). Keeps the frontend
// origin-relative so a production build can be served by FastAPI directly (ADR-0001).
const backend = process.env.RALLYTATOR_BACKEND ?? "http://127.0.0.1:8099";
const proxy = Object.fromEntries(
  ["/frame", "/video", "/videos", "/tracks", "/detections", "/open"].map((p) => [
    p,
    { target: backend, changeOrigin: true },
  ]),
);

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy },
});

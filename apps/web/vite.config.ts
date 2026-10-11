import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "VITE_");
  const target = env.VITE_HACHI_API_PROXY_TARGET || "http://127.0.0.1:8717";
  const replayTarget = env.VITE_HACHI_REPLAY_PROXY_TARGET || "http://127.0.0.1:5180";
  const proxy = {
    "/v1": { target, changeOrigin: true },
    "/replay": { target: replayTarget, changeOrigin: true },
    "/healthz": { target, changeOrigin: true },
  };
  return {
    plugins: [react()],
    server: { proxy },
    preview: { proxy },
  };
});

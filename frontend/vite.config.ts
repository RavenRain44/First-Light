import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, "..", "");
  const apiPort = env.API_PORT || "8000";

  return {
    envDir: "..",
    plugins: [react()],
    server: { port: 5173, proxy: { "/api": `http://127.0.0.1:${apiPort}` } },
  };
});

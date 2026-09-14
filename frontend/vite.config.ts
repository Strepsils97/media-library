import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { outDir: "dist", emptyOutDir: true },
  // У розробці фронт живе окремо від FastAPI, тому /api проксіюється.
  // Порт бекенда фіксований лише для dev-режиму; у продакшені він випадковий.
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});

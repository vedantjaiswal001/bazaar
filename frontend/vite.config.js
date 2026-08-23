import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
// Dev server proxies /api to the FastAPI backend (make run -> :8000).
// In production set VITE_API_BASE to the backend origin.
export default defineConfig({
    plugins: [react()],
    server: {
        port: 5173,
        proxy: { "/api": "http://localhost:8000" },
    },
});

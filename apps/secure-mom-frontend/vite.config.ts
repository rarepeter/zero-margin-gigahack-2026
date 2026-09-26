import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

// The Python REST server runs locally. In dev, Vite proxies API calls to it so the
// browser talks to one origin only (no CORS setup needed on the backend).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '');
  const host = env.VITE_DEV_HOST || '127.0.0.1';
  const port = Number(env.VITE_DEV_PORT || '3100');
  const target = env.VITE_API_TARGET || 'http://127.0.0.1:8000';
  // `vite --mode live` (npm run dev:live) or VITE_API_MODE=live → real server; anything else → example data.
  const apiMode = mode === 'live' || env.VITE_API_MODE === 'live' ? 'live' : 'mock';
  return {
    plugins: [react()],
    define: { 'import.meta.env.VITE_API_MODE': JSON.stringify(apiMode) },
    server: {
      host,
      port,
      strictPort: true,
      proxy: {
        '/api': { target, changeOrigin: true },
        '/health': { target, changeOrigin: true },
        '/ready': { target, changeOrigin: true },
      },
    },
    preview: { host, port, strictPort: true },
    build: { outDir: 'dist', sourcemap: false },
  };
});

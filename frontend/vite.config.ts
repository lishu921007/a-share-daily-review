import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const apiProxy = process.env.VITE_API_PROXY || 'http://127.0.0.1:8000';
const port = Number(process.env.VITE_PORT || 5173);

export default defineConfig({
  plugins: [react()],
  server: {
    port,
    proxy: { '/api': apiProxy },
  },
  preview: {
    port,
    host: '0.0.0.0',
    proxy: { '/api': apiProxy },
  },
});

import { defineConfig, loadEnv } from 'vite';
import vue from '@vitejs/plugin-vue';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const daemonTarget = env.VITE_MOZILCODE_DAEMON_HTTP || 'http://127.0.0.1:7800';

  return {
    plugins: [vue()],
    clearScreen: false,
    server: {
      port: 1420,
      strictPort: true,
      proxy: {
        '/api': {
          target: daemonTarget,
          changeOrigin: true,
          ws: true,
        },
      },
    },
    build: {
      outDir: 'dist',
      emptyOutDir: true,
    },
  };
});

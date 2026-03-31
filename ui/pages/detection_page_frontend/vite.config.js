import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [vue()],
  publicDir: false,
  build: {
    outDir: resolve(__dirname, '../detection_page_assets/dist'),
    emptyOutDir: true,
  },
});

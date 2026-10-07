import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const projectDirectory = dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react()],
  base: '/assets/digital-twin/',
  publicDir: false,
  build: {
    outDir: resolve(projectDirectory, '../adapters/static/assets/digital-twin'),
    emptyOutDir: true,
    sourcemap: false,
    // Three.js is 758 kB minified / 195 kB gzip in its own cacheable chunk.
    chunkSizeWarningLimit: 800,
    rollupOptions: {
      input: resolve(projectDirectory, 'src/main.tsx'),
      output: {
        entryFileNames: 'farm.js',
        chunkFileNames: 'chunk-[name]-[hash].js',
        assetFileNames: (asset) => asset.name?.endsWith('.css') ? 'farm.css' : 'asset-[name][extname]',
        manualChunks(id) {
          if (id.includes('/node_modules/@react-three/drei/')
            || id.includes('/node_modules/three-stdlib/')
            || id.includes('/node_modules/camera-controls/')) return 'three-controls';
          if (id.includes('/node_modules/@react-three/fiber/')) return 'react-three-fiber';
          if (id.includes('/node_modules/three/')) return 'three-core';
          if (id.includes('/node_modules/react-dom/')
            || id.includes('/node_modules/react/')
            || id.includes('/node_modules/scheduler/')) return 'react-core';
        },
      },
    },
  },
});

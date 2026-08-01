// import { defineConfig } from 'vite'
// import react from '@vitejs/plugin-react'
// import tailwindcss from '@tailwindcss/vite'

// // https://vite.dev/config/
// export default defineConfig({
//   plugins: [react(), tailwindcss()],
//   server: {
//     // optional: proxy /api to the RepoLens FastAPI backend so pages can
//     // fetch('/api/repos') without hardcoding the port (CORS also works
//     // without this — the API allows cross-origin requests).
//     proxy: {
//       '/api': {
//         target: 'http://127.0.0.1:8000',
//         changeOrigin: true,
//         rewrite: (path) => path.replace(/^\/api/, ''),
//       },
//     },
//   },
// })
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true, // Listens on all local IPs, necessary for Tailscale
    port: 5173, // Ensure the port is fixed so Tailscale always finds it
    // allowedHosts: true, // or e.g. ['your-node-name.your-tailnet.ts.net']
    allowedHosts: ['atharva.tailfbc6c8.ts.net'],
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
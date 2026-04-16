import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      devOptions: { enabled: true },
      manifest: {
        name: 'PulseTrade HD Dashboard',
        short_name: 'PulseTrade',
        description: 'Day Trading GUI PWA App',
        theme_color: '#1e1e1e',
        background_color: '#1e1e1e',
        display: 'standalone',
        icons: [
          { src: 'favicon.svg', sizes: '192x192', type: 'image/svg+xml' },
          { src: 'favicon.svg', sizes: '512x512', type: 'image/svg+xml' }
        ]
      }
    })
  ],
  base: './',
})

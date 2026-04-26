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
        name: '투자봇J',
        short_name: '투자봇J',
        description: 'Day Trading GUI PWA App',
        theme_color: '#1e1e1e',
        background_color: '#1e1e1e',
        display: 'standalone',
        icons: [
          { src: 'tradinggui.png', sizes: '192x192', type: 'image/png' },
          { src: 'tradinggui.png', sizes: '512x512', type: 'image/png' }
        ]
      }
    })
  ],
  base: './',
})

import { defineConfig } from 'astro/config';
import tailwind from '@astrojs/tailwind';
import sitemap from '@astrojs/sitemap';

export default defineConfig({
  site: 'https://bf-alpha-liart.vercel.app',
  integrations: [tailwind(), sitemap()],
  build: {
    format: 'directory',
  },
});

// Static build for the wisp.observer homepage. React renders the page once at
// build time (see build.mjs); the browser gets plain HTML, one stylesheet and a
// small module. Nothing is fetched from another host.
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

export default defineConfig({
  root: fileURLToPath(new URL(".", import.meta.url)),
  base: "/",
  publicDir: "public",
  plugins: [tailwindcss()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  build: {
    assetsDir: "app",
    // Small modules only; the WebGL hero is a separate lazy chunk.
    modulePreload: false,
    assetsInlineLimit: 0,
    reportCompressedSize: false,
  },
  logLevel: "warn",
});

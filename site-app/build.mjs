#!/usr/bin/env node
// Build the homepage: render the React page to static HTML, then let Vite
// bundle the stylesheet and the client module around it.
//   node site-app/build.mjs --out build/published
import { readdir, rm, stat } from "node:fs/promises";
import { join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build } from "vite";

const here = fileURLToPath(new URL(".", import.meta.url));
const configFile = join(here, "vite.config.mjs");
const at = process.argv.indexOf("--out");
const out = resolve(at > 0 ? process.argv[at + 1] : join(here, "../build/site-app"));

// Inside the repository so the render bundle resolves react from node_modules.
const ssrDir = join(here, "../build/.site-app-ssr");
try {
  await build({ configFile, build: { ssr: "src/page.tsx", outDir: ssrDir, emptyOutDir: true } });
  const entry = (await readdir(ssrDir)).find((f) => /^page\.m?js$/.test(f));
  const { render } = await import(pathToFileURL(join(ssrDir, entry)).href);
  const markup = render();
  await build({
    configFile,
    plugins: [{
      name: "wisp-prerender",
      transformIndexHtml: (html) => {
        if (!html.includes("<!--app-->")) throw new Error("index.html lost its <!--app--> slot");
        return html.replace("<!--app-->", markup);
      },
    }],
    build: { outDir: out, emptyOutDir: false },
  });
} finally {
  await rm(ssrDir, { recursive: true, force: true });
}

// Report what a first visit downloads before the WebGL hero is requested.
const files = await readdir(join(out, "app"));
const size = async (name) => (await stat(join(out, "app", name))).size;
const js = files.filter((f) => f.endsWith(".js"));
const hero = js.filter((f) => f.startsWith("hero-"));
const first = js.filter((f) => !hero.includes(f));
const sum = async (list) => (await Promise.all(list.map(size))).reduce((a, b) => a + b, 0);
const css = await sum(files.filter((f) => f.endsWith(".css")));
console.log(`site-app built in ${out}: first-paint JS ${await sum(first)} B, `
  + `lazy hero JS ${await sum(hero)} B, CSS ${css} B`);

// Homepage (site-app/) against the local Worker: no page errors, no external
// requests, no horizontal scroll, working copy/theme/FAQ controls, and the
// static hero frame for reduced motion, no JavaScript, no WebGL, a failed
// hero module and a failing renderer.
import assert from "node:assert/strict";
import {mkdir} from "node:fs/promises";
import {chromium, webkit} from "playwright";

const base = process.env.WISP_SITE_URL || "http://127.0.0.1:3000/";
const engines = (process.env.WISP_BROWSERS || "chromium").split(",");
const output = process.env.WISP_QA_OUTPUT || "../../build/browser-qa";
await mkdir(output, {recursive: true});

const ready = page => page.waitForFunction(() =>
  document.querySelector("#hero-bg").dataset.ready === "true", null, {timeout: 15000});
const fit = async (page, label) => assert.equal(await page.evaluate(() =>
  document.documentElement.scrollWidth <= innerWidth), true, `${label}: horizontal scroll`);

for (const name of engines) {
  const browser = await ({chromium, webkit}[name]).launch({
    headless: true,
    // WISP_CHROMIUM_PATH: a local Chromium where Playwright ships none (e.g. Linux ARM64).
    ...(name === "chromium" ? (process.env.WISP_CHROMIUM_PATH
      ? {executablePath: process.env.WISP_CHROMIUM_PATH} : {channel: "chromium"}) : {}),
  });
  try {
    const context = await browser.newContext({viewport: {width: 1440, height: 900}});
    const page = await context.newPage();
    const uncaught = [], external = [];
    page.on("pageerror", error => uncaught.push(error.stack || error.message));
    page.on("request", request => {
      if (new URL(request.url()).origin !== new URL(base).origin) external.push(request.url());
    });
    await page.goto(base, {waitUntil: "networkidle"});
    await ready(page);
    // A mounted hero either draws its first frame or falls back to the static frame.
    await page.waitForFunction(() => {
      const bg = document.querySelector("#hero-bg");
      return bg.dataset.hero === "static" || bg.dataset.rendered === "true";
    });
    const hero = await page.locator("#hero-bg").getAttribute("data-hero");
    assert.ok(["webgl", "static"].includes(hero), hero);
    assert.equal(await page.locator("#hero-bg canvas").count(), hero === "webgl" ? 1 : 0);
    assert.equal(await page.locator("#flame img").isVisible(), true);
    assert.match(await page.locator("h1").innerText(), /A little more\s+reach\./);
    await fit(page, "1440x900");
    await page.screenshot({path: `${output}/${name}-desktop.png`});

    if (hero === "webgl") {
      // Context loss drops back to the static frame without errors.
      await page.locator("#hero-bg canvas").evaluate(canvas =>
        canvas.getContext("webgl").getExtension("WEBGL_lose_context").loseContext());
      await page.waitForFunction(() => document.querySelector("#hero-bg").dataset.hero === "static");
      assert.equal(await page.locator("#hero-bg canvas").count(), 0);
    }

    // Theme toggle: flips, and the choice survives a reload.
    const before = await page.evaluate(() => matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    await page.locator("#theme-toggle").click();
    const after = await page.evaluate(() => document.documentElement.dataset.theme);
    assert.equal(after, before === "dark" ? "light" : "dark");
    await page.reload({waitUntil: "networkidle"});
    assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), after);

    // FAQ is plain <details>.
    const first = page.locator("#faq details").first();
    await first.locator("summary").click();
    assert.equal(await first.evaluate(d => d.open), true);

    for (const [width, height] of [[390, 844], [320, 740], [1440, 540]]) {
      await page.setViewportSize({width, height});
      await page.goto(base, {waitUntil: "networkidle"});
      await ready(page);
      await fit(page, `${width}x${height}`);
      await page.screenshot({path: `${output}/${name}-${width}x${height}.png`});
    }

    await page.locator("#install").scrollIntoViewIfNeeded();
    await page.getByRole("button", {name: "Copy command"}).click();
    await page.waitForFunction(() => document.querySelector("#copy-status").textContent.length > 0);
    const copyResult = await page.locator("#copy-status").innerText();
    assert.match(copyResult, /Command copied|Clipboard unavailable/);
    await page.addInitScript(() => {
      Object.defineProperty(navigator, "clipboard", {value: {
        writeText: async () => { throw new Error("Permission denied"); },
      }});
    });
    await page.reload({waitUntil: "networkidle"});
    await page.locator("#copy-install").click();
    assert.match(await page.locator("#copy-status").innerText(), /Select and copy/);
    assert.deepEqual(uncaught, []);
    assert.deepEqual(external, []);
    await context.close();

    for (const mode of ["reduced", "no-js", "no-webgl", "module-failed", "render-failed"]) {
      const c = await browser.newContext({
        viewport: {width: 390, height: 844},
        javaScriptEnabled: mode !== "no-js",
        reducedMotion: mode === "reduced" ? "reduce" : "no-preference",
      });
      if (mode === "no-webgl") await c.addInitScript(() => {
        const original = HTMLCanvasElement.prototype.getContext;
        HTMLCanvasElement.prototype.getContext = function (type, ...args) {
          return String(type).startsWith("webgl") ? null : original.call(this, type, ...args);
        };
      });
      if (mode === "module-failed") await c.route("**/app/hero-*.js", route => route.abort());
      if (mode === "render-failed") await c.addInitScript(() => {
        const prototype = window.WebGLRenderingContext?.prototype;
        if (prototype) prototype.drawArrays = () => { throw new Error("Injected renderer failure"); };
      });
      const p = await c.newPage();
      const errors = [], outside = [];
      p.on("pageerror", error => errors.push(error.stack || error.message));
      p.on("request", request => {
        if (new URL(request.url()).origin !== new URL(base).origin) outside.push(request.url());
      });
      await p.goto(base, {waitUntil: "networkidle"});
      if (mode !== "no-js") await ready(p);
      assert.equal(await p.locator("#hero-bg").getAttribute("data-hero"), "static", mode);
      assert.equal(await p.locator("#hero-bg canvas").count(), 0, mode);
      assert.equal(await p.locator("#flame img").isVisible(), true, mode);
      assert.match(await p.locator("#flame img").evaluate(img => img.currentSrc),
        mode === "reduced" ? /wisp-flame-512\.png$/ : /idle-256\.webp$/, mode);
      if (mode === "no-js") {
        assert.equal(await p.locator("#copy-install").isDisabled(), true);
        assert.equal(await p.locator("#theme-toggle").isVisible(), false);
      }
      await fit(p, mode);
      assert.deepEqual(errors, [], mode);
      assert.deepEqual(outside, [], mode);
      await p.locator("#install").scrollIntoViewIfNeeded();
      assert.equal(await p.locator("#install-code").isVisible(), true, mode);
      await c.close();
    }
    console.log(JSON.stringify({browser: name, version: browser.version(), hero,
      fallbacks: "pass", clipboard: copyResult, externalRequests: external.length,
      pageErrors: uncaught.length}));
  } finally {
    await browser.close();
  }
}

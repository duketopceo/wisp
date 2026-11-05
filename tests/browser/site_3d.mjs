import assert from "node:assert/strict";
import {mkdir} from "node:fs/promises";
import {chromium, webkit} from "playwright";

const base = process.env.WISP_SITE_URL || "http://127.0.0.1:3000/site-3d/";
const engines = (process.env.WISP_BROWSERS || "chromium").split(",");
const output = process.env.WISP_QA_OUTPUT || "../../build/browser-qa";
await mkdir(output, {recursive: true});

for (const name of engines) {
  const browser = await ({chromium, webkit}[name]).launch({
    headless: true, ...(name === "chromium" ? {channel: "chromium"} : {}),
  });
  try {
    const context = await browser.newContext({viewport: {width: 1440, height: 900}});
    const page = await context.newPage();
    const uncaught = [], external = [];
    page.on("pageerror", error => uncaught.push(error.stack || error.message));
    page.on("request", request => {
      if (new URL(request.url()).origin !== new URL(base).origin) external.push(request.url());
    });
    const phase = wanted => page.waitForFunction(value =>
      document.querySelector("#demo-state").dataset.phase === value, wanted);
    const fit = async () => assert.equal(await page.evaluate(() =>
      document.documentElement.scrollWidth <= innerWidth), true);
    await page.goto(base, {waitUntil: "networkidle"});
    await page.waitForFunction(() =>
      ["webgl", "dom"].includes(document.querySelector("#scene").dataset.renderer));
    if (name === "chromium") {
      await page.waitForFunction(() => document.querySelector("#scene").dataset.renderer === "webgl"
        && document.querySelector("#scene").dataset.rendered === "true");
      assert.equal(await page.locator("#scene canvas").count(), 1);
      // The hero flame renders from the glTF in its own small canvas.
      await page.waitForFunction(() => document.querySelector("#flame").dataset.flame === "webgl"
        && document.querySelector("#flame").dataset.rendered === "true");
      assert.equal(await page.locator("#flame canvas").count(), 1);
      assert.equal(await page.locator("#flame img").isVisible(), false);
    }
    const renderer = await page.locator("#scene").getAttribute("data-renderer");
    await page.screenshot({path: `${output}/${name}-desktop.png`});
    await fit();
    await page.getByRole("button", {name: "“Check my email.”"}).click();
    await phase("done");
    await page.getByRole("button", {name: "“Open my work tasks.”"}).click();
    await phase("done");
    await page.getByRole("button", {name: "“Toggle playback.”"}).click();
    await phase("done");
    assert.match(await page.locator("#demo-state").innerText(), /still need inspection/);
    await page.getByRole("button", {name: "“Submit this payment.”"}).click();
    await phase("awaiting_choice");
    assert.match(await page.locator("#sensitive-rules").innerText(), /Raw live secret keys are refused/);
    assert.equal(await page.locator("#approve-demo").isVisible(), true);
    // Exercise approval from the keyboard, not by changing internal state.
    await page.locator("#approve-demo").focus();
    await page.keyboard.press("Enter");
    await phase("done");
    assert.equal(await page.evaluate(() => document.activeElement?.dataset.scenario), "sensitive");
    await page.getByRole("button", {name: "“Submit this payment.”"}).click();
    await page.getByRole("button", {name: "“Check my email.”"}).click();
    await page.locator("#cancel-demo").click();
    await phase("cancelled");
    await page.locator("#reset-demo").click();
    await phase("idle");
    assert.equal(await page.locator("#sensitive-rules").isVisible(), false);
    await page.locator("#pause-motion").click();
    await page.waitForFunction(() => document.querySelector("#scene").dataset.renderer === "dom");
    assert.equal(await page.locator("#scene canvas").count(), 0);
    await page.locator("#pause-motion").click();
    await page.waitForFunction(() =>
      ["webgl", "dom"].includes(document.querySelector("#scene").dataset.renderer));
    await page.emulateMedia({reducedMotion: "reduce"});
    await page.waitForFunction(() => document.querySelector("#scene").dataset.renderer === "dom");
    assert.equal(await page.locator("#scene canvas").count(), 0);
    // The playable DOM desktop replaces the WebGL scene; the image stays hidden.
    assert.equal(await page.locator("#desktop").isVisible(), true);
    assert.equal(await page.locator("#scene-fallback").isVisible(), false);
    // Reduced motion also stops the hero flame: the still, never a canvas.
    assert.equal(await page.locator("#flame canvas").count(), 0);
    assert.equal(await page.locator("#flame img").isVisible(), true);
    assert.match(await page.locator("#flame img").evaluate(img => img.currentSrc), /wisp-flame-512\.png$/);
    await page.emulateMedia({reducedMotion: "no-preference"});
    if (renderer === "webgl") {
      await page.waitForFunction(() => document.querySelector("#scene").dataset.renderer === "webgl");
      await page.locator("#scene canvas").evaluate(canvas => {
        const gl = canvas.getContext("webgl2") || canvas.getContext("webgl");
        const extension = gl.getExtension("WEBGL_lose_context");
        if (!extension) throw new Error("No context-loss extension available");
        extension.loseContext();
      });
      await page.waitForFunction(() => document.querySelector("#scene").dataset.renderer === "dom");
      assert.equal(await page.locator("#scene canvas").count(), 0);
      assert.equal(await page.locator("#desktop").isVisible(), true);
      assert.equal(await page.locator("#scene-fallback").isVisible(), false);
    }
    for (const [width, height] of [[390, 844], [320, 740], [1440, 540], [1440, 900]]) {
      await page.setViewportSize({width, height});
      await page.goto(base, {waitUntil: "networkidle"});
      await fit();
      if (width < 761) {
        await page.getByRole("button", {name: "“Submit this payment.”"}).click();
        await phase("awaiting_choice");
        const fitsStory = await page.evaluate(() =>
          document.querySelector(".workspace-story").getBoundingClientRect().height >=
          document.querySelector(".workspace-sticky").getBoundingClientRect().height);
        assert.equal(fitsStory, true, `${width}px confirmation content overlaps the next section`);
        await page.locator("#reset-demo").click();
      }
      await page.screenshot({path: `${output}/${name}-${width}x${height}.png`});
    }
    await page.locator("#install").scrollIntoViewIfNeeded();
    if (renderer === "webgl") {
      await page.waitForFunction(() => document.querySelector("#scene").dataset.rendering === "paused");
    }
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

    for (const mode of ["render-failed", "reduced", "no-js", "no-webgl", "module-failed"]) {
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
      if (mode === "module-failed") for (const module of ["scene", "flame"]) {
        await c.route(`**/${module}.mjs`, route => route.abort());
      }
      if (mode === "render-failed") await c.addInitScript(() => {
        for (const name of ["WebGL2RenderingContext", "WebGLRenderingContext"]) {
          const prototype = window[name]?.prototype;
          if (!prototype) continue;
          for (const method of ["drawElements", "drawArrays"]) {
            prototype[method] = () => {
              window.__wispDrawFailure = true;
              throw new Error("Injected renderer failure");
            };
          }
        }
      });
      const p = await c.newPage();
      const errors = [];
      p.on("pageerror", error => errors.push(error.stack || error.message));
      await p.goto(base, {waitUntil: "networkidle"});
      if (mode !== "no-js") await p.waitForFunction(() =>
        document.querySelector("#scene").dataset.renderer === "dom");
      // Without JavaScript the companion image is the illustration; with it,
      // the DOM desktop is playable and the image stays hidden.
      assert.equal(await p.locator("#scene-fallback").isVisible(), mode === "no-js");
      if (mode !== "no-js") assert.equal(await p.locator("#desktop").isVisible(), true);
      assert.equal(await p.locator("#scene canvas").count(), 0);
      // The flame falls back to its animated WebP (a still under reduced motion).
      if (mode === "render-failed" && name === "chromium") {
        await p.waitForFunction(() => window.__wispDrawFailure === true);
      }
      if (mode !== "no-js") await p.waitForFunction(() => {
        const flame = document.querySelector("#flame");
        return flame.dataset.flame === "static" && !flame.querySelector("canvas");
      });
      assert.equal(await p.locator("#flame canvas").count(), 0);
      assert.equal(await p.locator("#flame img").isVisible(), true);
      assert.match(await p.locator("#flame img").evaluate(img => img.currentSrc),
        mode === "reduced" ? /wisp-flame-512\.png$/ : /idle-256\.webp$/);
      if (mode === "render-failed" && name === "chromium") {
        assert.equal(await p.evaluate(() => window.__wispDrawFailure), true);
      }
      assert.deepEqual(errors, []);
      await p.locator("#install").scrollIntoViewIfNeeded();
      assert.equal(await p.locator("#install-code").isVisible(), true);
      await c.close();
    }
    console.log(JSON.stringify({browser: name, version: browser.version(), renderer,
      enhancedCoverage: renderer === "webgl" ? "rendered" : "unavailable; fallback only",
      scenarios: "pass", cancellation: "pass", approval: "pass", fallbacks: "pass",
      clipboard: copyResult, externalRequests: external.length, pageErrors: uncaught.length}));
  } finally {
    await browser.close();
  }
}

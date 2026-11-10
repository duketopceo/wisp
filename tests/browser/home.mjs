// Homepage (site-app/) against the local Worker: no page errors, no external
// requests, no horizontal scroll, working copy/theme/FAQ controls, a live
// Canvas 2D mark that leans toward the pointer and keeps the pop colour across
// themes, and the SVG still for reduced motion, no JavaScript, no canvas, a
// failed mark module and data saver.
import assert from "node:assert/strict";
import {mkdir} from "node:fs/promises";
import {chromium, webkit} from "playwright";

const base = process.env.WISP_SITE_URL || "http://127.0.0.1:3000/";
const baseOrigin = new URL(base).origin;
const engines = (process.env.WISP_BROWSERS || "chromium").split(",");
const output = process.env.WISP_QA_OUTPUT || "../../build/browser-qa";
await mkdir(output, {recursive: true});

const POP = [255, 91, 31];
const ground = {dark: "rgb(21, 17, 14)", light: "rgb(242, 236, 224)"};
const ready = page => page.waitForFunction(() =>
  document.querySelector("#hero-mark").dataset.ready === "true", null, {timeout: 15000});
const ribbonReady = page => page.waitForFunction(() =>
  document.querySelector("#hero-bg").dataset.ready === "true", null, {timeout: 15000});
const live = page => page.waitForFunction(() =>
  document.querySelector("#hero-mark").dataset.mark === "live", null, {timeout: 15000});
// Opaque pixels of the live canvas: how many are the pop colour, and their mean x in CSS px.
const inspectCanvas = page => page.locator("#hero-mark canvas").evaluate(canvas => {
  const {width, height} = canvas;
  const data = canvas.getContext("2d").getImageData(0, 0, width, height).data;
  let pop = 0, sx = 0, count = 0, minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (let i = 0; i < data.length; i += 4) {
    if (data[i + 3] === 0) continue; // the glow counts toward the extent, not the mean
    const px = (i / 4) % width, py = Math.floor(i / 4 / width);
    minX = Math.min(minX, px); maxX = Math.max(maxX, px); minY = Math.min(minY, py); maxY = Math.max(maxY, py);
    if (data[i + 3] < 250) continue;
    count++;
    sx += px;
    if (Math.abs(data[i] - 255) < 3 && Math.abs(data[i + 1] - 91) < 3 && Math.abs(data[i + 2] - 31) < 3) pop++;
  }
  const k = canvas.clientWidth / width;
  return {pop, x: count ? sx / count * k : null, extent: {minX: minX * k, maxX: (maxX + 1) * k, minY: minY * k, maxY: (maxY + 1) * k},
    size: {w: canvas.clientWidth, h: canvas.clientHeight}};
});
// WCAG contrast of what the browser really computed: body text, muted text and the CTA label.
const contrast = page => page.evaluate(() => {
  const px = css => {
    const c = document.createElement("canvas").getContext("2d", {willReadFrequently: true});
    c.fillStyle = css;
    c.fillRect(0, 0, 1, 1);
    return [...c.getImageData(0, 0, 1, 1).data.slice(0, 3)];
  };
  const lum = ([r, g, b]) => [r, g, b].map(v => v / 255).map(v => v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)
    .reduce((acc, v, i) => acc + v * [0.2126, 0.7152, 0.0722][i], 0);
  const ratio = (a, b) => { const [hi, lo] = [lum(px(a)), lum(px(b))].sort((x, y) => y - x); return (hi + 0.05) / (lo + 0.05); };
  const color = el => getComputedStyle(el).color;
  const bg = getComputedStyle(document.body).backgroundColor;
  const cta = [...document.querySelectorAll("a")].find(a => a.textContent.includes("Install on Omarchy"));
  return {
    body: ratio(color(document.querySelector("h1")), bg),
    muted: ratio(color(document.querySelector("#hero-title ~ p")), bg),
    cta: ratio(color(cta), getComputedStyle(cta).backgroundColor),
  };
});
const stageBox = page => page.locator("#hero-mark").boundingBox();
const fit = async (page, label) => assert.equal(await page.evaluate(() =>
  document.documentElement.scrollWidth <= innerWidth), true, `${label}: horizontal scroll`);
const readTheme = page => page.evaluate(() => document.documentElement.dataset.theme
  || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
const trackExternalRequests = page => {
  const outside = [];
  page.on("request", request => {
    if (new URL(request.url()).origin !== baseOrigin) outside.push(request.url());
  });
  return outside;
};
const returnToTop = page => page.evaluate(() => {
  const root = document.documentElement;
  const behavior = root.style.scrollBehavior;
  root.style.scrollBehavior = "auto";
  scrollTo(0, 0);
  root.style.scrollBehavior = behavior;
});

// main.ts keeps the still on hosts reporting <= 2 cores or <= 2 GB, which a small CI
// runner can: pin a capable host wherever the test expects a live comet.
const hardware = ([cores, memory]) => {
  Object.defineProperty(navigator, "hardwareConcurrency", {value: cores, configurable: true});
  Object.defineProperty(navigator, "deviceMemory", {value: memory, configurable: true});
};

for (const name of engines) {
  const browser = await ({chromium, webkit}[name]).launch({
    headless: true,
    // WISP_CHROMIUM_PATH: a local Chromium where Playwright ships none (e.g. Linux ARM64).
    ...(name === "chromium" ? (process.env.WISP_CHROMIUM_PATH
      ? {executablePath: process.env.WISP_CHROMIUM_PATH} : {channel: "chromium"}) : {}),
  });
  try {
    const context = await browser.newContext({viewport: {width: 1440, height: 900}});
    await context.addInitScript(hardware, [8, 8]);
    const page = await context.newPage();
    const uncaught = [];
    const external = trackExternalRequests(page);
    page.on("pageerror", error => uncaught.push(error.stack || error.message));
    await page.goto(base, {waitUntil: "networkidle"});
    await ready(page);
    // The still stays until the canvas has drawn its first frame.
    await live(page);
    const initialTheme = await readTheme(page);
    assert.equal(await page.locator("#hero-mark canvas").count(), 1);
    assert.equal(await page.locator("#hero-mark svg").isVisible(), false, "the still hides once live");
    // The ribbon field is WebGL: a runner without it (or with only a slow software
    // renderer) keeps the CSS frame, so either end state is valid, never a broken one.
    await ribbonReady(page);
    const ribbon = await page.locator("#hero-bg").getAttribute("data-hero");
    assert.ok(["webgl", "static"].includes(ribbon), `ribbon state ${ribbon}`);
    assert.equal(await page.locator("#hero-bg canvas").count(), ribbon === "webgl" ? 1 : 0);
    assert.match(await page.locator("h1").innerText(), /A little more\s+reach\./);
    await fit(page, `1440x900-${initialTheme}`);
    await page.screenshot({path: `${output}/${name}-desktop-${initialTheme}.png`});

    const navInstall = page.getByRole("link", {name: "Install", exact: true});
    const heroInstall = page.getByRole("link", {name: "Install on Omarchy"});
    const heroBox = await heroInstall.boundingBox();
    assert.ok(heroBox, "the hero install CTA is visible");
    await page.mouse.move(heroBox.x + heroBox.width / 2, heroBox.y + heroBox.height / 2);
    await page.mouse.down();
    assert.notEqual(await heroInstall.evaluate(el => getComputedStyle(el).scale), "none",
      "a pressed CTA responds immediately");
    await page.mouse.up();
    await page.mouse.move(720, 4); // off the CTA, so it is measured at rest

    const navRest = await navInstall.evaluate(el => getComputedStyle(el).backgroundImage);
    const heroRest = await heroInstall.evaluate(el => getComputedStyle(el).backgroundImage);
    assert.equal(navRest, "none", "the sticky Install link is secondary");
    assert.equal(heroRest, "none", "the hero CTA is a flat fill");
    assert.equal(await heroInstall.evaluate(el => getComputedStyle(el).backgroundColor), "rgb(255, 91, 31)",
      "the hero CTA is the primary action in the pop colour");
    assert.equal(await navInstall.evaluate(el => getComputedStyle(el).transitionDuration), "0s",
      "hover feedback is immediate");
    const navBaseColor = await navInstall.evaluate(el => getComputedStyle(el).backgroundColor);
    await navInstall.hover();
    const navHoverColor = await navInstall.evaluate(el => getComputedStyle(el).backgroundColor);
    assert.notEqual(navHoverColor, navBaseColor, "the actionable nav link has a hover state");
    const passiveCard = page.locator("#what .glass-2").first();
    await passiveCard.hover();
    assert.equal(await passiveCard.evaluate(el => getComputedStyle(el).transform), "none",
      "a passive feature card does not look clickable");

    await page.keyboard.press("Tab");
    assert.equal(await page.evaluate(() => document.activeElement.matches(":focus-visible")), true,
      "keyboard focus uses the visible focus treatment");
    assert.notEqual(await page.evaluate(() => getComputedStyle(document.activeElement).outlineStyle), "none");

    // The comet leans toward the pointer while it hovers the stage, and stays inside it.
    // The drift swings about +-55 px over a ~9 s period, so each side is sampled for
    // one period; the lean (~100 px between the two edges) then shows in the mean.
    await returnToTop(page);
    await page.waitForFunction(() => scrollY === 0);
    const stage = await stageBox(page);
    assert.ok(stage, "the stage is laid out");
    const meanX = async edge => {
      await page.mouse.move(edge === "left" ? stage.x + 6 : stage.x + stage.width - 6, stage.y + stage.height / 2);
      await page.waitForTimeout(1200);
      const xs = [];
      let drawn = 0;
      for (let i = 0; i < 8; i++) {
        const {pop, x, extent, size} = await inspectCanvas(page);
        drawn += pop;
        xs.push(x);
        assert.ok(extent.minX > 2 && extent.maxX < size.w - 2 && extent.minY > 2 && extent.maxY < size.h - 2,
          `the comet and its glow stay inside the stage ${JSON.stringify(extent)} in ${size.w}x${size.h}`);
        await page.waitForTimeout(1100);
      }
      assert.ok(drawn > 0, "the comet is drawn in the pop colour");
      return xs.reduce((a, b) => a + b, 0) / xs.length;
    };
    const leftMean = await meanX("left");
    const rightMean = await meanX("right");
    assert.ok(rightMean - leftMean > 40, `the comet leans with the pointer (${leftMean} -> ${rightMean})`);
    await page.mouse.move(1400, 890);

    const firstContrast = await contrast(page);
    // Theme toggle: flips, and the choice survives a reload.
    const before = initialTheme;
    await page.locator("#theme-toggle").click();
    const after = await readTheme(page);
    assert.equal(after, before === "dark" ? "light" : "dark");
    // Recolour: the ground flips, the comet keeps the one pop colour.
    assert.equal(await page.evaluate(() => getComputedStyle(document.body).backgroundColor), ground[after]);
    assert.ok((await inspectCanvas(page)).pop > 0, "the comet is still the pop colour after a theme change");
    for (const [theme, ratios] of [[before, firstContrast], [after, await contrast(page)]])
      for (const [what, value] of Object.entries(ratios)) assert.ok(value >= 4.5, `${theme} ${what} contrast ${value}`);
    await page.reload({waitUntil: "networkidle"});
    assert.equal(await readTheme(page), after);
    await returnToTop(page);
    await page.waitForFunction(() => window.scrollY === 0);
    await page.mouse.move(1400, 890);
    await page.screenshot({path: `${output}/${name}-desktop-${after}.png`});

    // FAQ is plain <details>.
    const first = page.locator("#faq details").first();
    await first.locator("summary").click();
    assert.equal(await first.evaluate(d => d.open), true);

    for (const [width, height] of [[320, 740], [1440, 540]]) {
      await page.setViewportSize({width, height});
      await fit(page, `${width}x${height}`);
      await page.screenshot({path: `${output}/${name}-${width}x${height}.png`});
    }

    await page.setViewportSize({width: 390, height: 844});
    await page.goto(base, {waitUntil: "networkidle"});
    await ready(page);
    await live(page);
    const liveBox = await stageBox(page);
    await fit(page, `390x844-${after}`);
    await page.mouse.move(380, 830);
    const mobileTheme = await readTheme(page);
    await page.screenshot({path: `${output}/${name}-390-${mobileTheme}.png`});
    await page.locator("#theme-toggle").click();
    await page.evaluate(() => new Promise(requestAnimationFrame));
    const alternateMobileTheme = await readTheme(page);
    await fit(page, `390x844-${alternateMobileTheme}`);
    await page.mouse.move(380, 830);
    await page.screenshot({path: `${output}/${name}-390-${alternateMobileTheme}.png`});

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

    // A stage that is never on screen never runs the sim: the still stays.
    {
      const c = await browser.newContext({viewport: {width: 390, height: 844}});
      await c.addInitScript(hardware, [8, 8]);
      const p = await c.newPage();
      const errors = [];
      p.on("pageerror", error => errors.push(error.stack || error.message));
      await p.goto(`${base}#faq`, {waitUntil: "networkidle"});
      await p.waitForFunction(() => scrollY > 1000);
      await p.reload({waitUntil: "networkidle"}); // restored scroll: the stage is never in view
      await ready(p);
      await p.waitForTimeout(800);
      assert.equal(await p.locator("#hero-mark").getAttribute("data-mark"), "still", "off-screen stage stays still");
      await returnToTop(p);
      await live(p);
      assert.deepEqual(errors, []);
      await c.close();
    }

    for (const mode of ["reduced", "no-js", "no-canvas", "module-failed", "data-saver", "low-power", "draw-failed"]) {
      const c = await browser.newContext({
        viewport: {width: 390, height: 844},
        javaScriptEnabled: mode !== "no-js",
        reducedMotion: mode === "reduced" ? "reduce" : "no-preference",
      });
      await c.addInitScript(hardware, mode === "low-power" ? [2, 8] : [8, 8]);
      if (mode === "no-canvas") await c.addInitScript(() => {
        const original = HTMLCanvasElement.prototype.getContext;
        HTMLCanvasElement.prototype.getContext = function (type, ...args) {
          return type === "2d" ? null : original.call(this, type, ...args);
        };
      });
      // The canvas works at mount, then a later draw throws: the still must come back.
      if (mode === "draw-failed") await c.addInitScript(() => {
        const original = CanvasRenderingContext2D.prototype.createRadialGradient;
        let calls = 0;
        CanvasRenderingContext2D.prototype.createRadialGradient = function (...args) {
          if (++calls > 2) throw new Error("draw failed");
          return original.apply(this, args);
        };
      });
      if (mode === "data-saver") await c.addInitScript(() => {
        Object.defineProperty(navigator, "connection", {value: {saveData: true}});
      });
      if (mode === "module-failed") await c.route("**/app/mark-*.js", route => route.abort());
      const p = await c.newPage();
      const errors = [];
      const outside = trackExternalRequests(p);
      p.on("pageerror", error => errors.push(error.stack || error.message));
      await p.goto(base, {waitUntil: "networkidle"});
      if (mode !== "no-js") await ready(p);
      if (mode === "draw-failed") await p.waitForTimeout(1500); // first frame draws, a later one throws
      assert.equal(await p.locator("#hero-mark").getAttribute("data-mark"), "still", mode);
      assert.equal(await p.locator("#hero-mark canvas").count(), 0, mode);
      assert.equal(await p.locator("#hero-mark svg").isVisible(), true, mode);
      assert.deepEqual(await stageBox(p), liveBox, `${mode}: the still has the live stage's box`);
      if (["no-js", "data-saver", "low-power"].includes(mode))
        assert.equal(await p.locator("#hero-bg canvas").count(), 0, `${mode}: no ribbon canvas`);
      if (mode === "no-js") {
        assert.equal(await p.locator("#copy-install").isDisabled(), true);
        assert.equal(await p.locator("#theme-toggle").isVisible(), false);
      }
      await fit(p, mode);
      assert.deepEqual(errors, [], mode);
      assert.deepEqual(outside, [], mode);
      if (mode === "reduced") await p.screenshot({path: `${output}/${name}-390-reduced.png`});
      await p.locator("#install").scrollIntoViewIfNeeded();
      assert.equal(await p.locator("#install-code").isVisible(), true, mode);
      await c.close();
    }
    console.log(JSON.stringify({browser: name, version: browser.version(),
      fallbacks: "pass", clipboard: copyResult, externalRequests: external.length,
      pageErrors: uncaught.length}));
  } finally {
    await browser.close();
  }
}

// Wisp browser lane: an original MV3 service worker. It does nothing until
// the user pairs it with a one-time code from Wisp, talks only to the
// loopback socket Wisp serves (127.0.0.1), works in one tab group per task,
// and stops the moment the popup's Stop button is pressed.
importScripts("lib.js");

var DEFAULT_PORT = 47315;
var LANE = {
  port: DEFAULT_PORT,
  token: "",
  polling: false,
  stopped: false,
  abort: null,
  epoch: new WispLane.Epoch(),
  groups: {},        // task id -> tab group id
  tabs: {},          // task id -> tab ids Wisp opened
  kept: {},          // tab id -> true when the user asked to keep it
  current: {}        // task id -> the tab steps act on by default
};

function base() { return "http://127.0.0.1:" + LANE.port; }
function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

function api(method, path, body, signal) {
  return fetch(base() + path, {
    method: method,
    headers: { "Content-Type": "application/json", "X-Wisp-Token": LANE.token },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: signal
  }).then(function (r) {
    if (r.status === 401 || r.status === 403) { var e = new Error("auth"); e.status = r.status; throw e; }
    return r.status === 204 ? {} : r.json();
  });
}

// -- pairing and the poll loop -----------------------------------------

async function pair(code, port) {
  LANE.port = port > 0 && port < 65536 ? port : DEFAULT_PORT;
  try {
    var r = await fetch(base() + "/pair", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code: code })
    });
    var j = await r.json();
    if (!r.ok || !j.token) return { message: "Pairing refused: " + (j.error || r.status) };
    LANE.token = j.token;
    LANE.stopped = false;
    poll();
    return { message: "Paired. Wisp works in a tab group named Wisp." };
  } catch (e) {
    return { message: "Wisp is not reachable on port " + LANE.port + ". Is [browser] lane = \"extension\"?" };
  }
}

async function poll() {
  if (LANE.polling) return;
  LANE.polling = true;
  while (LANE.token) {
    try {
      await chrome.runtime.getPlatformInfo();      // keeps the worker awake
      LANE.abort = new AbortController();
      var r = await api("POST", "/poll", { wait: 20 }, LANE.abort.signal);
      if (r && r.cmd) {
        var res = await execute(r.cmd);
        res.id = r.cmd.id;
        await api("POST", "/result", res);
      }
    } catch (e) {
      if (e && e.status) { LANE.token = ""; break; }       // unpaired by Wisp
      if (e && e.name === "AbortError") continue;
      await sleep(1500);
    }
  }
  LANE.polling = false;
}

async function stop() {
  LANE.stopped = true;
  if (LANE.abort) LANE.abort.abort();
  var tasks = Object.keys(LANE.groups);
  for (var i = 0; i < tasks.length; i++) await endTask(tasks[i]);
  if (LANE.token) { try { await api("POST", "/stop", {}); } catch (e) { /* Wisp is gone: nothing to tell */ } }
  return { message: "Stopped. Wisp's tabs are closed; tabs you kept stay." };
}

chrome.runtime.onMessage.addListener(function (msg, _sender, reply) {
  var work = msg.type === "pair" ? pair(String(msg.code || ""), Number(msg.port))
    : msg.type === "stop" ? stop()
    : Promise.resolve({ message: LANE.token ? (LANE.stopped ? "Stopped." : "Paired.") : "Not paired." });
  work.then(reply);
  return true;
});

// -- tab group ------------------------------------------------------------

async function ensureGroup(task, tabId) {
  var groupId = LANE.groups[task];
  var id = await chrome.tabs.group(groupId === undefined
    ? { tabIds: [tabId] } : { tabIds: [tabId], groupId: groupId });
  if (groupId === undefined) {
    LANE.groups[task] = id;
    await chrome.tabGroups.update(id, { title: "Wisp", color: "purple", collapsed: false });
  }
  return id;
}

async function endTask(task) {
  var ids = (LANE.tabs[task] || []).filter(function (t) { return !LANE.kept[t]; });
  for (var i = 0; i < ids.length; i++) { try { await chrome.tabs.remove(ids[i]); } catch (e) { /* already closed */ } }
  delete LANE.groups[task]; delete LANE.tabs[task]; delete LANE.current[task];
}

function waitLoaded(tabId, ms) {
  return new Promise(function (resolve) {
    var done = false;
    function fin() { if (!done) { done = true; chrome.tabs.onUpdated.removeListener(on); resolve(); } }
    function on(id, info) { if (id === tabId && info.status === "complete") fin(); }
    chrome.tabs.onUpdated.addListener(on);
    setTimeout(fin, ms);
    chrome.tabs.get(tabId).then(function (t) { if (t.status === "complete") fin(); });
  });
}

// -- page functions: run inside the page, so they carry their own copy of
// the field rule (the patterns are passed in from lib.js) ----------------

function pageSnapshot(epoch, rule) {
  function sensitive(f) {
    if (rule.types.indexOf(String(f.type || "").toLowerCase()) >= 0) return true;
    if (new RegExp(rule.autocomplete, "i").test(String(f.autocomplete || ""))) return true;
    return new RegExp(rule.hint, "i").test([f.name, f.id, f.label, f.placeholder, f.ariaLabel].join(" "));
  }
  var sel = "a[href],button,input,select,textarea,summary,[role=button],[role=link],[role=checkbox],[role=tab],[role=menuitem],[contenteditable=''],[contenteditable='true']";
  var els = [], out = [];
  var nodes = document.querySelectorAll(sel);
  for (var i = 0; i < nodes.length && els.length < 150; i++) {
    var el = nodes[i], r = el.getBoundingClientRect(), s = getComputedStyle(el);
    if (r.width <= 0 || r.height <= 0 || s.visibility === "hidden" || s.display === "none") continue;
    var lab = el.getAttribute("aria-label") || (el.labels && el.labels[0] && el.labels[0].innerText) ||
      el.getAttribute("placeholder") || el.innerText || el.value || el.getAttribute("title") || "";
    lab = String(lab).replace(/\s+/g, " ").trim().slice(0, 80);
    var editable = /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable;
    var f = { type: el.getAttribute("type") || "", autocomplete: el.getAttribute("autocomplete") || "",
      name: el.getAttribute("name") || "", id: el.id || "", label: lab,
      placeholder: el.getAttribute("placeholder") || "", ariaLabel: el.getAttribute("aria-label") || "" };
    var sens = editable && sensitive(f);
    els.push(el);
    out.push({ ref: epoch + ":" + (els.length - 1), tag: el.tagName.toLowerCase(), type: f.type,
      name: lab, sensitive: sens, value: editable && !sens && el.value ? String(el.value).slice(0, 80) : "" });
  }
  window.__wisp = { epoch: epoch, els: els };
  return { epoch: epoch, url: location.href, title: document.title, elements: out,
    text: (document.body ? document.body.innerText : "").replace(/\s+/g, " ").slice(0, 3000) };
}

function pageAct(epoch, index, action, value, rule) {
  var w = window.__wisp;
  if (!w || w.epoch !== epoch) return { ok: false, error: "stale ref (snapshot again)" };
  var el = w.els[index];
  if (!el || !el.isConnected) return { ok: false, error: "that element is gone (snapshot again)" };
  el.scrollIntoView({ block: "center" });
  if (action === "click") { el.click(); return { ok: true }; }
  var f = { type: el.getAttribute("type") || "", autocomplete: el.getAttribute("autocomplete") || "",
    name: el.getAttribute("name") || "", id: el.id || "",
    label: (el.labels && el.labels[0] && el.labels[0].innerText) || "",
    placeholder: el.getAttribute("placeholder") || "", ariaLabel: el.getAttribute("aria-label") || "" };
  var bad = rule.types.indexOf(f.type.toLowerCase()) >= 0 ||
    new RegExp(rule.autocomplete, "i").test(f.autocomplete) ||
    new RegExp(rule.hint, "i").test([f.name, f.id, f.label, f.placeholder, f.ariaLabel].join(" "));
  if (bad) return { ok: false, error: "refused: password, one-time code and card fields are never filled" };
  el.focus();
  if (el.isContentEditable) { el.textContent = value; }
  else {
    var proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype
      : el.tagName === "SELECT" ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    var set = Object.getOwnPropertyDescriptor(proto, "value");
    if (set && set.set) set.set.call(el, value); else el.value = value;
  }
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
  return { ok: true };
}

function pageWait(text, selector) {
  if (selector && document.querySelector(selector)) return true;
  return !!text && !!document.body && document.body.innerText.indexOf(text) >= 0;
}

function pageScroll(dy) {
  window.scrollBy(0, dy);
  return { y: Math.round(window.scrollY) };
}

function rule() {
  return { types: WispLane.SENSITIVE_TYPES, autocomplete: WispLane.SENSITIVE_AUTOCOMPLETE, hint: WispLane.SENSITIVE_HINT };
}

// -- steps -----------------------------------------------------------------

function tabOf(task, step) {
  var id = step.tab !== undefined ? Number(step.tab) : LANE.current[task];
  if (!id) throw new Error("no tab yet: open a page first");
  if ((LANE.tabs[task] || []).indexOf(id) < 0) throw new Error("tab " + id + " is not one of Wisp's tabs");
  return id;
}

async function runStep(task, step) {
  var op = String(step["do"] || "");
  if (op === "open") {
    if (!WispLane.safeUrl(step.url)) throw new Error("only http and https pages can be opened");
    var tab = await chrome.tabs.create({ url: step.url, active: true });
    LANE.tabs[task] = (LANE.tabs[task] || []).concat([tab.id]);
    LANE.current[task] = tab.id;
    await ensureGroup(task, tab.id);
    await waitLoaded(tab.id, 15000);
    return { tab: tab.id };
  }
  if (op === "snapshot") {
    var id = tabOf(task, step);
    var epoch = LANE.epoch.next();
    var r = await chrome.scripting.executeScript({ target: { tabId: id }, func: pageSnapshot, args: [epoch, rule()] });
    var snap = r[0].result;
    snap.tab = id;
    return snap;
  }
  if (op === "click" || op === "fill") {
    var p = LANE.epoch.parse(step.ref);
    if (!p.ok) throw new Error(p.error);
    var tid = tabOf(task, step);
    var a = await chrome.scripting.executeScript({ target: { tabId: tid }, func: pageAct,
      args: [p.epoch, p.index, op, String(step.value === undefined ? "" : step.value), rule()] });
    if (!a[0].result.ok) throw new Error(a[0].result.error);
    if (op === "click") await waitLoaded(tid, 1500);
    return {};
  }
  if (op === "scroll") {
    var sid = tabOf(task, step);
    var sr = await chrome.scripting.executeScript({ target: { tabId: sid }, func: pageScroll, args: [Number(step.dy) || 400] });
    return sr[0].result;
  }
  if (op === "wait_for") {
    var wid = tabOf(task, step);
    var limit = Math.min(Number(step.timeout_ms) || 5000, WispLane.WAIT_MAX_MS);
    var t0 = Date.now();
    while (Date.now() - t0 < limit) {
      if (LANE.stopped) throw new Error("stopped");
      var w = await chrome.scripting.executeScript({ target: { tabId: wid }, func: pageWait,
        args: [String(step.text || ""), String(step.selector || "")] });
      if (w[0].result) return { waited_ms: Date.now() - t0 };
      await sleep(250);
    }
    throw new Error("wait_for timed out");
  }
  if (op === "screenshot") {
    var shot = tabOf(task, step);
    var tb = await chrome.tabs.update(shot, { active: true });
    var data = await chrome.tabs.captureVisibleTab(tb.windowId, { format: "png" });
    return { png: data.replace(/^data:image\/png;base64,/, "") };
  }
  if (op === "keep") {
    var kid = tabOf(task, step);
    LANE.kept[kid] = true;
    await chrome.tabs.ungroup([kid]);
    return {};
  }
  if (op === "done") { await endTask(task); return {}; }
  throw new Error("unknown step " + op);
}

async function execute(cmd) {
  if (cmd.resume) LANE.stopped = false;     // a new turn after a Stop
  if (cmd.op === "end_task") { await endTask(String(cmd.task || "")); return { ok: true, results: [] }; }
  if (cmd.op !== "batch") return { ok: false, error: "unknown command" };
  var why = WispLane.checkSteps(cmd.steps);
  if (why) return { ok: false, error: why };
  var task = String(cmd.task || "task");
  var results = [];
  for (var i = 0; i < cmd.steps.length; i++) {
    if (LANE.stopped) return { ok: false, error: "stopped", results: results };
    try { results.push(Object.assign({ ok: true }, await runStep(task, cmd.steps[i]))); }
    catch (e) { results.push({ ok: false, error: String(e.message || e) }); return { ok: false, error: results[i].error, results: results }; }
  }
  return { ok: true, results: results };
}

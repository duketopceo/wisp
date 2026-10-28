// Pure helpers for the Wisp browser lane. No chrome.* calls in here: the
// service worker loads this with importScripts(), and tests/test_browser_lane.py
// runs it under node. The field rule mirrors wisp/cua_safety.sensitive_field;
// a test runs both over one fixture list.
var WispLane = (function () {
  "use strict";

  var MAX_STEPS = 20;
  var WAIT_MAX_MS = 15000;

  // fields Wisp reads but never fills: passwords, one-time codes, cards
  var SENSITIVE_TYPES = ["password"];
  var SENSITIVE_AUTOCOMPLETE = "(?:^|\\s)(?:one-time-code|current-password|new-password|cc-[a-z-]+)(?:\\s|$)";
  var SENSITIVE_HINT = "(?:pass(?:word|code|phrase)|\\bpin\\b|one[\\s_-]?time|\\botp\\b|\\b2fa\\b|" +
    "\\bmfa\\b|verification[\\s_-]?code|security[\\s_-]?code|auth(?:entication)?" +
    "[\\s_-]?code|\\bcvv\\b|\\bcvc\\b|card[\\s_-]?(?:number|no)|credit[\\s_-]?card|" +
    "\\bcc[\\s_-]?num)";

  function str(v) { return v === undefined || v === null ? "" : String(v); }

  function isSensitiveField(f) {
    f = f || {};
    if (SENSITIVE_TYPES.indexOf(str(f.type).trim().toLowerCase()) >= 0) return true;
    if (new RegExp(SENSITIVE_AUTOCOMPLETE, "i").test(str(f.autocomplete))) return true;
    var hint = [f.name, f.id, f.label, f.placeholder, f.ariaLabel].map(str).join(" ");
    return new RegExp(SENSITIVE_HINT, "i").test(hint);
  }

  // only plain web pages: never file:, chrome:, javascript:, data:, blob:
  function safeUrl(u) {
    try {
      var p = new URL(str(u));
      return p.protocol === "http:" || p.protocol === "https:";
    } catch (e) { return false; }
  }

  // refs are "<epoch>:<index>"; a snapshot starts a new epoch and
  // every ref from an older one is refused
  function Epoch() { this.n = 0; }
  Epoch.prototype.next = function () { this.n += 1; return this.n; };
  Epoch.prototype.ref = function (index) { return this.n + ":" + index; };
  Epoch.prototype.parse = function (ref) {
    var m = /^(\d+):(\d+)$/.exec(str(ref).trim());
    if (!m) return { ok: false, error: "bad ref (expected epoch:index from the last snapshot)" };
    if (Number(m[1]) !== this.n) {
      return { ok: false, error: "stale ref " + ref + " (snapshot again; now at epoch " + this.n + ")" };
    }
    return { ok: true, epoch: Number(m[1]), index: Number(m[2]) };
  };

  function checkSteps(steps) {
    if (!Array.isArray(steps) || steps.length === 0) return "no steps";
    if (steps.length > MAX_STEPS) return "too many steps (" + steps.length + ", most is " + MAX_STEPS + ")";
    return "";
  }

  return {
    MAX_STEPS: MAX_STEPS, WAIT_MAX_MS: WAIT_MAX_MS,
    SENSITIVE_TYPES: SENSITIVE_TYPES, SENSITIVE_AUTOCOMPLETE: SENSITIVE_AUTOCOMPLETE,
    SENSITIVE_HINT: SENSITIVE_HINT,
    isSensitiveField: isSensitiveField, safeUrl: safeUrl, Epoch: Epoch, checkSteps: checkSteps
  };
})();
if (typeof module !== "undefined") module.exports = WispLane;

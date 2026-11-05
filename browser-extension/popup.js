// Popup: pair with a one-time code, or stop. All work happens in
// background.js; this only sends it messages and shows the answer.
function $(id) { return document.getElementById(id); }
function show(r) { $("status").textContent = (r && r.message) || "No answer from the extension."; }
function ask(msg) { chrome.runtime.sendMessage(msg, show); }

$("pair").addEventListener("click", function () {
  ask({ type: "pair", code: $("code").value.trim(), port: Number($("port").value) });
});
$("stop").addEventListener("click", function () { ask({ type: "stop" }); });
ask({ type: "status" });

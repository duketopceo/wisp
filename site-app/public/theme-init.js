// Applies a saved light/dark choice before first paint (no inline script: CSP).
try {
  var t = localStorage.getItem("wisp-theme");
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
} catch (e) {}

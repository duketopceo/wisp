// Applies a saved light/dark choice before first paint (no inline script: CSP).
try {
  var t = localStorage.getItem("wisp-theme");
  if (t === "light" || t === "dark") {
    document.documentElement.dataset.theme = t;
    var m = document.createElement("meta");
    m.name = "theme-color";
    m.setAttribute("data-wisp-chrome", "");
    m.content = t === "dark" ? "#15110E" : "#F2ECE0";
    document.head.insertBefore(m, document.head.firstChild);
  }
} catch (e) {}

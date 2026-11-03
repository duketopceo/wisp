// Small functions injected into the page. Each stands alone.

export function pageWait(text: string, selector: string): boolean {
  if (selector && document.querySelector(selector)) return true;
  return !!text && !!document.body && document.body.innerText.indexOf(text) >= 0;
}

export function pageScroll(dy: number): { y: number } {
  window.scrollBy(0, dy);
  return { y: Math.round(window.scrollY) };
}

"""Transform a Webpage-HTML-Export page into a graph-only landing.

Takes `jessica-j-walsh.html` (or any exported page; argv[1] overrides), strips
the sidebar/document/outline UI via injected CSS, and triggers the global-graph
view on load via injected JS. Writes the result to `index.html`.

Run after every re-export:
    python make_landing.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
SOURCE = REPO / (sys.argv[1] if len(sys.argv) > 1 else "jessica-j-walsh.html")
DEST = REPO / "index.html"

INJECT_CSS = """
<style id="landing-graph-only">
  html, body { overflow: hidden !important; }
  #navbar, #left-content, #center-content { display: none !important; }
  #main-horizontal { width: 100vw !important; }
  #right-content {
    flex: 1 1 100% !important;
    max-width: 100% !important;
    width: 100% !important;
  }
  #right-sidebar {
    min-width: 100% !important;
    max-width: 100% !important;
    width: 100% !important;
  }
  #right-sidebar .sidebar-topbar,
  #right-sidebar .sidebar-handle { display: none !important; }
  #right-sidebar-content {
    padding: 0 !important;
    padding-top: 0 !important;
    width: 100% !important;
    max-width: 100% !important;
    height: 100vh !important;
    border-radius: 0 !important;
  }
  /* Inside the right sidebar, keep only the graph wrapper. */
  #right-sidebar-content > *:not(.graph-view-wrapper) { display: none !important; }
  .graph-view-wrapper,
  .graph-view-container {
    width: 100% !important;
    height: 100vh !important;
    max-width: none !important;
    border-radius: 0 !important;
    margin: 0 !important;
  }
  .feature-title { display: none !important; }

  /* Subtle floating "← full wiki view" link in the corner. */
  #landing-escape {
    position: fixed; top: 14px; left: 14px;
    color: var(--text-faint); font-size: 11px;
    text-decoration: none;
    background: var(--background-secondary);
    padding: 4px 10px; border-radius: 4px;
    border: 1px solid var(--background-modifier-border);
    z-index: 1000;
    opacity: 0.4; transition: opacity 0.2s;
  }
  #landing-escape:hover { opacity: 1; }

  /* Caption pinned bottom-center. */
  #landing-caption {
    position: fixed; bottom: 12px; left: 50%; transform: translateX(-50%);
    color: var(--text-faint); font-size: 11px;
    text-align: center; z-index: 1000;
    pointer-events: none;
  }
</style>
"""

INJECT_JS = r"""
<script defer>
(function () {
  function tryClick(selector, attempts, delay) {
    let n = 0;
    const intv = setInterval(() => {
      const el = document.querySelector(selector);
      if (el) { el.click(); clearInterval(intv); }
      else if (++n >= attempts) clearInterval(intv);
    }, delay);
  }

  function addOverlay() {
    if (document.getElementById('landing-escape')) return;
    const a = document.createElement('a');
    a.id = 'landing-escape';
    a.href = 'jessica-j-walsh.html';
    a.textContent = '← exit graph view';
    document.body.appendChild(a);

    const cap = document.createElement('div');
    cap.id = 'landing-caption';
    cap.innerHTML = 'Walsh + Christoffel co-authorship network · click a node to open that person';
    document.body.appendChild(cap);
  }

  document.addEventListener('DOMContentLoaded', () => {
    // Switch to global graph (shows all 259 nodes instead of just neighbors).
    tryClick('.graph-icon.graph-global', 40, 150);
    addOverlay();
  });
})();
</script>
"""


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"Source page not found: {SOURCE}")
    html = SOURCE.read_text(encoding="utf-8")
    if "landing-graph-only" in html:
        # Already transformed; rebuild from a fresh copy if needed.
        raise SystemExit("Source already contains the landing injection. "
                         "Run against a freshly-exported page.")
    html = html.replace("</head>", INJECT_CSS + "</head>", 1)
    html = html.replace("</body>", INJECT_JS + "</body>", 1)
    DEST.write_text(html, encoding="utf-8")
    print(f"Wrote {DEST.name} ({len(html):,} chars) from {SOURCE.name}")


if __name__ == "__main__":
    main()

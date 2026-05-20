"""Build the interactive co-authorship graph from the NFB LLM Wiki.

Walks `wiki/entities/people/*.md`, parses YAML frontmatter and the
`## Co-authors` section's `**From [[<source>]]:**` blocks, then emits a
self-contained `index.html` with an embedded JSON data payload that
Cytoscape.js renders in any modern browser.

Run from anywhere:
    python scripts/build_graph.py

Override paths via env vars `NFB_WIKI_ROOT` and `OUTPUT_HTML` if needed.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
WIKI_ROOT = Path(os.environ.get("NFB_WIKI_ROOT", r"C:\WalshLab\NFB_LLM_Wiki"))
PEOPLE_DIR = WIKI_ROOT / "wiki" / "entities" / "people"
OUTPUT_HTML = Path(os.environ.get("OUTPUT_HTML", REPO_ROOT / "index.html"))

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+?)(?:\|[^\]]+)?\]\]")
FROM_BLOCK_HEADER_RE = re.compile(r"\*\*From\s+\[\[([^\]]+)\]\]\s*:\*\*")
WIKILINK_LAB_RE = re.compile(r"\[\[([^\]|#]+?)(?:\|[^\]]+)?\]\]")

# Hand-picked color palette for the labs that matter most to the Walsh + Christoffel labs.
# Other labs fall back to a muted scheme via `OTHER_LAB_COLORS`.
PRIMARY_LAB_COLORS: dict[str, str] = {
    "Walsh-lab-UNC": "#4B9CD3",          # Carolina blue (home lab)
    "Christoffel-lab-UNC": "#FF8C42",    # orange (sister lab)
    "Malenka-lab-Stanford": "#27AE60",   # green — Walsh postdoc home
    "Heifets-lab-Stanford": "#8E44AD",   # purple — recent psychedelic/opioid cluster
    "Russo-lab-Mount-Sinai": "#C0392B",  # red — Walsh PhD home (Russo)
    "Han-lab-Mount-Sinai": "#E74C3C",    # light red — Walsh PhD PI
    "Nestler-lab-Mount-Sinai": "#F39C12", # amber — Walsh PhD adjacent
    "Halpern-lab-Stanford": "#16A085",   # teal — Christoffel postdoc PI
    "Olson-lab-UC-Davis": "#1ABC9C",     # turquoise — psychoplastogen chem
    "Stuber-lab-UW": "#34495E",          # slate — whole-brain opioid
    "Roth-lab-UNC": "#2C3E50",           # dark blue — UNC psychedelic pharm
}

OTHER_LAB_COLOR = "#7F8C8D"   # gray-blue for any lab not in PRIMARY_LAB_COLORS
PI_NO_LAB_COLOR = "#FFE600"   # yellow accent for PIs without a wiki lab page
DEFAULT_COLOR = "#BDC3C7"     # light gray for plain authors
MISSING_PAGE_COLOR = "#34495E80"  # translucent slate for stub-only references (no page yet)


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return (frontmatter_dict, body_text). Handles missing or malformed FM."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    raw = m.group(1)
    try:
        fm = yaml.safe_load(raw) or {}
    except yaml.YAMLError:
        fm = {}
    return fm if isinstance(fm, dict) else {}, text[m.end():]


def strip_lab_wikilink(value: Any) -> str:
    """`lab:` frontmatter is `"[[Lab-page-basename]]"` — return the basename."""
    if not isinstance(value, str):
        return ""
    m = WIKILINK_LAB_RE.search(value)
    return m.group(1).strip() if m else value.strip()


def parse_coauthor_blocks(body: str) -> list[tuple[str, list[str]]]:
    """Return [(source_slug, [coauthor_wikilink_basenames]), ...] from the `## Co-authors` section."""
    # Locate the section.
    section_match = re.search(r"^##\s+Co-authors\s*$", body, re.MULTILINE)
    if not section_match:
        return []
    section = body[section_match.end():]
    # Stop at the next H2 heading.
    next_h2 = re.search(r"^##\s+\S", section, re.MULTILINE)
    if next_h2:
        section = section[: next_h2.start()]

    # Walk through `**From [[source]]:**` headers.
    results: list[tuple[str, list[str]]] = []
    parts = list(FROM_BLOCK_HEADER_RE.finditer(section))
    for i, m in enumerate(parts):
        source = m.group(1).strip()
        start = m.end()
        end = parts[i + 1].start() if i + 1 < len(parts) else len(section)
        chunk = section[start:end]
        coauthors = [w.strip() for w in WIKILINK_RE.findall(chunk)]
        results.append((source, coauthors))
    return results


def classify_node_color(fm: dict[str, Any]) -> tuple[str, str]:
    """Return (color_hex, category_label) for a node based on its frontmatter."""
    tags = fm.get("tags", []) or []
    tags = [str(t).lower() for t in tags] if isinstance(tags, list) else []

    lab_basename = strip_lab_wikilink(fm.get("lab", ""))
    if lab_basename in PRIMARY_LAB_COLORS:
        return PRIMARY_LAB_COLORS[lab_basename], lab_basename
    if lab_basename:
        return OTHER_LAB_COLOR, "Other lab"
    if "pi" in tags:
        return PI_NO_LAB_COLOR, "Other PI"
    return DEFAULT_COLOR, "Author"


def build_graph_data() -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edge_weights: dict[tuple[str, str], int] = {}
    sources_seen: set[str] = set()

    for path in sorted(PEOPLE_DIR.glob("*.md")):
        basename = path.stem
        text = path.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(text)

        title = fm.get("title", basename.replace("-", " "))
        if not isinstance(title, str):
            title = str(title)
        lab = strip_lab_wikilink(fm.get("lab", ""))
        sources_list = fm.get("sources", []) or []
        if not isinstance(sources_list, list):
            sources_list = []
        n_papers = len(sources_list)
        color, category = classify_node_color(fm)

        # Minimal public payload: name, lab (for color/filter), paper count (for sizing).
        # Affiliation / role / h-index / citation count / ORCID / tags are intentionally
        # excluded from the published HTML — names + connections only.
        nodes[basename] = {
            "id": basename,
            "label": title,
            "lab": lab,
            "n_papers": n_papers,
            "color": color,
            "category": category,
        }

        for source, coauthors in parse_coauthor_blocks(body):
            sources_seen.add(source)
            for ca in coauthors:
                if ca == basename:
                    continue
                a, b = sorted([basename, ca])
                edge_weights[(a, b)] = edge_weights.get((a, b), 0) + 1

    # Each true co-authorship contributes 2 directed mentions (one on each end's page).
    # Compute approximate "papers in common" = ceil(weight / 2).
    cy_edges = []
    for (a, b), w in edge_weights.items():
        papers_shared = max(1, (w + 1) // 2)
        cy_edges.append({
            "data": {
                "id": f"{a}__{b}",
                "source": a,
                "target": b,
                "weight": papers_shared,
            }
        })

    # Stub nodes for wikilinks referenced but missing a page.
    referenced: set[str] = set()
    for (a, b) in edge_weights:
        referenced.add(a)
        referenced.add(b)
    for ref in referenced:
        if ref not in nodes:
            nodes[ref] = {
                "id": ref,
                "label": ref.replace("-", " "),
                "lab": "",
                "n_papers": 0,
                "color": MISSING_PAGE_COLOR,
                "category": "Missing page",
            }

    cy_nodes = [{"data": n} for n in sorted(nodes.values(), key=lambda d: d["label"])]
    return {
        "nodes": cy_nodes,
        "edges": cy_edges,
        "stats": {
            "n_nodes": len(cy_nodes),
            "n_edges": len(cy_edges),
            "n_sources": len(sources_seen),
        },
        "palette": {
            **PRIMARY_LAB_COLORS,
            "Other lab": OTHER_LAB_COLOR,
            "Other PI": PI_NO_LAB_COLOR,
            "Author": DEFAULT_COLOR,
            "Missing page": MISSING_PAGE_COLOR,
        },
    }


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Walsh + Christoffel Lab Co-authorship Graph</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
  :root {
    color-scheme: dark;
    --bg: #1a1a1a;
    --panel: #242424;
    --text: #e7e7e7;
    --text-dim: #9a9a9a;
    --border: #383838;
    --accent: #4B9CD3;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
    overflow: hidden;
  }
  #app {
    display: grid;
    grid-template-columns: 280px 1fr 320px;
    height: 100vh;
  }
  .panel {
    background: var(--panel);
    border-right: 1px solid var(--border);
    overflow-y: auto;
    padding: 16px;
    font-size: 13px;
  }
  .panel.right {
    border-right: none;
    border-left: 1px solid var(--border);
  }
  h1 {
    margin: 0 0 4px 0;
    font-size: 17px;
    font-weight: 600;
    letter-spacing: 0.2px;
  }
  .subtitle {
    color: var(--text-dim);
    font-size: 12px;
    margin-bottom: 16px;
  }
  .stats {
    color: var(--text-dim);
    font-size: 11px;
    line-height: 1.5;
    margin-bottom: 16px;
    padding-bottom: 12px;
    border-bottom: 1px solid var(--border);
  }
  .stats b { color: var(--text); }
  .section-title {
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-size: 10px;
    color: var(--text-dim);
    margin-top: 18px;
    margin-bottom: 8px;
    font-weight: 600;
  }
  input[type="text"] {
    width: 100%;
    background: #181818;
    border: 1px solid var(--border);
    color: var(--text);
    padding: 6px 10px;
    border-radius: 4px;
    font-size: 13px;
    outline: none;
  }
  input[type="text"]:focus { border-color: var(--accent); }
  #legend { list-style: none; padding: 0; margin: 0; }
  #legend li {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 5px 6px;
    cursor: pointer;
    border-radius: 3px;
    user-select: none;
    margin-bottom: 1px;
  }
  #legend li:hover { background: #2e2e2e; }
  #legend li.disabled { opacity: 0.3; }
  #legend li .swatch {
    width: 12px; height: 12px; border-radius: 50%;
    border: 1px solid #00000060;
    flex-shrink: 0;
  }
  #legend li .label { flex: 1; font-size: 12px; }
  #legend li .count { color: var(--text-dim); font-size: 11px; }
  #cy { width: 100%; height: 100vh; background: var(--bg); }
  .detail-empty {
    color: var(--text-dim);
    font-size: 12px;
    line-height: 1.5;
  }
  .detail h2 {
    margin: 0 0 4px 0;
    font-size: 16px;
    font-weight: 600;
  }
  .detail .role { color: var(--text-dim); font-size: 12px; margin-bottom: 12px; }
  .detail .field {
    display: flex;
    gap: 8px;
    margin-bottom: 6px;
    font-size: 12px;
    line-height: 1.4;
  }
  .detail .field .key {
    color: var(--text-dim);
    flex-shrink: 0;
    min-width: 80px;
  }
  .detail .field .val { color: var(--text); }
  .detail .coauthors-list {
    margin-top: 14px;
    padding-top: 12px;
    border-top: 1px solid var(--border);
  }
  .detail .coauthors-list .item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 4px 6px;
    margin-bottom: 1px;
    border-radius: 3px;
    font-size: 12px;
    cursor: pointer;
  }
  .detail .coauthors-list .item:hover { background: #2e2e2e; }
  .detail .coauthors-list .item .papers {
    color: var(--text-dim);
    font-size: 10px;
  }
  .detail .swatch {
    width: 8px; height: 8px; border-radius: 50%;
    display: inline-block; margin-right: 6px;
    vertical-align: middle;
  }
  .credits {
    position: fixed;
    bottom: 8px; right: 336px;
    color: var(--text-dim);
    font-size: 10px;
    pointer-events: none;
  }
  .credits a { color: var(--accent); text-decoration: none; }
</style>
</head>
<body>
<div id="app">
  <aside class="panel left">
    <h1>Walsh + Christoffel</h1>
    <div class="subtitle">Co-authorship network</div>
    <div class="stats" id="stats"></div>

    <div class="section-title">Search</div>
    <input id="search" type="text" placeholder="Filter by name…" autocomplete="off" />

    <div class="section-title">Lab / category</div>
    <ul id="legend"></ul>
  </aside>

  <main>
    <div id="cy"></div>
  </main>

  <aside class="panel right" id="detail-panel">
    <div class="detail-empty" id="detail-empty">
      Click a node to see details. Hover any node to lift it. Drag to pan, scroll to zoom.
      <br /><br />
      Edges are weighted by number of co-authored papers in the wiki. Node size scales with
      the per-person paper count.
    </div>
    <div class="detail" id="detail" style="display: none;"></div>
  </aside>
</div>

<div class="credits">
  Built from <a href="https://github.com/karpathy" target="_blank">Karpathy</a>-pattern LLM wiki ·
  rendered with <a href="https://js.cytoscape.org" target="_blank">Cytoscape.js</a>
</div>

<script src="https://unpkg.com/cytoscape@3.30.4/dist/cytoscape.min.js"></script>
<script src="https://unpkg.com/layout-base@2.0.1/layout-base.js"></script>
<script src="https://unpkg.com/cose-base@2.2.0/cose-base.js"></script>
<script src="https://unpkg.com/cytoscape-fcose@2.2.0/cytoscape-fcose.js"></script>

<script>
const DATA = __DATA_PLACEHOLDER__;
const PALETTE = DATA.palette;

// --- Build category counts for the legend (preserve PRIMARY_LAB_COLORS order). ---
const labOrder = Object.keys(PALETTE);
const counts = {};
DATA.nodes.forEach(n => {
  const cat = n.data.category;
  counts[cat] = (counts[cat] || 0) + 1;
});

// --- Stats line ---
const statsEl = document.getElementById("stats");
statsEl.innerHTML =
  `<b>${DATA.stats.n_nodes}</b> people · <b>${DATA.stats.n_edges}</b> co-authorship edges<br />` +
  `across <b>${DATA.stats.n_sources}</b> ingested sources`;

// --- Legend ---
const legendEl = document.getElementById("legend");
const visibleCats = new Set(labOrder);
labOrder.forEach(cat => {
  const c = counts[cat] || 0;
  if (c === 0) return;
  const li = document.createElement("li");
  li.dataset.cat = cat;
  li.innerHTML = `<span class="swatch" style="background:${PALETTE[cat]}"></span>
                  <span class="label">${cat}</span>
                  <span class="count">${c}</span>`;
  li.addEventListener("click", () => {
    if (visibleCats.has(cat)) {
      visibleCats.delete(cat);
      li.classList.add("disabled");
    } else {
      visibleCats.add(cat);
      li.classList.remove("disabled");
    }
    applyFilters();
  });
  legendEl.appendChild(li);
});

// --- Cytoscape init ---
const cy = cytoscape({
  container: document.getElementById("cy"),
  elements: DATA.nodes.concat(DATA.edges),
  wheelSensitivity: 0.2,
  minZoom: 0.05,
  maxZoom: 4,
  style: [
    {
      selector: "node",
      style: {
        "background-color": "data(color)",
        "label": "data(label)",
        "font-size": 9,
        "color": "#cccccc",
        "text-valign": "bottom",
        "text-margin-y": 4,
        "text-outline-color": "#1a1a1a",
        "text-outline-width": 2,
        "width": ele => 8 + Math.sqrt(ele.data("n_papers") || 0) * 6,
        "height": ele => 8 + Math.sqrt(ele.data("n_papers") || 0) * 6,
        "border-color": "#00000040",
        "border-width": 1,
        "overlay-padding": 6,
      }
    },
    {
      selector: "node.dimmed",
      style: { "opacity": 0.08, "text-opacity": 0 }
    },
    {
      selector: "node.highlighted",
      style: {
        "border-color": "#ffffff",
        "border-width": 2,
        "z-index": 100,
        "font-weight": 700,
        "font-size": 11,
        "color": "#ffffff",
      }
    },
    {
      selector: "node.neighbor",
      style: { "font-size": 11, "color": "#ffffff" }
    },
    {
      selector: "edge",
      style: {
        "width": ele => Math.min(8, 0.5 + (ele.data("weight") || 1) * 0.9),
        "line-color": "#555",
        "curve-style": "haystack",
        "haystack-radius": 0.5,
        "opacity": 0.35,
      }
    },
    {
      selector: "edge.dimmed",
      style: { "opacity": 0.05 }
    },
    {
      selector: "edge.highlighted",
      style: { "line-color": "#ffffff", "opacity": 0.9, "z-index": 50 }
    },
  ],
  layout: {
    name: "fcose",
    quality: "default",
    randomize: true,
    animate: false,
    nodeRepulsion: 6000,
    idealEdgeLength: 70,
    edgeElasticity: 0.45,
    gravity: 0.25,
    numIter: 2500,
    tile: true,
    nodeSeparation: 75,
  }
});

// --- Selection / highlight handling ---
let selectedId = null;
let searchTerm = "";

function applyFilters() {
  const q = searchTerm.trim().toLowerCase();
  cy.batch(() => {
    cy.nodes().forEach(n => {
      const cat = n.data("category");
      const labelMatch = !q || n.data("label").toLowerCase().includes(q);
      const visible = visibleCats.has(cat) && labelMatch;
      n.style("display", visible ? "element" : "none");
    });
    cy.edges().forEach(e => {
      const s = e.source(), t = e.target();
      const both = (s.style("display") !== "none") && (t.style("display") !== "none");
      e.style("display", both ? "element" : "none");
    });
  });
  if (selectedId) highlightSelection(selectedId);
}

function highlightSelection(id) {
  const node = cy.getElementById(id);
  if (!node || node.empty()) return;
  cy.elements().removeClass("highlighted neighbor dimmed");
  cy.elements().addClass("dimmed");
  node.removeClass("dimmed").addClass("highlighted");
  const neighborhood = node.closedNeighborhood();
  neighborhood.removeClass("dimmed");
  neighborhood.nodes().not(node).addClass("neighbor");
  node.connectedEdges().addClass("highlighted").removeClass("dimmed");
  renderDetail(node);
}

function clearSelection() {
  selectedId = null;
  cy.elements().removeClass("highlighted neighbor dimmed");
  document.getElementById("detail").style.display = "none";
  document.getElementById("detail-empty").style.display = "block";
}

cy.on("tap", "node", evt => {
  selectedId = evt.target.id();
  highlightSelection(selectedId);
});

cy.on("tap", evt => {
  if (evt.target === cy) clearSelection();
});

// --- Detail panel ---
function renderDetail(node) {
  const d = node.data();
  const html = [];
  html.push(`<h2>${escapeHtml(d.label)}</h2>`);
  if (d.lab) {
    html.push(`<div class="role">${escapeHtml(d.lab.replace(/-/g, " "))}</div>`);
  }
  if (d.n_papers) {
    html.push(`<div class="field"><span class="key">Papers in wiki</span><span class="val">${d.n_papers}</span></div>`);
  }

  // Co-authors list
  const neighbors = node.neighborhood("node").not(node);
  if (neighbors.length > 0) {
    html.push(`<div class="coauthors-list">`);
    html.push(`<div class="section-title" style="margin-top:0">Co-authors (${neighbors.length})</div>`);
    const items = neighbors.map(n => {
      const edge = node.edgesWith(n);
      const w = edge.length ? edge.data("weight") : 1;
      return { node: n, weight: w };
    }).sort((a, b) => b.weight - a.weight);
    items.forEach(({ node: n, weight }) => {
      const nd = n.data();
      html.push(`<div class="item" data-id="${n.id()}">
        <span><span class="swatch" style="background:${nd.color}"></span>${escapeHtml(nd.label)}</span>
        <span class="papers">${weight} paper${weight === 1 ? "" : "s"}</span>
      </div>`);
    });
    html.push(`</div>`);
  }

  const detailEl = document.getElementById("detail");
  detailEl.innerHTML = html.join("");
  detailEl.style.display = "block";
  document.getElementById("detail-empty").style.display = "none";
  // wire up co-author clicks
  detailEl.querySelectorAll(".item").forEach(item => {
    item.addEventListener("click", () => {
      const targetId = item.dataset.id;
      selectedId = targetId;
      cy.center(cy.getElementById(targetId));
      highlightSelection(targetId);
    });
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

// --- Search ---
document.getElementById("search").addEventListener("input", e => {
  searchTerm = e.target.value;
  applyFilters();
});

// Center view after layout settles.
cy.ready(() => {
  setTimeout(() => cy.fit(undefined, 30), 200);
});
</script>
</body>
</html>
"""


def build_html(data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return HTML_TEMPLATE.replace("__DATA_PLACEHOLDER__", payload)


def main() -> None:
    if not PEOPLE_DIR.exists():
        raise SystemExit(f"PEOPLE_DIR not found: {PEOPLE_DIR}")

    data = build_graph_data()
    html = build_html(data)
    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(html, encoding="utf-8")

    print(f"Wrote {OUTPUT_HTML}")
    print(f"  nodes:   {data['stats']['n_nodes']}")
    print(f"  edges:   {data['stats']['n_edges']}")
    print(f"  sources: {data['stats']['n_sources']}")


if __name__ == "__main__":
    main()

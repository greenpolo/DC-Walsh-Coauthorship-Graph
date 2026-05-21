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

# Only the two home labs get distinguishing colors. Everyone else is default gray.
PRIMARY_LAB_COLORS: dict[str, str] = {
    "Walsh-lab-UNC": "#4B9CD3",          # Carolina blue (home lab)
    "Christoffel-lab-UNC": "#27AE60",    # green (sister lab)
}

OTHER_LAB_COLOR = "#BDC3C7"   # light gray — any other lab
PI_NO_LAB_COLOR = "#BDC3C7"   # light gray — PIs without a wiki lab page
DEFAULT_COLOR = "#BDC3C7"     # light gray for plain authors
MISSING_PAGE_COLOR = "#BDC3C780"  # translucent gray for stub-only references (no page yet)


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
    lab_basename = strip_lab_wikilink(fm.get("lab", ""))
    if lab_basename in PRIMARY_LAB_COLORS:
        return PRIMARY_LAB_COLORS[lab_basename], lab_basename
    return DEFAULT_COLOR, "Other"


def build_graph_data() -> dict[str, Any]:
    # Pass 1: parse every person page, collect metadata + raw co-author blocks.
    people: dict[str, dict[str, Any]] = {}
    for path in sorted(PEOPLE_DIR.glob("*.md")):
        basename = path.stem
        text = path.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(text)
        title = fm.get("title", basename.replace("-", " "))
        if not isinstance(title, str):
            title = str(title)
        lab = strip_lab_wikilink(fm.get("lab", ""))
        color, category = classify_node_color(fm)
        blocks = parse_coauthor_blocks(body)
        people[basename] = {
            "title": title,
            "lab": lab,
            "color": color,
            "category": category,
            "blocks": blocks,
        }

    # Build source -> set(author basenames) by unioning each person's blocks.
    source_authors: dict[str, set[str]] = {}
    for basename, info in people.items():
        for source, coauthors in info["blocks"]:
            authors = source_authors.setdefault(source, set())
            authors.add(basename)
            for ca in coauthors:
                authors.add(ca)

    # Keep only sources with at least one Walsh- or Christoffel-lab author.
    home_lab_members = {b for b, info in people.items() if info["lab"] in PRIMARY_LAB_COLORS}
    kept_sources = {s for s, authors in source_authors.items() if authors & home_lab_members}

    # Rebuild edges from kept sources only, and tally per-author paper counts.
    edge_weights: dict[tuple[str, str], int] = {}
    n_papers_per: dict[str, int] = {}
    for basename, info in people.items():
        for source, coauthors in info["blocks"]:
            if source not in kept_sources:
                continue
            n_papers_per[basename] = n_papers_per.get(basename, 0) + 1
            for ca in coauthors:
                if ca == basename:
                    continue
                a, b = sorted([basename, ca])
                edge_weights[(a, b)] = edge_weights.get((a, b), 0) + 1
    # Author counts for missing-page stubs come from the same source loop, but
    # via membership in source_authors (their own page didn't supply blocks).
    for s in kept_sources:
        for author in source_authors[s]:
            if author not in people:
                n_papers_per[author] = n_papers_per.get(author, 0) + 1

    # Determine which nodes survive: anyone with an edge, plus all home-lab members.
    connected: set[str] = set()
    for (a, b) in edge_weights:
        connected.add(a)
        connected.add(b)
    keep_nodes = connected | home_lab_members

    nodes: dict[str, dict[str, Any]] = {}
    for basename in keep_nodes:
        if basename in people:
            info = people[basename]
            nodes[basename] = {
                "id": basename,
                "label": info["title"],
                "lab": info["lab"],
                "n_papers": n_papers_per.get(basename, 0),
                "color": info["color"],
                "category": info["category"],
            }
        else:
            nodes[basename] = {
                "id": basename,
                "label": basename.replace("-", " "),
                "lab": "",
                "n_papers": n_papers_per.get(basename, 0),
                "color": MISSING_PAGE_COLOR,
                "category": "Missing page",
            }

    cy_edges = []
    for (a, b), w in edge_weights.items():
        if a not in nodes or b not in nodes:
            continue
        papers_shared = max(1, (w + 1) // 2)
        cy_edges.append({"source": a, "target": b, "weight": papers_shared})

    cy_nodes = sorted(nodes.values(), key=lambda d: d["label"])
    return {
        "nodes": cy_nodes,
        "links": cy_edges,
        "stats": {
            "n_nodes": len(cy_nodes),
            "n_edges": len(cy_edges),
            "n_sources": len(kept_sources),
        },
        "palette": {
            **PRIMARY_LAB_COLORS,
            "Other": DEFAULT_COLOR,
            "Missing page": MISSING_PAGE_COLOR,
        },
    }


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>DC-Walsh Labs Co-authorship Graph</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
  :root {
    color-scheme: dark;
    --bg: #1a1a1a;
    --panel: #242424cc;
    --text: #e7e7e7;
    --text-dim: #9a9a9a;
    --border: #383838;
    --accent: #4B9CD3;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; overflow: hidden; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
  }
  #graph { position: absolute; inset: 0; }
  .panel {
    position: absolute;
    background: var(--panel);
    backdrop-filter: blur(8px);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 9px 10px;
    font-size: 11px;
    z-index: 10;
  }
  .panel.left {
    top: 12px; left: 12px;
    width: 188px;
    max-height: calc(100vh - 24px);
    overflow-y: auto;
    transition: width 0.18s ease, padding 0.18s ease, max-height 0.18s ease;
  }
  .panel.left.collapsed {
    width: 36px;
    height: 36px;
    max-height: 36px;
    padding: 0;
    overflow: hidden;
    cursor: pointer;
  }
  .panel.left.collapsed > *:not(.panel-toggle) { display: none; }
  .panel-toggle {
    position: absolute;
    top: 5px; right: 5px;
    width: 24px; height: 24px;
    border: none;
    background: transparent;
    color: var(--text-dim);
    cursor: pointer;
    font-size: 14px;
    padding: 0;
    line-height: 1;
    border-radius: 3px;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .panel-toggle:hover { background: #ffffff10; color: var(--text); }
  .panel.left.collapsed .panel-toggle {
    top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    right: auto;
  }
  .panel.left h1 { padding-right: 32px; }
  .panel.right {
    top: 16px; right: 16px;
    width: 280px;
    max-height: calc(100vh - 32px);
    overflow-y: auto;
    display: none;
  }
  .panel.right.visible { display: block; }
  @media (max-width: 700px) {
    .panel.right { width: calc(100vw - 32px); }
    .help { display: none; }
  }
  h1 {
    margin: 0 0 1px 0;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.2px;
  }
  .subtitle { color: var(--text-dim); font-size: 9px; margin-bottom: 8px; }
  .stats {
    color: var(--text-dim);
    font-size: 9px;
    line-height: 1.45;
    padding-bottom: 7px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 7px;
  }
  .stats b { color: var(--text); }
  .section-title {
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-size: 8.5px;
    color: var(--text-dim);
    margin-top: 9px;
    margin-bottom: 4px;
    font-weight: 600;
  }
  input[type="text"] {
    width: 100%;
    background: #181818;
    border: 1px solid var(--border);
    color: var(--text);
    padding: 3px 6px;
    border-radius: 3px;
    font-size: 10.5px;
    outline: none;
  }
  input[type="text"]:focus { border-color: var(--accent); }
  .slider-row {
    display: grid;
    grid-template-columns: 60px 1fr 34px;
    gap: 5px;
    align-items: center;
    margin-bottom: 3px;
    font-size: 10px;
  }
  .slider-row label { color: var(--text-dim); }
  .slider-row .value { color: var(--text); text-align: right; font-variant-numeric: tabular-nums; }
  input[type="range"] {
    width: 100%;
    height: 4px;
    -webkit-appearance: none;
    appearance: none;
    background: #181818;
    border-radius: 2px;
    outline: none;
  }
  input[type="range"]::-webkit-slider-thumb {
    -webkit-appearance: none;
    appearance: none;
    width: 12px; height: 12px;
    border-radius: 50%;
    background: var(--accent);
    cursor: pointer;
  }
  input[type="range"]::-moz-range-thumb {
    width: 12px; height: 12px;
    border: none;
    border-radius: 50%;
    background: var(--accent);
    cursor: pointer;
  }
  #legend { list-style: none; padding: 0; margin: 0; }
  #legend li {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 2px 4px;
    cursor: pointer;
    border-radius: 3px;
    user-select: none;
  }
  #legend li:hover { background: #ffffff10; }
  #legend li.disabled { opacity: 0.3; }
  #legend li .swatch {
    width: 9px; height: 9px; border-radius: 50%;
    border: 1px solid #00000060;
    flex-shrink: 0;
  }
  #legend li .label { flex: 1; font-size: 10px; }
  #legend li .count { color: var(--text-dim); font-size: 9px; }
  .detail h2 { margin: 0 0 4px 0; font-size: 15px; font-weight: 600; }
  .detail .lab-row { color: var(--text-dim); font-size: 11px; margin-bottom: 10px; }
  .detail .field {
    display: flex; gap: 8px;
    margin-bottom: 4px; font-size: 12px;
  }
  .detail .field .key { color: var(--text-dim); min-width: 90px; }
  .detail .coauthors-list {
    margin-top: 12px;
    padding-top: 10px;
    border-top: 1px solid var(--border);
  }
  .detail .coauthors-list > summary {
    list-style: none;
    cursor: pointer;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-size: 9px;
    color: var(--text-dim);
    font-weight: 600;
    user-select: none;
    padding: 2px 0;
  }
  .detail .coauthors-list > summary::-webkit-details-marker { display: none; }
  .detail .coauthors-list > summary::before {
    content: "▸ ";
    display: inline-block;
    transition: transform 0.15s ease;
  }
  .detail .coauthors-list[open] > summary::before { content: "▾ "; }
  .detail .coauthors-list > .items { margin-top: 6px; }
  .coauthor-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 3px 6px;
    border-radius: 3px;
    font-size: 11px;
    cursor: pointer;
  }
  .coauthor-item:hover { background: #ffffff10; }
  .coauthor-item .papers { color: var(--text-dim); font-size: 10px; }
  .coauthor-item .swatch {
    width: 7px; height: 7px; border-radius: 50%;
    display: inline-block; margin-right: 5px; vertical-align: middle;
  }
  .help {
    position: absolute;
    bottom: 12px; left: 16px;
    color: var(--text-dim);
    font-size: 10px;
    z-index: 10;
    pointer-events: none;
    line-height: 1.5;
  }
  .credits {
    position: absolute;
    bottom: 12px; right: 16px;
    color: var(--text-dim);
    font-size: 10px;
    z-index: 10;
    pointer-events: none;
  }
  .credits a { color: var(--accent); text-decoration: none; }
  .close-btn {
    position: absolute;
    top: 10px; right: 10px;
    width: 20px; height: 20px;
    border: none;
    background: transparent;
    color: var(--text-dim);
    cursor: pointer;
    font-size: 16px;
    padding: 0;
    line-height: 1;
  }
  .close-btn:hover { color: var(--text); }
</style>
</head>
<body>
<div id="graph"></div>

<aside class="panel left" id="settings-panel">
  <button class="panel-toggle" id="settings-toggle" title="Toggle settings" aria-label="Toggle settings">☰</button>
  <h1>DC-Walsh Labs</h1>
  <div class="subtitle">Co-authorship network</div>
  <div class="stats" id="stats"></div>

  <div class="section-title">Search</div>
  <input id="search" type="text" placeholder="Filter by name…" autocomplete="off" />

  <div class="section-title">Forces</div>
  <div class="slider-row">
    <label>Center</label>
    <input id="f-center" type="range" min="0" max="100" value="3" />
    <span class="value" id="f-center-v">0.03</span>
  </div>
  <div class="slider-row">
    <label>Repel</label>
    <input id="f-repel" type="range" min="0" max="500" value="150" />
    <span class="value" id="f-repel-v">150</span>
  </div>
  <div class="slider-row">
    <label>Link force</label>
    <input id="f-link" type="range" min="0" max="100" value="40" />
    <span class="value" id="f-link-v">0.40</span>
  </div>
  <div class="slider-row">
    <label>Link dist</label>
    <input id="f-dist" type="range" min="20" max="300" value="80" />
    <span class="value" id="f-dist-v">80</span>
  </div>
  <div class="slider-row">
    <label>Name fade</label>
    <input id="f-label" type="range" min="0" max="500" value="160" />
    <span class="value" id="f-label-v">1.60</span>
  </div>

  <div class="section-title">Lab / category</div>
  <ul id="legend"></ul>
</aside>

<aside class="panel right" id="detail-panel">
  <button class="close-btn" id="detail-close">✕</button>
  <div class="detail" id="detail"></div>
</aside>

<div class="help">
  drag a node · scroll to zoom · click for details · hover to focus
</div>
<div class="credits">
  d3-force + <a href="https://github.com/vasturiano/force-graph" target="_blank">force-graph</a>
</div>

<script src="https://unpkg.com/d3@7/dist/d3.min.js"></script>
<script src="https://unpkg.com/force-graph@1.43.5/dist/force-graph.min.js"></script>

<script>
const DATA = __DATA_PLACEHOLDER__;
const PALETTE = DATA.palette;

// --- Stats ---
document.getElementById("stats").innerHTML =
  `<b>${DATA.stats.n_nodes}</b> people · <b>${DATA.stats.n_edges}</b> co-authorship edges<br />` +
  `across <b>${DATA.stats.n_sources}</b> ingested sources`;

// --- Legend ---
const counts = {};
DATA.nodes.forEach(n => { counts[n.category] = (counts[n.category] || 0) + 1; });
const legendEl = document.getElementById("legend");
const labOrder = Object.keys(PALETTE);
const hiddenCats = new Set();
labOrder.forEach(cat => {
  const c = counts[cat] || 0;
  if (c === 0) return;
  const li = document.createElement("li");
  li.dataset.cat = cat;
  li.innerHTML = `<span class="swatch" style="background:${PALETTE[cat]}"></span>
                  <span class="label">${cat}</span>
                  <span class="count">${c}</span>`;
  li.addEventListener("click", () => {
    if (hiddenCats.has(cat)) { hiddenCats.delete(cat); li.classList.remove("disabled"); }
    else { hiddenCats.add(cat); li.classList.add("disabled"); }
    Graph.refresh();
  });
  legendEl.appendChild(li);
});

// --- State for highlight / filter ---
let searchTerm = "";
let hoveredNode = null;
let highlightedIds = new Set();
let selectedNode = null;
let labelThreshold = 1.6;
let suppressClick = false;
// On touch-primary devices, finger-brushes fire spurious hover events
// during pans. Disable hover highlighting there — clicks still work.
const isTouchPrimary = window.matchMedia && window.matchMedia("(hover: none)").matches;
let neighborsByNode = new Map();
DATA.nodes.forEach(n => neighborsByNode.set(n.id, new Set()));
DATA.links.forEach(l => {
  neighborsByNode.get(l.source).add(l.target);
  neighborsByNode.get(l.target).add(l.source);
});

function nodeVisible(node) {
  if (hiddenCats.has(node.category)) return false;
  if (searchTerm) {
    return node.label.toLowerCase().includes(searchTerm);
  }
  return true;
}

function nodeRadius(n) {
  // Linear floor of 2 plus a sqrt-scaled body — keeps stubs visible while
  // giving 20-paper nodes ~3x the radius of 1-paper nodes (vs. ~2x before).
  return 2 + Math.sqrt(n.n_papers || 0) * 1.6;
}

function dimColor(hex) {
  // Convert hex (possibly 8-digit) to rgba with low alpha.
  let h = hex.replace("#", "");
  if (h.length === 8) h = h.slice(0, 6);
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r},${g},${b},0.12)`;
}

// --- Force-graph init ---
const Graph = ForceGraph()
  (document.getElementById("graph"))
  .graphData(DATA)
  .backgroundColor("#1a1a1a")
  .nodeId("id")
  .nodeRelSize(1)
  .nodeVal(n => Math.pow(nodeRadius(n), 2))
  .linkColor(link => {
    // When a node is focused, only edges touching it light up (direct connections only).
    const focal = selectedNode || hoveredNode;
    if (focal) {
      const s = typeof link.source === "object" ? link.source.id : link.source;
      const t = typeof link.target === "object" ? link.target.id : link.target;
      if (s === focal.id || t === focal.id) {
        return "rgba(255,255,255,0.5)";
      }
      return "rgba(255,255,255,0.02)";
    }
    return "rgba(255,255,255,0.13)";
  })
  .linkWidth(link => 0.5 + Math.min(link.weight, 6) * 0.45)
  .cooldownTime(Infinity)
  .d3AlphaDecay(0.012)
  .d3VelocityDecay(0.35)
  .warmupTicks(40)
  .nodeCanvasObject((node, ctx, globalScale) => {
    if (!nodeVisible(node)) return;
    const r = nodeRadius(node);
    const isHovered = node.id === (hoveredNode && hoveredNode.id);
    const isSelected = node.id === (selectedNode && selectedNode.id);
    const isDimmed = highlightedIds.size > 0 && !highlightedIds.has(node.id);

    // Body
    ctx.beginPath();
    ctx.arc(node.x, node.y, r, 0, 2 * Math.PI, false);
    ctx.fillStyle = isDimmed ? dimColor(node.color) : node.color;
    ctx.fill();

    // Border
    if (isHovered || isSelected) {
      ctx.lineWidth = 2 / globalScale;
      ctx.strokeStyle = "#ffffff";
      ctx.stroke();
    } else if (!isDimmed) {
      ctx.lineWidth = 0.5 / globalScale;
      ctx.strokeStyle = "#00000080";
      ctx.stroke();
    }

    // Label — show when zoomed in, or when this node is highlighted
    const showLabel = isHovered || isSelected ||
                      (highlightedIds.size > 0 && highlightedIds.has(node.id)) ||
                      globalScale > labelThreshold;
    if (showLabel && !isDimmed) {
      // Quadratic scaling with no floor. Cap + multiplier scale with
      // viewport width so phone screens get proportionally smaller text.
      const vw = Math.min(1, window.innerWidth / 1200);
      const screenPx = Math.min(16 * vw, Math.pow(globalScale, 2) * 4 * vw);
      const fontSize = screenPx / globalScale;
      ctx.font = `${fontSize}px -apple-system, sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.strokeStyle = "#1a1a1a";
      ctx.lineWidth = 3 / globalScale;
      ctx.strokeText(node.label, node.x, node.y + r + 1);
      ctx.fillStyle = (isHovered || isSelected) ? "#ffffff" : "#bbbbbb";
      ctx.fillText(node.label, node.x, node.y + r + 1);
    }
  })
  .nodePointerAreaPaint((node, color, ctx) => {
    if (!nodeVisible(node)) return;
    const r = nodeRadius(node) + 2;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(node.x, node.y, r, 0, 2 * Math.PI, false);
    ctx.fill();
  })
  .onNodeHover(node => {
    if (isTouchPrimary) return;
    hoveredNode = node;
    if (node && !selectedNode) {
      highlightedIds = new Set([node.id, ...neighborsByNode.get(node.id)]);
    } else if (!selectedNode) {
      highlightedIds = new Set();
    }
    document.body.style.cursor = node ? "pointer" : null;
  })
  .onNodeClick(node => {
    if (suppressClick) { suppressClick = false; return; }
    if (selectedNode && selectedNode.id === node.id) {
      // Deselect + unfreeze
      delete selectedNode.fx; delete selectedNode.fy;
      selectedNode = null;
      highlightedIds = hoveredNode ? new Set([hoveredNode.id, ...neighborsByNode.get(hoveredNode.id)]) : new Set();
      hideDetail();
    } else {
      // Unfreeze old selection
      if (selectedNode) { delete selectedNode.fx; delete selectedNode.fy; }
      selectedNode = node;
      // Pin in current position to stop drift
      node.fx = node.x;
      node.fy = node.y;
      highlightedIds = new Set([node.id, ...neighborsByNode.get(node.id)]);
      showDetail(node);
    }
    Graph.d3ReheatSimulation();
  })
  .onBackgroundClick(() => {
    if (suppressClick) { suppressClick = false; return; }
    if (selectedNode) {
      delete selectedNode.fx; delete selectedNode.fy;
      selectedNode = null;
      hideDetail();
    }
    highlightedIds = new Set();
  });

// --- Suppress click-after-pan ---
// Track pointer movement between down and up; if the gesture traveled
// more than DRAG_THRESHOLD pixels (i.e. a pan/drag), discard the click.
const DRAG_THRESHOLD = 8;
let pointerDownPos = null;
const graphRoot = document.getElementById("graph");
graphRoot.addEventListener("pointerdown", e => {
  pointerDownPos = { x: e.clientX, y: e.clientY };
  suppressClick = false;
}, true);
graphRoot.addEventListener("pointerup", e => {
  if (pointerDownPos) {
    const dx = e.clientX - pointerDownPos.x;
    const dy = e.clientY - pointerDownPos.y;
    if (Math.hypot(dx, dy) > DRAG_THRESHOLD) suppressClick = true;
  }
  pointerDownPos = null;
}, true);

// --- Force tuning sliders ---
Graph.d3Force("charge").strength(-150);
Graph.d3Force("link").distance(80).strength(0.4);
// forceCenter only translates the centroid — use forceX/forceY for real radial pull
Graph.d3Force("center", null);
Graph.d3Force("x", d3.forceX(0).strength(0.03));
Graph.d3Force("y", d3.forceY(0).strength(0.03));
Graph.d3Force("collision", d3.forceCollide(n => nodeRadius(n) + 1));

const f = {
  center: document.getElementById("f-center"),
  repel:  document.getElementById("f-repel"),
  link:   document.getElementById("f-link"),
  dist:   document.getElementById("f-dist"),
  label:  document.getElementById("f-label"),
};
const fv = {
  center: document.getElementById("f-center-v"),
  repel:  document.getElementById("f-repel-v"),
  link:   document.getElementById("f-link-v"),
  dist:   document.getElementById("f-dist-v"),
  label:  document.getElementById("f-label-v"),
};
f.center.addEventListener("input", e => {
  const v = +e.target.value / 100;
  fv.center.textContent = v.toFixed(2);
  Graph.d3Force("x").strength(v);
  Graph.d3Force("y").strength(v);
  Graph.d3ReheatSimulation();
});
f.repel.addEventListener("input", e => {
  const v = +e.target.value;
  fv.repel.textContent = v;
  Graph.d3Force("charge").strength(-v);
  Graph.d3ReheatSimulation();
});
f.link.addEventListener("input", e => {
  const v = +e.target.value / 100;
  fv.link.textContent = v.toFixed(2);
  Graph.d3Force("link").strength(v);
  Graph.d3ReheatSimulation();
});
f.dist.addEventListener("input", e => {
  const v = +e.target.value;
  fv.dist.textContent = v;
  Graph.d3Force("link").distance(v);
  Graph.d3ReheatSimulation();
});
f.label.addEventListener("input", e => {
  const v = +e.target.value / 100;
  fv.label.textContent = v.toFixed(2);
  labelThreshold = v;
  Graph.refresh();
});

// --- Search ---
document.getElementById("search").addEventListener("input", e => {
  searchTerm = e.target.value.trim().toLowerCase();
  Graph.refresh();
});

// --- Detail panel ---
const panelEl = document.getElementById("detail-panel");
const detailEl = document.getElementById("detail");
document.getElementById("detail-close").addEventListener("click", () => {
  if (selectedNode) { delete selectedNode.fx; delete selectedNode.fy; }
  selectedNode = null;
  highlightedIds = new Set();
  hideDetail();
});

function hideDetail() { panelEl.classList.remove("visible"); }

function showDetail(node) {
  const html = [];
  html.push(`<h2>${escapeHtml(node.label)}</h2>`);
  if (node.lab) {
    html.push(`<div class="lab-row">${escapeHtml(node.lab.replace(/-/g, " "))}</div>`);
  }
  if (node.n_papers) {
    html.push(`<div class="field"><span class="key">Papers in wiki</span><span>${node.n_papers}</span></div>`);
  }

  // Co-authors
  const neighbors = [...neighborsByNode.get(node.id)];
  if (neighbors.length > 0) {
    const linkByPair = new Map();
    DATA.links.forEach(l => {
      const s = typeof l.source === "object" ? l.source.id : l.source;
      const t = typeof l.target === "object" ? l.target.id : l.target;
      if (s === node.id) linkByPair.set(t, l.weight);
      else if (t === node.id) linkByPair.set(s, l.weight);
    });
    const items = neighbors.map(id => {
      const n = DATA.nodes.find(x => x.id === id);
      return { node: n, weight: linkByPair.get(id) || 1 };
    }).sort((a, b) => b.weight - a.weight);

    html.push(`<details class="coauthors-list">`);
    html.push(`<summary>Co-authors (${neighbors.length})</summary>`);
    html.push(`<div class="items">`);
    items.forEach(({ node: n, weight }) => {
      html.push(`<div class="coauthor-item" data-id="${n.id}">
        <span><span class="swatch" style="background:${n.color}"></span>${escapeHtml(n.label)}</span>
        <span class="papers">${weight}</span>
      </div>`);
    });
    html.push(`</div></details>`);
  }

  detailEl.innerHTML = html.join("");
  panelEl.classList.add("visible");
  detailEl.querySelectorAll(".coauthor-item").forEach(el => {
    el.addEventListener("click", () => {
      const id = el.dataset.id;
      const n = DATA.nodes.find(x => x.id === id);
      if (n) {
        if (selectedNode) { delete selectedNode.fx; delete selectedNode.fy; }
        selectedNode = n;
        n.fx = n.x; n.fy = n.y;
        highlightedIds = new Set([n.id, ...neighborsByNode.get(n.id)]);
        Graph.centerAt(n.x, n.y, 600);
        Graph.d3ReheatSimulation();
        showDetail(n);
      }
    });
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

// --- Settings panel collapse / expand ---
const settingsPanel = document.getElementById("settings-panel");
const settingsToggle = document.getElementById("settings-toggle");
function setCollapsed(collapsed) {
  if (collapsed) {
    settingsPanel.classList.add("collapsed");
    settingsToggle.textContent = "☰";
  } else {
    settingsPanel.classList.remove("collapsed");
    settingsToggle.textContent = "✕";
  }
}
settingsToggle.addEventListener("click", e => {
  e.stopPropagation();
  setCollapsed(!settingsPanel.classList.contains("collapsed"));
});
settingsPanel.addEventListener("click", e => {
  if (settingsPanel.classList.contains("collapsed")) setCollapsed(false);
});
// Default collapsed on narrow viewports (mobile/portrait tablet).
setCollapsed(window.innerWidth < 700);

// Resize handler
window.addEventListener("resize", () => Graph.width(window.innerWidth).height(window.innerHeight));
Graph.width(window.innerWidth).height(window.innerHeight);

// Zoom to fit after initial settle.
setTimeout(() => Graph.zoomToFit(800, 60), 1500);
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

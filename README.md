# DC-Walsh Co-authorship Graph

Interactive co-authorship network for the Walsh + Christoffel labs at UNC, generated from the [NFB LLM Wiki](https://github.com/) (sibling private repo).

**Live view:** *(URL goes here once GitHub Pages is enabled)*

## What this is

A self-contained `index.html` rendering a force-directed graph of ~260 researchers and their co-authorship ties, parsed from the wiki's per-person `## Co-authors` blocks. Click a node to see affiliation / h-index / paper count, click again to see who they've co-authored with. Filter by lab from the legend; search by name.

- **Walsh Lab (Carolina blue), Christoffel Lab (orange)** are the two home labs.
- **Heifets, Malenka, Russo, Han, Nestler, Halpern, Olson** etc. get distinct colors because they're frequent collaborators / Walsh's training labs.
- **Other labs** share a muted gray.
- **PIs without a lab page** are yellow.
- **Plain authors** are light gray.

Node size scales with paper count; edge thickness scales with shared papers.

## Updating

When the wiki gets new ingests, regenerate the HTML:

```powershell
python scripts/build_graph.py
git add index.html
git commit -m "refresh: regenerate from wiki state"
git push
```

GitHub Pages auto-deploys on push.

## Architecture

- `scripts/build_graph.py` — walks `C:\WalshLab\NFB_LLM_Wiki\wiki\entities\people\*.md`, parses frontmatter + `## Co-authors` wikilinks, emits nodes/edges JSON, and bakes everything into `index.html`.
- `index.html` — single file, ~250 KB inc. embedded data. Uses [Cytoscape.js](https://js.cytoscape.org) via CDN with the [fcose](https://github.com/iVis-at-Bilkent/cytoscape.js-fcose) layout extension.
- No build step, no server. Open in any modern browser.

## Customization

Edit `PRIMARY_LAB_COLORS` in `scripts/build_graph.py` to add/change lab colors. Override the wiki path with `NFB_WIKI_ROOT` and the output path with `OUTPUT_HTML` env vars.

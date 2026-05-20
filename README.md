# DC-Walsh Co-authorship Graph

Single-page interactive co-authorship network for the Walsh + Christoffel labs at UNC.

**Live:** https://greenpolo.github.io/DC-Walsh-Coauthorship-Graph/

One HTML file. No individual person pages, no sidebars, no Obsidian export — just the graph. Works on desktop and mobile (d3-force + Canvas; touch and pinch-zoom supported).

## What's in the graph

- **259 nodes** = every researcher with a wiki page in `wiki/entities/people/` of the sibling [NFB LLM Wiki](https://github.com/) vault.
- **2,661 edges** = co-authorship ties parsed from each person page's `## Co-authors` section.
- **Colors** = lab affiliation (Walsh = Carolina blue, Christoffel = orange, Heifets / Malenka / Russo / Han / Nestler / Halpern / Olson / Stuber / Roth distinguished, plus "other lab", "other PI", "author", "missing page").
- **Node size** = number of papers in the wiki.
- **Edge thickness** = shared paper count.

## Interactions

- Drag a node → reflows the network live (d3-force continuous simulation).
- Hover → highlights the node + its neighbors, dims everything else.
- Click → pins that node, opens a side panel with co-authors sorted by shared-paper count.
- Click a co-author in the side panel → centers on that person.
- Scroll → zoom. Drag empty space → pan.
- Four live sliders adjust forces (center / repel / link force / link distance).
- Search bar filters visible nodes by name.
- Legend swatches toggle whole lab groups on/off.

## What's exposed in the public HTML

Per node: `id, label, lab, n_papers, color, category`. Per edge: `source, target, weight`. Nothing else — no affiliation, role, h-index, ORCID, citation count, ORCID, or page bodies. The 39 source paper slugs are not in the data payload (only inferred edge weights).

## Regenerating after wiki ingests

```powershell
cd C:/WalshLab/DC-Walsh-Coauthorship-Graph
python scripts/build_graph.py
git add index.html
git commit -m "refresh: regenerate from wiki state"
git push
```

GitHub Pages auto-rebuilds on push (~30–60 s lag).

## Customization

Edit `PRIMARY_LAB_COLORS` in `scripts/build_graph.py` to add/change lab colors. Override the wiki path with `NFB_WIKI_ROOT` and the output path with `OUTPUT_HTML` env vars.

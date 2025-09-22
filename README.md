# Holden's Daily Report

Generate a daily PDF briefing with book-grade typography using SILE.

Highlights:
- Sharp page boundaries with precise frames.
- Stylized Front Page "Holden’s Daily Report".
- Low-ink/low-color aesthetic with restrained accents.

Planned sections:
- Low-color version of the Wikipedia front page
- Summary of API spend from the previous day
- Facebook API: new posts from followed feeds
- YouTube: new videos from followed channels
- CALDAV: today’s events
- Weather: a daily plot (SVG) embedded in the PDF
- RSS: new items from followed feeds (including arstechnica, pluralistic.net)

Architecture (high level):
- Per-section pipeline: each section has a Python producer (tools/<section>.py) that writes data/<section>.json, a SILE section class (sile/sections/<section>.sil) that renders the section, and the main document includes those classes.
- Typesetting (SILE): holden-report.sil is the top-level class (frames, header, footer). It also hosts shared JSON utilities. Each section reads its own JSON file.
- Layout strategy: Explicit SILE frames for page boundaries; “section boxes” that can flow multiple short sections onto one page; page numbers.

Dev environment (Nix Flake):
- Reproducible shell with SILE and Python preinstalled.

Quick start:
- nix develop
- sile --version
- (Once templates/scripts are added) python tools/build.py

Planned directory layout:
- sile/: SILE classes and templates
  - sile/main.sil (entrypoint)
  - sile/holden-report.sil (top-level class: frames, header, footer, colors, fonts, shared JSON helpers)
  - sile/sections/rss.sil (RSS section class)
  - sile/sections/wikipedia.sil
  - sile/sections/api_spend.sil
  - sile/sections/youtube.sil
  - sile/sections/facebook.sil
  - sile/sections/caldav.sil
  - sile/sections/weather.sil
- tools/: Python scripts per section to fetch data and write JSON; plus orchestrator
  - tools/rss.py, tools/wiki.py, tools/spend.py, tools/youtube.py, tools/facebook.py, tools/caldav.py, tools/weather.py
  - tools/build.py: Orchestrates generation and invokes SILE
- data/: Per-section JSON and caches
  - data/rss.json, data/wikipedia.json, data/api_spend.json, data/youtube.json, data/facebook.json, data/caldav.json, data/weather.json
  - data/.cache/: raw API responses and metadata
- assets/: Fonts, icons, and generated charts (SVG preferred)
- output/: Generated PDFs

Typography and color:
- Fonts: JetBrains Mono everywhere, in headers and body.
- Palette: Define named colors once (e.g., Ink, Subtle, Accent) in a SILE package and reuse across components.
- Microtypography: Use SILE’s default features and tweak as needed (tracking, protrusion, hyphenation).

Pagination & layout:
- Use SILE frames for sharp page edges and consistent margins.
- Header: Running header “Holden’s Daily Report”; footer with page numbers.
- Collate short sections using vertical boxes to avoid orphaned whitespace.

Next steps:
- Keep holden-report.sil as the top-level class and add per-section SILE classes under sile/sections/.
- Add per-section Python producers that write data/<section>.json and update the orchestrator to call them.
- Implement the RSS vertical slice end-to-end (tools/rss.py -> data/rss.json -> sile/sections/rss.sil -> PDF).

License: TBD

# Holden's Daily Report

Generate a daily PDF briefing with book-grade typography using SILE.

Highlights:
- Sharp page boundaries with precise frames.
- Consistent running header: “Holden’s Daily Report”.
- Low-ink/low-color aesthetic with restrained accents.
- Multiple short sections can share a page without wasting space.

Planned sections:
- Low-color version of the Wikipedia front page
- Summary of API spend from the previous day
- Facebook API: new posts from followed feeds
- YouTube: new videos from followed channels
- CALDAV: today’s events
- Weather: a daily plot (SVG) embedded in the PDF
- RSS: new items from followed feeds (including arstechnica, pluralistic.net)

Architecture (high level):
- Data gathering (Python): Fetch, normalize, and cache content as JSON and SVG artifacts.
- Typesetting (SILE): SILE .sil templates (with Lua) render JSON/SVG into a styled PDF.
- Layout strategy: Explicit SILE frames for page boundaries; “section boxes” that can flow multiple short sections onto one page; running header; page numbers.

Dev environment (Nix Flake):
- Reproducible shell with SILE and Python preinstalled.
- .env sets USE_FLAKE=true to signal flake-based workflows.

Quick start:
- nix develop
- sile --version
- (Once templates/scripts are added) python tools/build.py

Planned directory layout:
- sile/: SILE classes, packages, and main document templates
  - sile/main.sil (entrypoint)
  - sile/holden-report.sil (class: frames, header, footer, colors, fonts)
  - sile/components/*.sil (reusable section renderers)
- tools/: Python scripts to fetch data, cache it, and render SILE input
- data/: Cached API responses and normalized JSON
- assets/: Fonts, icons, and generated charts (SVG preferred)
- output/: Generated PDFs

Typography and color:
- Fonts (suggested): Inter (text), JetBrains Mono (code). Place OTF/TTF in assets/fonts and load via SILE’s font configuration.
- Palette: Define named colors once (e.g., Ink, Subtle, Accent) in a SILE package and reuse across components.
- Microtypography: Use SILE’s default features and tweak as needed (tracking, protrusion, hyphenation).

Pagination & layout:
- Use SILE frames for sharp page edges and consistent margins.
- Header: Running header “Holden’s Daily Report”; footer with page numbers.
- Collate short sections using vertical boxes to avoid orphaned whitespace.

Security & secrets:
- Keep API keys in environment variables (e.g., in a local .env not committed).
- Add network timeouts and caching to avoid rate limits.

Next steps:
- Implement a minimal SILE class with frames, header, and page numbers.
- Add a Python build script that writes JSON and invokes SILE.
- Implement one data section end-to-end (RSS) as a vertical slice.

License: TBD

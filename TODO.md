# TODO

Next up (prioritized):
- [x] SILE class skeleton in sile/holden-report.sil: frames, header, footer, counters
- [x] Lua JSON loading in SILE using a standard JSON library if available (cjson/dkjson) and wire to section boxes
- [x] Per-section pipeline skeletons: add sile/sections/* classes, per-section JSON filenames, and per-section Python modules; update tools/build.py to generate data/*.json
- [x] Implement the RSS vertical slice end-to-end (tools/rss.py -> data/rss.json -> sile/sections/rss.sil -> PDF).
- [x] Caching scaffold in data/.cache with TTL and freshness checks
- [x] .gitignore entries for caches and output artifacts

MVP typesetting (SILE):
- [ ] Create sile/holden-report.sil class:
  - [ ] Page size, margins, and frames for sharp boundaries
  - [ ] Opening header
  - [ ] Footer with page numbers
  - [ ] Running header/counters setup (page numbers via counters)
  - [ ] Color palette (Ink, Subtle, Accent) and baseline grid spacing
  - [ ] Font setup (open-license fixed-width fonts) loaded from assets/fonts
- [x] Main entrypoint sile/main.sil using the class and rendering placeholder sections
- [x] Placeholder sections render in main.sil (temporary sans-serif header; class TBD)
- [ ] Section components:
  - [x] A generic “section box” macro that composes title + body content
  - [ ] Automatic collation of short section boxes onto the same page
  - [ ] Section box variants: list, table, paragraph
  - [ ] A flow-sections macro to pack multiple boxes with vertical glue and keep-with-next

Build pipeline:
- [x] generate.py: Minimal wrapper to invoke SILE and write output/brief.pdf
- [x] tools/build.py: Orchestrate data fetch → JSON/SVG → call SILE to build output/brief.pdf
- [x] Caching layer (data/.cache) with timestamps to limit API calls
  - [x] Define cache key scheme and filenames in data/.cache
  - [x] TTL per source; skip network if fresh
  - [x] Utility helpers: read_cache(path) / write_cache(path, payload, meta)
- [ ] Config via environment variables (.env and/or dotenv) for API keys
  - [ ] Load .env via python-dotenv (fallback to os.environ)
  - [ ] Document required variables in README and provide .env.example
- [ ] Make the build idempotent and fast (skip unchanged assets)
  - [ ] Hash content (JSON + SVG) and short-circuit SILE when unchanged
  - [ ] Only write files when content differs (avoid noisy rebuilds)
  - [ ] Logging with timings and clear “cache hit/miss” messages

Data ingestion (Python):
- [ ] RSS (feedparser):
  - [ ] Read configured feeds (incl. https://feeds.arstechnica.com/arstechnica/index and https://pluralistic.net/feed/)
  - [ ] Normalize to JSON (title, link, source, published, summary)
  - [ ] Minimal module scaffold (tools/rss.py) with fetch_rss(feeds: list[str]) -> list[Item]
- [ ] Wikipedia (MediaWiki API):
  - [ ] Fetch a low-ink textual summary of the front page (avoid large images)
  - [ ] Strip styles, sanitize HTML to plain text/limited markup
  - [ ] Module scaffold (tools/wiki.py) with fetch_front_page() -> dict
- [ ] API spend summary (previous day):
  - [ ] Define source(s) and auth
  - [ ] Compute totals and top endpoints; output small table JSON
  - [ ] Module scaffold (tools/spend.py) with summarize_spend(date) -> dict
- [ ] YouTube (Data API v3):
  - [ ] Fetch latest videos from followed channels (or from a channel list)
  - [ ] Extract title, channel, published time, link
  - [ ] Module scaffold (tools/youtube.py) with fetch_videos(channels) -> list[Item]
- [ ] Facebook Graph API:
  - [ ] Fetch new posts from followed feeds (permissions required)
  - [ ] Normalize to author, time, text, links
  - [ ] Module scaffold (tools/facebook.py) with fetch_posts(pages) -> list[Item]
- [ ] CALDAV:
  - [ ] Connect to calendar and fetch today’s events
  - [ ] Handle time zones; output start/end, title, location
  - [ ] Module scaffold (tools/caldav.py) with fetch_events(date) -> list[Event]
- [ ] Weather:
  - [ ] Fetch daily forecast
  - [ ] Generate an SVG plot (matplotlib) saved to assets/charts/weather.svg
  - [ ] Module scaffold (tools/weather.py) with build_daily_svg(path) and return metadata

SILE rendering details:
- [ ] Section titles with consistent typographic hierarchy
- [ ] Bullet and code styles (monospace; JetBrains Mono)
- [ ] Hyphenation and widows/orphans control
- [ ] Sensible overflow handling (truncate/continue indicators)
- [ ] Image/SVG scaling utilities (max width, preserve aspect ratio)
- [ ] Keep section boxes on baseline grid (align glue to baseline)

Integration:
- [ ] Per-section JSON inputs for SILE (no unified data.json):
  - [ ] Define canonical files: data/rss.json, data/wikipedia.json, data/api_spend.json, data/youtube.json, data/facebook.json, data/caldav.json, data/weather.json
  - [ ] Update main.sil to include per-section section classes and render from each JSON
  - [ ] Remove references to unified data/data.json from code and docs
- [ ] In SILE, use Lua to read and map per-section JSON to section boxes:
  - [x] Use standard JSON libraries if present (cjson/dkjson); do not vendor a parser
  - [ ] Add helper to load a JSON file by path (kept in holden-report.sil) and expose to section classes
  - [ ] Render each section from its own JSON file
- [ ] Insert SVG charts/images with proper scaling and low-ink palette

Ops & polish:
- [ ] .gitignore: data caches, output PDFs, local secrets
- [ ] Fail fast when APIs fail

Notes/decisions:
- Low-color aesthetic: grayscale + one accent color
- Short sections can share a page via stacked boxes; avoid large white gaps
- Keep secrets out of the repo; prefer environment variables
- Per-section architecture: one SILE section class + one Python producer + one JSON file per section
- Do not vendor a JSON parser; rely on standard Lua JSON libs (cjson/dkjson).

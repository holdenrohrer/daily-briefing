# TODO

MVP typesetting (SILE):
- [ ] Create sile/holden-report.sil class:
  - [ ] Page size, margins, and frames for sharp boundaries
  - [ ] Opening header
  - [ ] Footer with page numbers
  - [ ] Color palette (Ink, Subtle, Accent) and baseline grid spacing
  - [ ] Font setup (open-license fixed-width fonts) loaded from assets/fonts
- [x] Main entrypoint sile/main.sil using the class and rendering placeholder sections
- [x] Placeholder sections render in main.sil (temporary sans-serif header; class TBD)
- [ ] Section components:
  - [x] A generic “section box” macro that composes title + body content
  - [ ] Automatic collation of short section boxes onto the same page

Build pipeline:
- [x] generate.py: Minimal wrapper to invoke SILE and write output/brief.pdf
- [x] tools/build.py: Orchestrate data fetch → JSON/SVG → call SILE to build output/brief.pdf
- [ ] Caching layer (data/.cache) with timestamps to limit API calls
- [ ] Config via environment variables (.env and/or dotenv) for API keys
- [ ] Make the build idempotent and fast (skip unchanged assets)

Data ingestion (Python):
- [ ] RSS (feedparser):
  - [ ] Read configured feeds (incl. https://feeds.arstechnica.com/arstechnica/index and https://pluralistic.net/feed/)
  - [ ] Normalize to JSON (title, link, source, published, summary)
- [ ] Wikipedia (MediaWiki API):
  - [ ] Fetch a low-ink textual summary of the front page (avoid large images)
  - [ ] Strip styles, sanitize HTML to plain text/limited markup
- [ ] API spend summary (previous day):
  - [ ] Define source(s) and auth
  - [ ] Compute totals and top endpoints; output small table JSON
- [ ] YouTube (Data API v3):
  - [ ] Fetch latest videos from followed channels (or from a channel list)
  - [ ] Extract title, channel, published time, link
- [ ] Facebook Graph API:
  - [ ] Fetch new posts from followed feeds (permissions required)
  - [ ] Normalize to author, time, text, links
- [ ] CALDAV:
  - [ ] Connect to calendar and fetch today’s events
  - [ ] Handle time zones; output start/end, title, location
- [ ] Weather:
  - [ ] Fetch daily forecast
  - [ ] Generate an SVG plot (matplotlib) saved to assets/charts/weather.svg

SILE rendering details:
- [ ] Section titles with consistent typographic hierarchy
- [ ] Bullet and code styles (monospace)
- [ ] Hyphenation and widows/orphans control
- [ ] Sensible overflow handling (truncate/continue indicators)

Integration:
- [ ] Combine JSON data into a single data/data.json for SILE:
  - [x] Write placeholder combined JSON to data/data.json in tools/build.py
  - [x] Pass the JSON path to SILE via REPORT_DATA_JSON env
  - [ ] Merge real data from fetchers into the combined schema
- [ ] In SILE, use Lua to read and map JSON to section boxes:
  - [x] Access path via REPORT_DATA_JSON in a placeholder section
  - [ ] Load and parse JSON in Lua
  - [ ] Render section boxes from parsed data
- [ ] Insert SVG charts/images with proper scaling and low-ink palette

Ops & polish:
- [ ] .gitignore: data caches, output PDFs, local secrets
- [ ] Fail fast when APIs fail
- [ ] Unit tests for data transforms (Python)
- [ ] Performance: Parallel fetches, timeouts, retries with backoff

Notes/decisions:
- Low-color aesthetic: grayscale + one accent color
- Short sections can share a page via stacked boxes; avoid large white gaps
- Keep secrets out of the repo; prefer environment variables

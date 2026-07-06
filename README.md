# KhelaDekho API

Aggregator API for KhelaDekho. The same routes are available in two runtimes:

- **FastAPI app** (`app/`) — run locally or in Docker (uvicorn).
- **Cloudflare Worker** (`worker/src/index.js`, Hono) — deployed at the edge.

All endpoints return the standard envelope `{ success, data, error }` and require the
shared `xkey` header (proxy routes are exempt).

---

## Project Structure

```
KhelaDekho-API/
├── app/                          # FastAPI application
│   ├── __init__.py
│   ├── main.py                   # App factory: CORS, gzip, xkey auth, routers, /health
│   ├── config.py                 # Settings (single source of truth, env-driven)
│   ├── logging_config.py         # Environment-gated structlog setup
│   ├── dependencies/
│   │   ├── auth.py               # Shared xkey verification
│   │   └── rate_limit.py         # (removed - contact form only)
│   ├── middleware/
│   │   └── errors.py             # Global exception handlers
│   ├── models/                   # Pydantic response models
│   │   ├── __init__.py           # StandardResponse, HealthResponse
│   │   ├── goal_scores.py        # V1 score-provider models
│   │   ├── v2.py                 # V2/V5 match + TV channel models
│   │   └── v4.py                 # V4 channel models
│   ├── routes/                   # API routers (one per version)
│   │   ├── __init__.py
│   │   ├── v1.py                 # V1 score provider: scores, matches, player, team
│   │   ├── v2.py                 # V2 match-centric streams + proxy
│   │   ├── v4.py                 # V4 channel list, stream, stats, proxy
│   │   └── v5.py                 # V5 matches, TV channels (DLHD), stream, proxy
│   └── services/                 # Scraping / caching / resolution logic
│       ├── cache.py              # In-memory TTL cache + stampede protection
│       ├── v1.py                 # V1 score scraper (goal.com)
│       ├── channels.py           # V2 match/channel scraping + stream resolution + DRM
│       ├── v4.py                 # V4 channel/stream extraction (proxybdix)
│       └── v5.py                 # V5 match + TV channel resolution (DLHD)
├── worker/
│   ├── src/
│   │   └── index.js              # Cloudflare Worker (Hono) — same API at the edge
│   └── wrangler.toml             # Worker env vars, secrets, KV bindings
├── run.py                        # Local uvicorn entrypoint
├── requirements.txt
├── Dockerfile / docker-compose.yml
├── .env.example                  # Required environment variables
└── wrangler.toml                 # Root deploy config → worker/src/index.js
```

---

## API Versions

### V1 — Score Provider
Live football scores, fixtures, results and match/player/team detail. The provider
**base URL is configurable** via `V1_HOME_URL` — nothing is hardcoded.

| Endpoint | Description |
|----------|-------------|
| `GET /api/v1/health` | Health check |
| `GET /api/v1/scores` | Scores (filters: `date`, `competition`, `status=live\|result\|fixture`) |
| `GET /api/v1/competitions` | Competition list with match counts |
| `GET /api/v1/matches/{id}?slug=` | Match detail (events, lineups, stats, commentary) |
| `GET /api/v1/player/{id}` | Player profile + season stats |
| `GET /api/v1/team/{id}` | Team info + recent matches |

### V2 — Channel Provider (match-centric)
Matches are listed first; each match exposes its own channels, and a channel's
stream is resolved lazily on demand.

| Endpoint | Description |
|----------|-------------|
| `GET /api/v2/matches` | Match list (`?live=true` for live only) |
| `GET /api/v2/matches/{slug}/channels` | Channels for a match |
| `GET /api/v2/matches/{slug}/stream?ch={id}` | Resolve one channel's stream + DRM |
| `GET /api/v2/proxy?url=` | CORS/segment proxy |

### V4 — Channel Provider
| Endpoint | Description |
|----------|-------------|
| `GET /api/v4/health` | Health check |
| `GET /api/v4/channels` | Channel list |
| `GET /api/v4/channels/{id}` | Single channel |
| `GET /api/v4/channels/{id}/stream` | Stream URL + DRM keys |
| `GET /api/v4/proxy?url=` | CORS/segment proxy |
| `GET /api/v4/stats` | Platform metrics |

### V5 — Match-centric Streams + TV Channel List
Match-first API: list live/upcoming matches, then browse channels per match and
resolve streams on demand. Supports both TV channels and substreams.

Also provides a standalone DLHD 24/7 TV channel list (878+ channels) with auto-
categorization (Sports, News, Kids, Entertainment, Music, General).

| Endpoint | Description |
|----------|-------------|
| `GET /api/v5/matches` | Match list (football) |
| `GET /api/v5/matches/{slug}/channels` | Channels + substreams for a match |
| `GET /api/v5/matches/{slug}/stream?ch={id}` | Resolve one channel/substream |
| `GET /api/v5/tv/channels` | DLHD 24/7 TV channel list (878+ channels) |
| `GET /api/v5/tv/channel/{id}/stream` | Resolve a DLHD channel stream |
| `GET /api/v5/proxy?url=` | CORS/Referer proxy for TV manifests |

All v5 streams are routed through the proxy to keep Referer/Origin headers fresh
and rewrite tokenized manifests. TV channel streams have no rate limit.

---

## Configuration

Single source of truth: `app/config.py` (env prefix `KHELADEKHO_`). Provider and
auth keys use unprefixed aliases so they match the Worker and frontend.

| Variable | Purpose | Default |
|----------|---------|---------|
| `XKEY` | Shared API key (`xkey` header) | _(empty = auth disabled)_ |
| `V1_HOME_URL` | Score-provider base URL | — |
| `V2_HOME_URL` | V2 channel-provider base URL | — |
| `V4_HOME_URL` | V4 channel-provider base URL | — |
| `V5_HOME_URL` | V5 match-provider base URL | — |
| `PROXY_REQUIRED_PATTERNS` | Comma-sep domains/URLs that need proxying | `phantemlis.top,/papi/tv/playlist/` |
| `CACHE_INTERNAL_DOMAIN` | Internal domain for cache key partitioning | `kheladekho-cache.internal` |
| `KHELADEKHO_DEBUG` | Verbose console logging | `false` |
| `KHELADEKHO_LOG_LEVEL` | Log level in production | `INFO` |

All upstream base URLs come from env — no host is hardcoded in source.

Logging is environment-gated: human-readable console logs when `DEBUG=true`,
compact JSON at `LOG_LEVEL` otherwise. The Worker logs only when
`ENVIRONMENT=development`; production is silent.

---

## FastAPI (local / Docker)

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # set XKEY, V1_HOME_URL, V2_HOME_URL, V4_HOME_URL, V5_HOME_URL
uvicorn app.main:app --reload --port 8000
```

Or with Docker: `docker compose up --build`.

---

## Cloudflare Worker

The Worker is the production API (deployed at the edge). It serves the exact same
routes as the FastAPI app.

**Run locally** (Wrangler dev server on `http://localhost:8787`):

```bash
cd worker            # or run from the repo root (uses ./wrangler.toml)
npm install
npm run dev          # local dev at http://localhost:8787
```

Point the frontend at it during development by setting
`KHELADEKHO_API_URL=http://localhost:8787` in the frontend `.env.local`.

**Configure & deploy:**

```bash
# Set upstreams in wrangler.toml under [vars]:
#   V1_HOME_URL, V2_HOME_URL, V4_HOME_URL, V5_HOME_URL
# Optional: ENVIRONMENT = "development" for verbose local logs
wrangler secret put XKEY     # shared API key (never commit it)
npm run deploy
```

---


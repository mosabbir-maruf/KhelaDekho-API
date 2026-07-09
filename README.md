# KhelaDekho API

<p align="center">
  <img src="https://kheladekho.pages.dev/meta-graph.webp" alt="KhelaDekho" width="100%" />
</p>

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
│   └── wrangler.toml             # Worker env vars, secrets
├── run.py                        # Local uvicorn entrypoint
├── requirements.txt
├── Dockerfile / docker-compose.yml
├── .env.example                  # Required environment variables
└── wrangler.toml                 # Root deploy config (for CI/CD) → worker/src/index.js
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

The `?sport=` parameter accepts **12 sport slugs**: `football`, `cricket`,
`motorsports`, `basketball`, `fight`, `rugby`, `tennis`, `golf`,
`american-football`, `afl`, `volleyball`, and `24/7-streams` (24/7 animated
series & entertainment channels). The slug is URL-encoded before being sent
to the upstream provider.

The `24/7-streams` sport returns 4 channels (Family Guy, The Simpsons,
SpongeBob, Rally TV) after filtering out South Park and COWS. Poster images
are served by the frontend (Cloudflare Pages) from `/public/V5-24:7-Assets/`.

Also provides a standalone DLHD 24/7 TV channel list (878+ channels) with auto-
categorization (Sports, News, Kids, Entertainment, Music, General).

| Endpoint | Description |
|----------|-------------|
| `GET /api/v5/matches?sport=` | Match list (`?sport=football`, `?sport=cricket`, `?sport=24/7-streams`, etc.; defaults to football) |
| `GET /api/v5/matches/{slug}/channels?sport=` | Channels + substreams for a match |
| `GET /api/v5/matches/{slug}/stream?ch={id}&sport=` | Resolve one channel/substream |
| `GET /api/v5/tv/channels` | DLHD 24/7 TV channel list (878+ channels) |
| `GET /api/v5/tv/channel/{id}/stream` | Resolve a DLHD channel stream |
| `GET /api/v5/proxy?t=` | Token-based proxy (upstream URL hidden behind signed token) |

All v5 streams are routed through the proxy to keep Referer/Origin headers fresh
and rewrite tokenized manifests. TV channel streams have no rate limit.

**Proxy tokens are stateless and signed (HMAC-SHA256).** The stream endpoint
mints a token that embeds the upstream URL + a 24h expiry; the proxy verifies the
signature on every request with no shared in-memory state. This is required for
Cloudflare Workers, whose ephemeral, non-shared isolates would otherwise lose
per-isolate token maps and break live streams ("buffering after a while, fixed by
reload"). Tokens are valid on **any** isolate, so manifest reloads always resolve.

---

## Configuration

Single source of truth: `app/config.py`. All variables use their natural names
(`V1_HOME_URL`, `XKEY`, etc.) — no prefix — so they match the Worker and frontend.

| Variable | Purpose | Default |
|----------|---------|---------|
| `XKEY` | Shared API key (`xkey` header) | _(empty = auth disabled)_ |
| `PROXY_SECRET` | HMAC secret signing v5 proxy tokens | _(insecure dev fallback if unset)_ |
| `V1_HOME_URL` | Score-provider base URL | — |
| `V2_HOME_URL` | V2 channel-provider base URL | — |
| `V4_HOME_URL` | V4 channel-provider base URL | — |
| `V5_HOME_URL` | V5 match-provider base URL | — |
| `KHELADEKHO_DEBUG` | Verbose console logging | `false` |
| `KHELADEKHO_LOG_LEVEL` | Log level in production | `INFO` |

All upstream base URLs come from env — no host is hardcoded in source.

> **Cloudflare KV:** Only the frontend uses a KV namespace (`KHELA_SETTINGS`) for
> V3 playlist storage and admin settings. The API Worker does not bind any KV
> namespace — all caching is in-memory via `caches.default` and `cachetools.TTLCache`.

The Worker also uses these **hardcoded constants** (not env vars, defined in source):

| Constant | Location | Value |
|----------|----------|-------|
| `PROXY_REQUIRED_PATTERNS` | `worker:122` (`needsProxy`) | `phantemlis.top,/papi/tv/playlist/` |
| `CACHE_INTERNAL_DOMAIN` | `worker:120` (`cacheDomain`) | `kheladekho-cache.internal` |
| `_DECRYPT_KEY` | `channels.py:25` | `999999859198` |

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
cd worker
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
wrangler secret put XKEY         # shared API key (never commit it)
wrangler secret put PROXY_SECRET # HMAC secret for v5 proxy tokens (REQUIRED in prod)
npm run deploy
```

Generate a strong `PROXY_SECRET` (any of these; use a fresh, unique value):

```bash
openssl rand -hex 32
# or: node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
# or: python3 -c "import secrets; print(secrets.token_hex(32))"
```

If you run **both** the Worker and the Python backend, set the **same** `PROXY_SECRET`
on each — tokens signed by one must verify on the other.

---


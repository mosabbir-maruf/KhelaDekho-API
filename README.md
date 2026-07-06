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
├── app/                      # FastAPI application
│   ├── main.py               # App factory: CORS, gzip, xkey auth, routers, /health
│   ├── config.py             # Settings (single source of truth, env-driven)
│   ├── logging_config.py     # Environment-gated structlog setup
│   ├── dependencies/
│   │   ├── auth.py           # Shared xkey verification
│   │   └── rate_limit.py     # Sliding-window rate limiter
│   ├── middleware/
│   │   └── errors.py         # Global exception handlers
│   ├── models/               # Pydantic response models
│   │   ├── __init__.py       # StandardResponse, HealthResponse
│   │   ├── goal_scores.py    # V1 score-provider models
│   │   ├── v2.py             # V2 channel models
│   │   └── v4.py             # V4 channel models
│   ├── routes/               # API routers
│   │   ├── v1.py             # V1 score provider (scores, match/player/team)
│   │   ├── v2.py             # V2 channels, highlights, live matches, proxy
│   │   └── v4.py             # V4 channels, stream, stats, proxy
│   └── services/             # Scraping / caching logic
│       ├── cache.py          # In-memory TTL cache + stampede protection
│       ├── goal_scores.py    # V1 provider scraper (base URL from env)
│       ├── channels.py       # V2 channel/highlight extraction
│       ├── kickbd_matches.py # V2 live matches
│       └── proxybdix.py      # V4 channel/stream extraction
├── worker/
│   ├── src/index.js          # Cloudflare Worker (Hono) — same API at the edge
│   └── wrangler.toml         # Worker config
├── run.py                    # Local uvicorn entrypoint
├── requirements.txt
├── Dockerfile · docker-compose.yml
└── wrangler.toml             # Root worker deploy config (main -> worker/src/index.js)
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

### V2 — Channel Provider
| Endpoint | Description |
|----------|-------------|
| `GET /api/v2/channels` | Channel list |
| `GET /api/v2/channels/{id}` | Single channel |
| `GET /api/v2/highlights` | Highlights list |
| `GET /api/v2/highlights/{slug}` | Single highlight |
| `GET /api/v2/matches/live` | Live matches |
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
cp .env.example .env      # set XKEY, V1_HOME_URL, V2_HOME_URL, V4_HOME_URL
uvicorn app.main:app --reload --port 8000
```

Or with Docker: `docker compose up --build`.

---

## Cloudflare Worker

```bash
cd worker
npm install
npm run dev        # http://localhost:8787
npm run deploy
```

Set `V1_HOME_URL`, `V2_HOME_URL`, `V4_HOME_URL` in `wrangler.toml` under `[vars]`,
and the secret with `wrangler secret put XKEY`.

---

## Rate limiting

All endpoints use in-memory sliding-window rate limiting. The Worker can optionally
sync to a bound `KHELADEKHO_STORE` KV namespace for distributed limits.

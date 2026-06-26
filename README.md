# KhelaDekho API Worker

Cloudflare Worker-based scraper and stream decryption API for live sports channels. Deployed at Cloudflare's edge.

---

## File Structure

```text
kheladekho-api/
├── wrangler.toml            # Root Wrangler configuration
├── package.json             # NPM dependencies
└── worker/
    ├── wrangler.toml        # Worker-level Wrangler config
    ├── package.json         # Worker NPM dependencies
    └── src/
        └── index.js         # Hono router — all endpoints, caching, scraping
```

---

## Configuration

Set these variables in `wrangler.toml` under `[vars]` or in the Cloudflare Dashboard:

```toml
V1_HOME_URL = "https://example.com"
V2_HOME_URL = "https://example.com"
V4_HOME_URL = "https://example.com"
```

---

## Getting Started

```bash
cd worker
npm install
npm run dev
```

The worker runs at `http://localhost:8787`.

---

## Deploy

```bash
npm run deploy
```

---

## API Endpoints

All endpoints return a standard JSON envelope: `{ success, data, error }`.

### V1 — Legacy Scraper
| Endpoint | Description |
|----------|-------------|
| `GET /api/v1/health` | Health check |
| `GET /api/v1/matches` | Paginated match list |
| `GET /api/v1/matches/live` | Live matches only |
| `GET /api/v1/matches/:match_id` | Single match details |
| `GET /api/v1/channels` | Paginated channel list |
| `GET /api/v1/channels/live` | Active channels sorted by viewers |
| `GET /api/v1/stats` | Platform metrics |
| `GET /api/v1/channels/:channel_key/stream` | Decrypted stream URL + DRM keys |

### V2 — Kickbd
| Endpoint | Description |
|----------|-------------|
| `GET /api/v2/channels` | Channel list |
| `GET /api/v2/channels/:id` | Single channel details |
| `GET /api/v2/highlights` | Highlight list |
| `GET /api/v2/highlights/:slug` | Single highlight detail |
| `GET /api/v2/matches/live` | Live matches |
| `GET /api/v2/proxy?url=` | CORS proxy for stream segments |

### V4 — ProxyBDIX
| Endpoint | Description |
|----------|-------------|
| `GET /api/v4/health` | Health check |
| `GET /api/v4/channels` | Channel list |
| `GET /api/v4/channels/:channel_id` | Single channel |
| `GET /api/v4/channels/:channel_id/stream` | Stream URL + DRM keys |
| `GET /api/v4/proxy?url=` | CORS proxy for DASH/HLS segments |
| `GET /api/v4/stats` | Platform metrics |

---

## Rate Limiting

All endpoints are protected by in-memory rate limiting (configurable per-route). KV-backed rate limiting is available when `KHELADEKHO_STORE` KV namespace is bound.

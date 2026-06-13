# KhelaDekho Aggregator & Decryption API

A production-grade FastAPI-based proxy-scraping service and aggregator wrapper for `livekhela.tv` featuring dynamic caching, Redis-backed token bucket rate-limiting, centralized exception handling, standard JSON response envelopes, and cryptographic hotlink protection.

---

## File Structure Tree

```text
stream-api/
├── .env.example             # Example environment file template
├── Dockerfile               # Production Docker deployment script
├── docker-compose.yml       # Production-ready Compose setup
├── requirements.txt         # Python dependencies
├── run.py                   # Development entrypoint runner
├── test_parse.py            # Local parser debugger
├── test_production_api.py   # Automated production endpoints test suite
├── app/                     # FastAPI Application source
│   ├── __init__.py          # App package init
│   ├── config.py            # Pydantic Settings and configurations
│   ├── main.py              # Root router registrations, lifecycles, and routes
│   ├── dependencies/        # Route dependencies
│   │   ├── auth.py          # Cryptographic HMAC-SHA256 URL validator
│   │   └── rate_limit.py    # Redis & Memory token-bucket rate limiter
│   ├── middleware/          # HTTP request-response middlewares
│   │   └── errors.py        # Centralized exception response handlers
│   ├── models/              # Pydantic schema declarations
│   │   └── __init__.py      # Models and StandardResponse envelope definitions
│   ├── scrapers/            # Web scraping HTML single-pass parsers
│   │   └── __init__.py      # Parse logic for matches, channels, and stats
│   ├── services/            # Background business services
│   │   ├── cache.py         # Redis clustered & Local memory TTL cache service
│   │   └── scraper.py       # LiveKhelaScraper engine instance
│   ├── templates/           # Legacy template components
│   │   └── player.html      # Basic HTML fallback player template
│   └── utils/               # Internal utility modules
│       ├── __init__.py      # Safe parsing helper functions
│       └── http.py          # Shared HTTP Client engine & exponential retries
└── frontend/                # React + Vite Streaming dashboard client
    ├── package.json         # NPM manifest & dependencies
    ├── vite.config.js       # Vite build configurations with backend proxy
    ├── index.html           # SPA root HTML template
    └── src/                 # Client React components & styles
        ├── main.jsx         # Render entrypoint hooks
        ├── App.jsx          # Dashboard application container
        ├── index.css        # Glassmorphic cyber-punk styling rules
        └── components/      
            └── VideoPlayer.jsx # Shaka Player clearKey DRM controller
```

---

## Environment Setup (`.env`)

To configure the API, create a `.env` file in the root directory:

```env
# General Backend Settings
STREAMAPI_DEBUG=false
STREAMAPI_LOG_LEVEL=INFO
STREAMAPI_ALLOW_ORIGINS=["http://localhost:5173", "http://localhost:8000"]

# Cache & Connection Configurations
STREAMAPI_REDIS_URL=redis://localhost:6379/0
STREAMAPI_REQUEST_TIMEOUT=30.0
STREAMAPI_MATCH_CACHE_TTL=120
STREAMAPI_CHANNEL_CACHE_TTL=120

# Rate Limiter & Upstream Retry Limits
STREAMAPI_RATE_LIMIT_RPM=30
STREAMAPI_MAX_RETRIES=3
STREAMAPI_RETRY_BACKOFF=2.0

# Cryptographic Token Signing Key
STREAMAPI_SECRET_KEY=production-super-secret-key-fallback-change-me
STREAMAPI_SIGNATURE_WINDOW_SECONDS=60
```

---

## Getting Started

### Prerequisites
- Python 3.9+
- Node.js 18+ (for building React frontend)
- Redis Server (optional, falls back to memory automatically)

### 1. Build and Bundle Frontend
First, compile and package the React frontend:
```bash
cd frontend
npm install
npm run build
cd ..
```

### 2. Configure and Run Backend
Install python requirements and launch the FastAPI server:
```bash
pip install -r requirements.txt
python3 run.py
```
The application will run on `http://localhost:8000`. It automatically detects the compiled frontend in `frontend/dist` and serves it on the root URL `/`.

---

## Available API Endpoints

All endpoints are prefixed with `/api/v1` and are governed by standard rate-limiting.

### Operational Endpoints
* **`GET /api/v1/health`**
  - **Description**: Probe to check the health status of the application and metrics.
  - **Rate Limit**: 100 req/min.

### Sports & Match Endpoints
* **`GET /api/v1/matches`**
  - **Description**: Returns a paginated list of sports matches parsed from source.
  - **Query Params**:
    - `status` (string, optional): Filter by `live`, `upcoming`, or `finished`.
    - `group` (string, optional): Filter by group name (e.g. `Group A`).
    - `stage` (string, optional): Filter by tournament stage.
    - `limit` (integer, default 50): Number of matches to return (1-100).
    - `offset` (integer, default 0): Slicing offset.
* **`GET /api/v1/matches/{match_id}`**
  - **Description**: Returns details for a single match.
* **`GET /api/v1/matches/live`**
  - **Description**: Helper endpoint returning only currently live sports matches.
* **`GET /api/v1/groups`**
  - **Description**: Lists all parsed match group tags and their match counts.
* **`GET /api/v1/stages`**
  - **Description**: Lists all parsed tournament stage tags and their match counts.

### TV Channel & Streaming Endpoints
* **`GET /api/v1/channels`**
  - **Description**: Returns a paginated list of TV channels parsed from source.
  - **Query Params**:
    - `status` (string, optional): Filter by `live`, `down`, or `hidden`.
    - `category` (string, optional): Filter by category.
    - `limit` (integer, default 50): Number of items to return (1-100).
    - `offset` (integer, default 0): Slicing offset.
* **`GET /api/v1/channels/live`**
  - **Description**: Returns active live streaming channels sorted by current active viewer counts.
* **`GET /api/v1/stats`**
  - **Description**: Returns platform transmission metrics (views, active servers, channels, viewer peaks).
* **`GET /api/v1/channels/{channel_key}/stream`**
  - **Description**: Requests DRM licensing, ClearKeys parameters, and decrypts stream URL for a given channel.
  - **Headers Required**: Cryptographic signatures `X-Signature-Token` and `X-Signature-Timestamp` (see details below).
  - **Rate Limit**: 30 req/min.

---

## API Integration Guide (For Clients & Third-Party APIs)

All requests to the backend return a structured JSON envelope.

### Successful Response Envelope (`200 OK`)
```json
{
  "success": true,
  "data": {
    "key_1": "value_1"
  },
  "error": null,
  "meta": null
}
```

### Error Response Envelope
```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "HTTP_401",
    "message": "Secure session credentials missing",
    "details": null
  },
  "meta": null
}
```

---

### Connecting to the Hardened Stream Extraction Endpoint

The stream retrieval endpoint `/api/v1/channels/{channel_key}/stream` is cryptographically hardened. To fetch stream details, other services must include two HTTP Headers:
1. `X-Signature-Timestamp`: An integer epoch timestamp (seconds) representing request creation time.
2. `X-Signature-Token`: The computed SHA-256 HMAC signature of the payload.

#### Token Calculation Rule
The message to sign is constructed as:
```text
{X-Signature-Timestamp}:{Request_URL_Path}
```
**Example message to sign**: `1781371516:/api/v1/channels/wctveng/stream`

Below are code patterns to generate headers and fetch decrypted streams in various languages:

#### Node.js / JavaScript Example
```javascript
const crypto = require('crypto');
const axios = require('axios');

const secretKey = "production-super-secret-key-fallback-change-me"; // Keep in env
const channelKey = "wctveng";
const path = `/api/v1/channels/${channelKey}/stream`;
const baseUrl = "http://localhost:8000";

const timestamp = Math.floor(Date.now() / 1000).toString();
const message = `${timestamp}:${path}`;

const token = crypto
  .createHmac('sha256', secretKey)
  .update(message)
  .digest('hex');

axios.get(`${baseUrl}${path}`, {
  headers: {
    'X-Signature-Token': token,
    'X-Signature-Timestamp': timestamp
  }
})
.then(res => {
  console.log("Decrypted Stream Data:", res.data.data);
})
.catch(err => {
  console.error("Authentication failed:", err.response ? err.response.data : err.message);
});
```

#### Python Example
```python
import time
import hmac
import hashlib
import requests

secret_key = "production-super-secret-key-fallback-change-me"
channel_key = "wctveng"
path = f"/api/v1/channels/{channel_key}/stream"
base_url = "http://localhost:8000"

timestamp = str(int(time.time()))
message = f"{timestamp}:{path}".encode()

token = hmac.new(
    secret_key.encode(),
    message,
    hashlib.sha256
).hexdigest()

headers = {
    "X-Signature-Token": token,
    "X-Signature-Timestamp": timestamp
}

response = requests.get(f"{base_url}{path}", headers=headers)
print(response.json())
```

#### Shell / cURL Example
```bash
SECRET="production-super-secret-key-fallback-change-me"
TIMESTAMP=$(date +%s)
PATH_URI="/api/v1/channels/wctveng/stream"
BASE_URL="http://localhost:8000"

# Compute HMAC signature using openssl
MESSAGE="${TIMESTAMP}:${PATH_URI}"
TOKEN=$(echo -n "$MESSAGE" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')

curl -X GET "${BASE_URL}${PATH_URI}" \
  -H "X-Signature-Token: ${TOKEN}" \
  -H "X-Signature-Timestamp: ${TIMESTAMP}"
```

---

## Cloudflare Workers Deployment (Hono + Cheerio Version)

We have created an alternative **JavaScript Node-compatible Cloudflare Workers version** of this API under the `/worker` directory. This is optimized to run at Cloudflare's Edge locations with 0ms cold starts, and scale to millions of requests seamlessly.

### File Structure of Worker
- [worker/package.json](file:///Volumes/Mosabbir/Developement/Project/stream-api/worker/package.json) - Node dependencies for Worker.
- [worker/wrangler.toml](file:///Volumes/Mosabbir/Developement/Project/stream-api/worker/wrangler.toml) - Cloudflare wrangler configurations.
- [worker/src/index.js](file:///Volumes/Mosabbir/Developement/Project/stream-api/worker/src/index.js) - Complete Hono router logic, Cheerio scraper parsing, edge caching, rate limiting, and HMAC signature check.

### How to Run Locally (Worker)
1. Navigate into the worker directory:
   ```bash
   cd worker
   ```
2. Install npm dependencies:
   ```bash
   npm install
   ```
3. Run the wrangler development server:
   ```bash
   npm run dev
   ```
   The local edge server will run at `http://localhost:8787`.

### How to Deploy (Worker)
Log in to your Cloudflare account and deploy to your subdomain using:
```bash
npx wrangler login
npm run deploy
```


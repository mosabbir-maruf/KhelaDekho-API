import { Hono } from 'hono';
import { cors } from 'hono/cors';
import * as cheerio from 'cheerio';

const app = new Hono();

// Helper: Clean Whitespace
function cleanText(text) {
  if (!text) return '';
  return text.trim().replace(/\s+/g, ' ');
}

// Helper: Safe Int Parsing
function safeInt(value, def = 0) {
  if (!value) return def;
  const cleaned = value.toString().trim().replace(/,/g, '');
  const parsed = parseInt(cleaned, 10);
  return isNaN(parsed) ? def : parsed;
}

// Helper: Parse View Counts (K, M, B)
function parseViews(text) {
  if (!text) return 0;
  const val = text.trim().toUpperCase().replace(/,/g, '');
  try {
    if (val.endsWith('B')) return Math.floor(parseFloat(val.slice(0, -1)) * 1000000000);
    if (val.endsWith('M')) return Math.floor(parseFloat(val.slice(0, -1)) * 1000000);
    if (val.endsWith('K')) return Math.floor(parseFloat(val.slice(0, -1)) * 1000);
    return Math.floor(parseFloat(val)) || 0;
  } catch {
    return 0;
  }
}

// Standard Envelope Models
const makeResponse = (success, data = null, error = null) => ({
  success,
  data,
  error
});

// CORS Config
app.use('*', cors({
  origin: '*', // Can restrict to allowed origins via env
  allowMethods: ['GET', 'OPTIONS'],
  allowHeaders: ['X-Signature-Token', 'X-Signature-Timestamp', 'Content-Type', 'User-Agent']
}));

// Centralized Error Middleware
app.onError((err, c) => {
  console.error("Worker Execution Error:", err);
  
  let status = 500;
  let code = "INTERNAL_SERVER_ERROR";
  let message = "A critical system error occurred. Please try again later.";
  
  if (err.status) {
    status = err.status;
    code = `HTTP_${status}`;
    message = err.message || message;
  }
  
  return c.json(makeResponse(false, null, { code, message }), status);
});

// 404 Route handler
app.notFound((c) => {
  return c.json(makeResponse(false, null, {
    code: "NOT_FOUND",
    message: "Requested API resource not found."
  }), 404);
});

// Dynamic In-Memory sliding-window Rate Limiter (Fallback if KV Rate Limiting is unbound)
const rateLimitCache = new Map();
const rateLimiterMiddleware = (requests = 60, windowSecs = 60) => {
  return async (c, next) => {
    const ip = c.req.header('CF-Connecting-IP') || 'unknown';
    const path = new URL(c.req.url).pathname;
    const key = `rate:${ip}:${path}`;
    const now = Math.floor(Date.now() / 1000);
    
    // Check local memory first
    let clientHits = rateLimitCache.get(key) || [];
    clientHits = clientHits.filter(ts => ts > now - windowSecs);
    
    if (clientHits.length >= requests) {
      return c.json(makeResponse(false, null, {
        code: "HTTP_429",
        message: "Request rate limit exceeded. Please back off."
      }), 429);
    }
    
    clientHits.push(now);
    rateLimitCache.set(key, clientHits);
    
    // Optional: Sync rate limiting to Cloudflare KV for distributed check
    if (c.env.KHELADEKHO_STORE) {
      try {
        const kvKey = `rl:${ip}:${path}`;
        const raw = await c.env.KHELADEKHO_STORE.get(kvKey);
        let kvHits = raw ? JSON.parse(raw) : [];
        kvHits = kvHits.filter(ts => ts > now - windowSecs);
        
        if (kvHits.length >= requests) {
          return c.json(makeResponse(false, null, {
            code: "HTTP_429",
            message: "Request rate limit exceeded. Please back off."
          }), 429);
        }
        
        kvHits.push(now);
        await c.env.KHELADEKHO_STORE.put(kvKey, JSON.stringify(kvHits), { expirationTtl: windowSecs });
      } catch (err) {
        console.warn("KV rate limiting sync failed, falling back to local memory:", err);
      }
    }
    
    await next();
  };
};

// Cryptographic HMAC-SHA256 Signature Middleware (Anti-Hotlinking)
const verifySignature = async (c, next) => {
  const secret = c.env.KHELADEKHO_SECRET_KEY;
  if (!secret) {
    return c.json(makeResponse(false, null, {
      code: "HTTP_500",
      message: "Worker secret configuration missing"
    }), 500);
  }
  const windowSecs = parseInt(c.env.SIGNATURE_WINDOW_SECONDS || '60', 10);
  
  const token = c.req.header('X-Signature-Token');
  const timestampStr = c.req.header('X-Signature-Timestamp');
  
  if (!token || !timestampStr) {
    return c.json(makeResponse(false, null, {
      code: "HTTP_401",
      message: "Secure session credentials missing"
    }), 401);
  }
  
  const ts = parseInt(timestampStr, 10);
  if (isNaN(ts) || Math.abs(Math.floor(Date.now() / 1000) - ts) > windowSecs) {
    return c.json(makeResponse(false, null, {
      code: "HTTP_401",
      message: "Session signature expired"
    }), 401);
  }
  
  // Verify HMAC-SHA256
  const path = new URL(c.req.url).pathname;
  const message = `${timestampStr}:${path}`;
  
  const encoder = new TextEncoder();
  const keyData = encoder.encode(secret);
  const msgData = encoder.encode(message);
  
  const cryptoKey = await crypto.subtle.importKey(
    'raw',
    keyData,
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign', 'verify']
  );
  
  const signatureBuffer = await crypto.subtle.sign(
    'HMAC',
    cryptoKey,
    msgData
  );
  
  const hashArray = Array.from(new Uint8Array(signatureBuffer));
  const expectedToken = hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
  
  if (expectedToken !== token) {
    return c.json(makeResponse(false, null, {
      code: "HTTP_401",
      message: "Signature validation failed"
    }), 401);
  }
  
  await next();
};

// Browser-mimicking User-Agent rotation
const USER_AGENTS = [
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15',
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0',
  'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
];

let uaIndex = 0;

function nextUA() {
  const ua = USER_AGENTS[uaIndex];
  uaIndex = (uaIndex + 1) % USER_AGENTS.length;
  return ua;
}

function buildScrapeHeaders() {
  return {
    'User-Agent': nextUA(),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'cross-site',
    'Pragma': 'no-cache',
    'Cache-Control': 'no-cache',
  };
}

// Target Scraper Service
async function scrapeAll(targetUrl) {
  for (let attempt = 0; attempt < 2; attempt++) {
    const res = await fetch(targetUrl, { headers: buildScrapeHeaders() });
    if (!res.ok) {
      if (attempt === 1) throw new Error(`Target provider returned status ${res.status}`);
      continue;
    }
    const html = await res.text();
    const $ = cheerio.load(html);

    // 1. Matches Parsing
    const matches = [];
    const seenIds = new Set();

    $('.match-card[data-match-id], .match-card[data-match-status], div[data-match-id]').each((i, card) => {
      const $card = $(card);
      let matchId = $card.attr('data-match-id') || '';

      if (!matchId) {
        const rows = $card.find('.team-row');
        if (rows.length >= 2) {
          const t1 = cleanText($(rows[0]).find('.team-name, .mcard-team b, .mcard-team').text());
          const t2 = cleanText($(rows[1]).find('.team-name, .mcard-team b, .mcard-team').text());
          const startTs = $card.attr('data-start-ts') || $card.attr('data-start') || '0';
          const t1Slug = t1.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
          const t2Slug = t2.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
          matchId = `${t1Slug}-vs-${t2Slug}-${startTs}`;
        } else {
          return;
        }
      }

      if (seenIds.has(matchId)) return;
      seenIds.add(matchId);

      const rows = $card.find('.team-row');
      if (rows.length < 2) return;

      const team1Name = cleanText($(rows[0]).find('.team-name, .mcard-team b, .mcard-team').text());
      const team1Flag = $(rows[0]).find('img.flag, img.mcard-flag-img, .flag img, img[src*="flagcdn"]').attr('src') || null;
      const team2Name = cleanText($(rows[1]).find('.team-name, .mcard-team b, .mcard-team').text());
      const team2Flag = $(rows[1]).find('img.flag, img.mcard-flag-img, .flag img, img[src*="flagcdn"]').attr('src') || null;

      const startTs = safeInt($card.attr('data-start-ts') || $card.attr('data-start'), 0);
      const endTs = safeInt($card.attr('data-end-ts') || $card.attr('data-end'), 0);

      let status = $card.attr('data-match-status') || $card.attr('data-status') || 'upcoming';
      if (status === 'none' || !status) {
        if ($card.find('[data-mode="live"], .live-dot.green').length > 0) status = 'live';
        else if ($card.hasClass('live-row')) status = 'live';
        else if ($card.hasClass('is-finished')) status = 'finished';
      }

      matches.push({
        match_id: matchId,
        group: cleanText($card.find('.match-group').text()),
        stage: cleanText($card.find('[data-stage], .group-tag').text()) || 'Group Stage',
        team1: { name: team1Name, flag_url: team1Flag },
        team2: { name: team2Name, flag_url: team2Flag },
        start_time: startTs ? new Date(startTs * 1000).toISOString() : null,
        end_time: endTs ? new Date(endTs * 1000).toISOString() : null,
        status: status
      });
    });

    // 2. Channels Parsing
    let channels = [];
    const scriptRegex = /CHANNELS\s*=\s*(\[.+?\])\s*;/s;
    const scriptMatch = html.match(scriptRegex);
    if (scriptMatch) {
      try {
        const parsedData = JSON.parse(scriptMatch[1]);
        channels = parsedData.map(item => ({
          key: item.key || '',
          name: item.name || '',
          image_url: item.image || null,
          category: item.category || 'Sports',
          quality: item.quality || 'HD',
          status: item.status || 'live',
          sort_order: item.sort || 99,
          total_views: item.views || 0,
          live_viewers: item.live || 0,
          resolution: item.resolution || 'Auto',
          source_types: item.source_types || [],
          play_token: item.play_token || null,
          play_exp: item.play_exp || null,
          fetched_at: new Date().toISOString()
        })).filter(c => c.key);
      } catch (e) {
        console.warn("Failed to parse CHANNELS script array:", e);
      }
    }

    // 3. Platform Stats
    const liveViewers = safeInt($('[data-stats-live], #currentLiveCount, .watch-metric.live strong').text());
    const allViews = parseViews($('[data-stats-views], #currentViewCount, .watch-metric strong').text());
    const totalChannels = channels.length;

    return {
      matches,
      channels,
      platform_stats: {
        live_viewers: liveViewers,
        all_views: allViews,
        active_channels: totalChannels,
        total_channels: totalChannels,
        fetched_at: new Date().toISOString()
      },
      fetched_at: new Date().toISOString()
    };
  }
}

// Strip sensitive fields before returning channel data to clients
function sanitizeChannels(channels) {
  return channels.map(({ play_token, play_exp, ...rest }) => rest);
}

// Global lock to prevent cache stampedes
let scrapingPromise = null;

// Cache Stamede-Proof Getter using Cloudflare Cache API
async function getCachedScrape(c) {
  const targetUrl = c.env.KHELADEKHO_TARGET_URL;
  
  // Cloudflare native cache
  const cacheKey = new Request("http://kheladekho-cache.internal/data", { method: "GET" });
  const cache = caches.default;
  const cachedResponse = await cache.match(cacheKey);
  
  if (cachedResponse) {
    return await cachedResponse.json();
  }
  
  // If a scrape is already in progress, await it instead of launching another one
  if (scrapingPromise) {
    return await scrapingPromise;
  }
  
  // Fetch fresh with lock
  scrapingPromise = scrapeAll(targetUrl)
    .then(freshData => {
      // Store in cache for 120 seconds
      const responseToStore = new Response(JSON.stringify(freshData), {
        headers: {
          'Content-Type': 'application/json',
          'Cache-Control': 'max-age=120'
        }
      });
      c.executionCtx.waitUntil(cache.put(cacheKey, responseToStore));
      return freshData;
    })
    .finally(() => {
      scrapingPromise = null;
    });
    
  return await scrapingPromise;
}

// Endpoints: Root / Welcome
app.get('/', rateLimiterMiddleware(100, 60), (c) => {
  return c.json(makeResponse(true, {
    message: "Welcome to KhelaDekho API Cloudflare Worker!",
    endpoints: {
      health: "/api/v1/health",
      matches: "/api/v1/matches",
      channels: "/api/v1/channels",
      stats: "/api/v1/stats"
    }
  }));
});

// Alias: /health -> /api/v1/health
app.get('/health', (c) => c.redirect('/api/v1/health', 301));

// Endpoints: Root / Health check
app.get('/api/v1/health', rateLimiterMiddleware(100, 60), async (c) => {
  return c.json(makeResponse(true, {
    status: "ok",
    version: "1.0.0"
  }));
});

// Endpoints: List Matches
app.get('/api/v1/matches', rateLimiterMiddleware(100, 60), async (c) => {
  const statusFilter = c.req.query('status');
  const groupFilter = c.req.query('group');
  const stageFilter = c.req.query('stage');
  const limit = safeInt(c.req.query('limit'), 50);
  const offset = safeInt(c.req.query('offset'), 0);
  
  const scrape = await getCachedScrape(c);
  let matches = scrape.matches;
  
  if (statusFilter) {
    matches = matches.filter(m => m.status === statusFilter);
  }
  if (groupFilter) {
    const gLower = groupFilter.toLowerCase();
    matches = matches.filter(m => m.group && m.group.toLowerCase().includes(gLower));
  }
  if (stageFilter) {
    const sLower = stageFilter.toLowerCase();
    matches = matches.filter(m => m.stage && m.stage.toLowerCase().includes(sLower));
  }
  
  // Sort by start_time
  matches.sort((a, b) => new Date(a.start_time || '9999-12-31') - new Date(b.start_time || '9999-12-31'));
  
  const total = matches.length;
  const page = matches.slice(offset, offset + limit);
  
  return c.json(makeResponse(true, {
    matches: page,
    total,
    cached_at: scrape.fetched_at
  }));
});

// Endpoints: Live Matches Helper
app.get('/api/v1/matches/live', rateLimiterMiddleware(100, 60), async (c) => {
  const scrape = await getCachedScrape(c);
  const live = scrape.matches.filter(m => m.status === 'live');
  return c.json(makeResponse(true, {
    matches: live,
    total: live.length,
    cached_at: scrape.fetched_at
  }));
});

// Endpoints: Single Match
app.get('/api/v1/matches/:match_id', rateLimiterMiddleware(100, 60), async (c) => {
  const matchId = c.req.param('match_id');
  const scrape = await getCachedScrape(c);
  const match = scrape.matches.find(m => m.match_id === matchId);
  
  if (!match) {
    return c.json(makeResponse(false, null, {
      code: "HTTP_404",
      message: "Match not found"
    }), 404);
  }
  
  return c.json(makeResponse(true, match));
});

// Endpoints: List Channels
app.get('/api/v1/channels', rateLimiterMiddleware(100, 60), async (c) => {
  const statusFilter = c.req.query('status');
  const categoryFilter = c.req.query('category');
  const limit = safeInt(c.req.query('limit'), 50);
  const offset = safeInt(c.req.query('offset'), 0);
  
  const scrape = await getCachedScrape(c);
  let channels = scrape.channels;
  
  if (statusFilter) {
    channels = channels.filter(ch => ch.status === statusFilter);
  }
  if (categoryFilter) {
    const cLower = categoryFilter.toLowerCase();
    channels = channels.filter(ch => ch.category && ch.category.toLowerCase().includes(cLower));
  }
  
  channels.sort((a, b) => a.sort_order - b.sort_order);
  
  const total = channels.length;
  const page = channels.slice(offset, offset + limit);
  
  return c.json(makeResponse(true, {
    channels: sanitizeChannels(page),
    total,
    cached_at: scrape.fetched_at
  }));
});

// Endpoints: Live Channels Sorted by Viewers
app.get('/api/v1/channels/live', rateLimiterMiddleware(100, 60), async (c) => {
  const scrape = await getCachedScrape(c);
  const live = scrape.channels.filter(ch => ch.status === 'live');
  live.sort((a, b) => b.live_viewers - a.live_viewers || a.sort_order - b.sort_order);
  
  return c.json(makeResponse(true, {
    channels: sanitizeChannels(live),
    total: live.length,
    cached_at: scrape.fetched_at
  }));
});

// Endpoints: Platform Transmission Stats
app.get('/api/v1/stats', rateLimiterMiddleware(100, 60), async (c) => {
  const scrape = await getCachedScrape(c);
  return c.json(makeResponse(true, {
    stats: scrape.platform_stats,
    cached_at: scrape.fetched_at
  }));
});

// Endpoints: Stream Decrypter Helper
async function decodePayload(payload, accessToken) {
  try {
    // Support legacy string format
    if (typeof payload === 'string') {
      const reversed = payload.split('').reverse().join('');
      const raw = atob(reversed);
      return JSON.parse(raw);
    }
    
    // Support legacy/data wrapped format
    if (payload && typeof payload === 'object' && payload.legacy && payload.data) {
      const dataStr = payload.data;
      const reversed = dataStr.split('').reverse().join('');
      const raw = atob(reversed);
      return JSON.parse(raw);
    }
    
    // Support AES-GCM encrypted payload dictionary (v2)
    if (payload && typeof payload === 'object' && Number(payload.v) === 2) {
      if (!accessToken) {
        throw new Error("Access token is required for AES-GCM payload decryption");
      }
      
      const encoder = new TextEncoder();
      const tokenStr = String(accessToken || "");
      const keyData = encoder.encode(tokenStr + "|mlbd-web-stream-v2");
      const keyBuffer = await crypto.subtle.digest("SHA-256", keyData);
      
      const cryptoKey = await crypto.subtle.importKey(
        "raw",
        keyBuffer,
        { name: "AES-GCM" },
        false,
        ["decrypt"]
      );
      
      const b64urlDecode = (s) => {
        let str = s.replace(/-/g, '+').replace(/_/g, '/');
        while (str.length % 4) {
          str += '=';
        }
        const binary = atob(str);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) {
          bytes[i] = binary.charCodeAt(i);
        }
        return bytes;
      };
      
      const iv = b64urlDecode(payload.iv);
      const ct = b64urlDecode(payload.ct);
      const tag = b64urlDecode(payload.tag);
      
      // Concatenate ct and tag
      const cipherTextWithTag = new Uint8Array(ct.length + tag.length);
      cipherTextWithTag.set(ct);
      cipherTextWithTag.set(tag, ct.length);
      
      const decryptedBuffer = await crypto.subtle.decrypt(
        {
          name: "AES-GCM",
          iv: iv,
          tagLength: 128
        },
        cryptoKey,
        cipherTextWithTag
      );
      
      const textDecoder = new TextDecoder("utf-8");
      const plainText = textDecoder.decode(decryptedBuffer);
      return JSON.parse(plainText);
    }
    
    throw new Error("Unsupported payload format or version");
  } catch (e) {
    console.error("Payload decoding failed:", e);
    throw new Error("Failed to decode stream payload: " + e.message);
  }
}

// Endpoints: Get Decrypted Channel Stream (Rate-limited, cryptographically verified)
app.get('/api/v1/channels/:channel_key/stream', rateLimiterMiddleware(30, 60), verifySignature, async (c) => {
  const channelKey = c.req.param('channel_key');
  const scrape = await getCachedScrape(c);
  const channel = scrape.channels.find(ch => ch.key === channelKey);
  
  if (!channel) {
    return c.json(makeResponse(false, null, { code: "HTTP_404", message: "Channel not found" }), 404);
  }
  if (!channel.play_token) {
    return c.json(makeResponse(false, null, { code: "HTTP_400", message: "DRM credentials not configured for this channel" }), 400);
  }
  
  // Edge Cache check for the decrypted URL payload (30 seconds)
  const streamCacheKey = new Request(`http://kheladekho-cache.internal/stream/${channelKey}`, { method: "GET" });
  const cache = caches.default;
  const cachedStream = await cache.match(streamCacheKey);
  if (cachedStream) {
    return c.json(makeResponse(true, await cachedStream.json()));
  }
  
  // Post target request
  try {
    const targetUrl = c.env.KHELADEKHO_TARGET_URL;
    const baseUrl = targetUrl.replace(/\/+$/, '');
    const res = await fetch(`${baseUrl}/api/channel`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
        'Origin': baseUrl,
        'Referer': `${baseUrl}/`,
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0'
      },
      body: new URLSearchParams({
        key: channel.key,
        access: channel.play_token
      })
    });
    
    if (!res.ok) throw new Error("Upstream stream provider server returned status " + res.status);
    const respJson = await res.json();
    
    if (!respJson.success || !respJson.payload) {
      return c.json(makeResponse(false, null, {
        code: "HTTP_502",
        message: respJson.message || "Failed to fetch stream details from upstream source"
      }), 502);
    }
    
    const decoded = await decodePayload(respJson.payload, channel.play_token);
    
    const responseData = {
      key: channel.key,
      name: channel.name,
      url: decoded.url || '',
      type: decoded.type || 'dash',
      drm: decoded.drm || null,
      clearkey: decoded.clearkey || null,
      sources: decoded.sources || [],
      expires_at: decoded.exp ? new Date(decoded.exp * 1000).toISOString() : null
    };
    
    // Store in stream cache for 30 seconds
    const streamCacheResponse = new Response(JSON.stringify(responseData), {
      headers: { 'Content-Type': 'application/json', 'Cache-Control': 'max-age=30' }
    });
    c.executionCtx.waitUntil(cache.put(streamCacheKey, streamCacheResponse));
    
    return c.json(makeResponse(true, responseData));
  } catch (err) {
    console.error("Upstream stream decryption request failed:", err);
    return c.json(makeResponse(false, null, {
      code: "HTTP_502",
      message: "Upstream stream connection error: " + err.message
    }), 502);
  }
});

export default app;

// =========================================================================
// V2 Optimized Helpers & Routes
// =========================================================================

// --- Shared Constants ---
const SPORTZFY_PLAYBACK_KEY = 'ZESBtSlRTuF4Ac4k757OuasOWOA0W8LcqRn3SFgdInDoMyS8';
const SPORTZFY_TARGET_URL = 'https://sportzfytvlive.xyz';
const KICKBD_HOME = 'https://kickbd.org';

// --- Concurrent Batch Processor ---
async function concurrentMap(items, fn, concurrency = 5) {
  const results = [];
  const queue = [...items];
  async function worker() {
    while (queue.length > 0) {
      const item = queue.shift();
      results.push(await fn(item));
    }
  }
  const count = Math.min(concurrency, items.length);
  if (count === 0) return results;
  await Promise.all(Array.from({ length: count }, () => worker()));
  return results;
}

// --- Unified Cache helper with stampede protection ---
const fetchPromises = new Map();
async function getCachedOrFetch(c, key, fetchFn, ttl) {
  const cache = caches.default;
  const cacheReq = new Request(`http://kheladekho-cache.internal/v2/${key}`);
  const hit = await cache.match(cacheReq);

  // Serve any cached response immediately (fresh or stale)
  if (hit) {
    // Check if still fresh
    const dateHeader = hit.headers.get('x-cache-date');
    const cachedAt = dateHeader ? parseInt(dateHeader, 10) : 0;
    const age = Date.now() - cachedAt;
    if (age < ttl * 1000) return await hit.json(); // Fresh

    // Stale: serve immediately, re-fetch in background
    c.executionCtx.waitUntil(
      (async () => {
        if (fetchPromises.has(key)) return;
        const p = fetchFn().then(data => {
          const res = new Response(JSON.stringify(data), {
            headers: {
              'Content-Type': 'application/json',
              'Cache-Control': `max-age=${ttl}`,
              'x-cache-date': String(Date.now())
            }
          });
          return cache.put(cacheReq, res);
        }).finally(() => fetchPromises.delete(key));
        fetchPromises.set(key, p);
        await p;
      })()
    );
    return await hit.json();
  }

  if (fetchPromises.has(key)) return await fetchPromises.get(key);

  const promise = fetchFn()
    .then(data => {
      const res = new Response(JSON.stringify(data), {
        headers: {
          'Content-Type': 'application/json',
          'Cache-Control': `max-age=${ttl}`,
          'x-cache-date': String(Date.now())
        }
      });
      c.executionCtx.waitUntil(cache.put(cacheReq, res));
      return data;
    })
    .finally(() => fetchPromises.delete(key));

  fetchPromises.set(key, promise);
  return await promise;
}

// --- Status computation (extracted, no redefinition each call) ---
function computeEventStatus(startsAt, now) {
  if (!startsAt) return 'upcoming';
  const ts = Math.floor(new Date(startsAt).getTime() / 1000);
  if (ts <= now + 300 && ts > now - 3600) return 'live';
  if (ts > now + 300 && ts <= now + 64800) return 'upcoming';
  if (ts < now - 3600) return 'finished';
  return 'upcoming';
}

// --- AES-GCM Decryption (Sportzfy playback) ---
async function sportzfyDecrypt(encStr, bucket, playbackKey) {
  const encoder = new TextEncoder();
  const keyHash = await crypto.subtle.digest('SHA-256', encoder.encode(`${playbackKey}|lsp-v1|${bucket}`));
  const cryptoKey = await crypto.subtle.importKey('raw', keyHash, { name: 'AES-GCM' }, false, ['decrypt']);
  const raw = Uint8Array.from(atob(encStr), c => c.charCodeAt(0));
  const plain = await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: raw.slice(0, 12), tagLength: 128 },
    cryptoKey,
    raw.slice(12)
  );
  return JSON.parse(new TextDecoder().decode(plain));
}

// --- Kickbd XOR decryption ---
function kickbdDecrypt(payloadUrlEnc) {
  const decoded = decodeURIComponent(payloadUrlEnc);
  const k = "999999859198";
  let r = "";
  for (let i = 0; i < decoded.length; i++) {
    r += String.fromCharCode((decoded.charCodeAt(i) + 5) ^ parseInt(k[i % k.length]));
  }
  return r;
}

// --- Unified fetch helper (no duplicate UA strings) ---
async function fetchText(url, headers = {}) {
  const res = await fetch(url, {
    headers: {
      'User-Agent': nextUA(),
      'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
      'Accept-Language': 'en-US,en;q=0.9',
      ...headers
    }
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return await res.text();
}

// =========================================================================
// Sportzfy Helpers
// =========================================================================

async function fetchSportzfyEvents(targetUrl) {
  const base = targetUrl.replace(/\/+$/, '');
  const json = await fetchText(`${base}/api/upstream/events`, { 'Accept': 'application/json' });
  const rawEvents = JSON.parse(json).events || [];
  const now = Math.floor(Date.now() / 1000);

  return rawEvents.filter(e => e && e.id).map(e => {
    const startsAt = e.starts_at ? e.starts_at.replace('Z', '+00:00') : null;
    const status = computeEventStatus(startsAt, now);
    return {
      id: e.id,
      parent: e.parent || e.id,
      enc_parent: e.enc_parent || e.parent || e.id,
      sport: e.sport || 'Sports',
      league: e.league || '',
      round: e.round || '',
      team_a: { name: e.team_a_name || 'Team A', logo: e.team_a_logo || null },
      team_b: { name: e.team_b_name || 'Team B', logo: e.team_b_logo || null },
      starts_at: startsAt,
      is_live: status === 'live' || Boolean(e.is_live),
      status,
      league_icon: e.league_icon || null,
      priority: e.priority || 0,
      fetched_at: new Date().toISOString()
    };
  });
}

async function fetchSportzfyPlayback(parent, targetUrl) {
  const base = targetUrl.replace(/\/+$/, '');
  let body;
  try {
    body = JSON.parse(await fetchText(`${base}/api/upstream/playback/${parent}`, {
      'Accept': 'application/json',
      'X-Requested-With': 'lsp'
    }));
  } catch (e) {
    return { ok: false, parent, streams: [] };
  }

  if (body && body.enc) {
    try {
      body = await sportzfyDecrypt(body.enc, body.bucket || 0, SPORTZFY_PLAYBACK_KEY);
    } catch (e) {
      return { ok: false, parent, streams: [] };
    }
  }

  const ok = body && body.ok;
  const rawStreams = body && body.streams ? body.streams : [];

  // Parallel stream verification
  const verifyHeaders = {
    'User-Agent': nextUA(),
    'Accept': '*/*',
    'Referer': `${base}/`
  };

  const streamChecks = rawStreams.map(async (s, i) => {
    const streamUrl = s.stream_url || '';
    if (!streamUrl) return null;
    const drmKid = s.drm_kid || null;
    const drmKey = s.drm_key || null;
    const hasDrm = !!(drmKid && drmKey);
    const isDrmDash = hasDrm && s.stream_type === 'dash';
    let alive = false;
    try {
      const resp = await fetch(streamUrl, { headers: verifyHeaders, redirect: 'follow' });
      alive = resp.ok || (isDrmDash && resp.status === 403);
    } catch (e) { /* not alive */ }
    if (!alive) return null;
    return {
      id: s.id || String(i),
      label: s.label || `Server ${i + 1}`,
      stream_type: s.stream_type || 'hls',
      stream_url: streamUrl,
      drm_kid: drmKid,
      drm_key: drmKey,
      sort_order: s.sort_order !== undefined ? s.sort_order : i
    };
  });

  const streams = (await Promise.all(streamChecks))
    .filter(Boolean)
    .sort((a, b) => a.sort_order - b.sort_order);

  return { ok: ok && streams.length > 0, parent, streams };
}

// =========================================================================
// Kickbd Helpers
// =========================================================================

async function processChannel(ch) {
  let iframeUrl = null;
  try {
    const watchHtml = await fetchText(`${KICKBD_HOME}/watch/${ch.id}`);
    const iframeMatch = watchHtml.match(/<iframe[^>]*src=["']([^"']+)["'][^>]*>/);
    if (iframeMatch) iframeUrl = iframeMatch[1];
  } catch (e) { /* skip */ }

  let streamData = null;
  if (iframeUrl) {
    if (iframeUrl.includes('kickbd.org/source/')) {
      try {
        const srcHtml = await fetchText(iframeUrl);
        const pMatch = srcHtml.match(/var _p\s*=\s*"([^"]+)"/);
        if (pMatch) {
          const decrypted = kickbdDecrypt(pMatch[1]);
          const urlMatch = decrypted.match(/window\.player\.load\('([^']+)'\)/);
          const kidMatch = decrypted.match(/k_id='([^']+)'/);
          const kvMatch = decrypted.match(/k_v='([^']+)'/);
          if (urlMatch) {
            streamData = {
              stream_url: urlMatch[1],
              stream_type: urlMatch[1].includes('.mpd') ? 'dash' : 'hls',
              drm_kid: kidMatch ? kidMatch[1] : null,
              drm_key: kvMatch ? kvMatch[1] : null
            };
          }
        }
      } catch (e) { /* skip */ }
    } else if (iframeUrl.includes('kick.yagaverse.net')) {
      try {
        const yHtml = await fetchText(iframeUrl);
        const sMatch = yHtml.match(/const streamUrl\s*=\s*'([^']+)'/) ||
          yHtml.match(/source:\s*'([^']+)'/) ||
          yHtml.match(/file:\s*'([^']+)'/) ||
          yHtml.match(/https?:\/\/[^"'\s>]+\.m3u8[^"'\s>]*/);
        if (sMatch) {
          const url = sMatch[1] || sMatch[0];
          streamData = { stream_url: url, stream_type: 'hls' };
        }
      } catch (e) { /* skip */ }
    } else if (iframeUrl.includes('soccerball.st')) {
      try {
        const sHtml = await fetchText(iframeUrl);
        const proxyMatch = sHtml.match(/https?:\/\/[^"'<>\s]+s\d+\.php[^"'<>\s]*/);
        if (proxyMatch) {
          // Return the s1.php URL directly so the proxy resolves it live
          streamData = { stream_url: proxyMatch[0], stream_type: 'hls' };
        }
      } catch (e) { /* skip */ }
    } else {
      // Generic handler for all other iframe types (also covers kickbd.org/player/)
      try {
        const pHtml = await fetchText(iframeUrl);
        const urlMatch = pHtml.match(/https?:\/\/[^"'<>\s]+\.(?:m3u8|mpd)[^"'<>\s]*/);
        if (urlMatch) {
          streamData = {
            stream_url: urlMatch[0],
            stream_type: urlMatch[0].includes('.mpd') ? 'dash' : 'hls'
          };
        }
      } catch (e) { /* skip */ }
    }
  }

  return {
    id: ch.id,
    name: ch.name,
    logo: ch.logo,
    stream_type: streamData ? streamData.stream_type : 'hls',
    stream_url: streamData ? streamData.stream_url : null,
    drm_kid: streamData ? (streamData.drm_kid || null) : null,
    drm_key: streamData ? (streamData.drm_key || null) : null,
    is_alive: !!streamData,
    cached_at: new Date().toISOString()
  };
}

async function fetchKickbdChannels() {
  const html = await fetchText(KICKBD_HOME);
  const $ = cheerio.load(html);
  const seen = new Set();
  const channels = [];
  $('a[href*="/watch/"]').each((i, el) => {
    const href = $(el).attr('href') || '';
    const match = href.match(/\/watch\/(\d+)/);
    if (!match) return;
    const id = parseInt(match[1], 10);
    if (seen.has(id)) return;
    seen.add(id);
    const img = $(el).find('img');
    const name = img.attr('alt') || $(el).text().trim() || 'Channel ' + id;
    const logo = img.attr('src') || null;
    channels.push({ id, name, logo });
  });

  // Parallel processing with concurrency=3 to avoid rate limiting
  return await concurrentMap(channels, processChannel, 3);
}

async function processHighlight(slug) {
  let detail = { slug, title: slug, stream_url: null, sources: [], is_alive: false };
  try {
    const detailHtml = await fetchText(`${KICKBD_HOME}/highlights/${slug}`);
    const titleMatch = detailHtml.match(/<title[^>]*>(.*?)<\/title>/);
    if (titleMatch) detail.title = titleMatch[1].replace(' || KicKBD.Com', '').trim();
    const iframeMatch = detailHtml.match(/<iframe[^>]*src=["']([^"']+)["'][^>]*>/);
    if (iframeMatch) {
      const streamUrl = iframeMatch[1];
      if (streamUrl.includes('cdn.kickbd.org/stream.php')) {
        try {
          const innerHtml = await fetchText(streamUrl);
          const payloadMatch = innerHtml.match(/securePayload\s*=\s*"([^"]+)"/);
          if (payloadMatch) {
            const decodedUrl = atob(payloadMatch[1]);
            const playerHtml = await fetchText(decodedUrl);
            const sourcesRaw = [...playerHtml.matchAll(/\{"label":"([^"]+)","type":"[^"]+","file":"([^"]+)"[^}]*\}/g)];
            if (sourcesRaw.length > 0) {
              detail.sources = sourcesRaw.map(sr => ({ label: sr[1], url: sr[2] }));
              detail.stream_url = sourcesRaw[0][2];
              detail.is_alive = true;
            }
          }
        } catch (e) { /* expired or unavailable */ }
      } else {
        detail.stream_url = streamUrl;
        detail.is_alive = true;
      }
    }
  } catch (e) { /* skip */ }
  return detail;
}

async function fetchKickbdHighlights() {
  const html = await fetchText(KICKBD_HOME);
  const slugSet = new Set();
  const slugRegex = /href=["']https:\/\/kickbd\.com\/highlights\/([^"']+)["'][^>]*>/g;
  let m;
  while ((m = slugRegex.exec(html)) !== null) slugSet.add(m[1]);

  // Parallel processing with concurrency=5
  return await concurrentMap([...slugSet], processHighlight, 5);
}

// =========================================================================
// V2 Routes
// =========================================================================

app.get('/api/v2/health', rateLimiterMiddleware(100, 60), (c) => {
  return c.json(makeResponse(true, {
    status: 'ok', version: '2.0.0', source: 'sportzfytvlive.xyz'
  }));
});

// --- Sportzfy Events ---
app.get('/api/v2/events', rateLimiterMiddleware(100, 60), async (c) => {
  const targetUrl = c.env.SPORTZFY_TARGET_URL || SPORTZFY_TARGET_URL;
  const events = await getCachedOrFetch(c, 'sportzfy_events',
    () => fetchSportzfyEvents(targetUrl), 600);
  const sport = c.req.query('sport');
  const league = c.req.query('league');
  const statusFilter = c.req.query('status');
  const q = c.req.query('q');
  const limit = Math.min(safeInt(c.req.query('limit'), 50), 100);
  const offset = safeInt(c.req.query('offset'), 0);

  let filtered = events;
  if (sport) { const s = sport.toLowerCase(); filtered = filtered.filter(e => e.sport.toLowerCase() === s); }
  if (league) { const l = league.toLowerCase(); filtered = filtered.filter(e => e.league.toLowerCase().includes(l)); }
  if (statusFilter) filtered = filtered.filter(e => e.status === statusFilter);
  if (q) {
    const query = q.toLowerCase();
    filtered = filtered.filter(e =>
      e.team_a.name.toLowerCase().includes(query) ||
      e.team_b.name.toLowerCase().includes(query) ||
      e.league.toLowerCase().includes(query) ||
      e.sport.toLowerCase().includes(query)
    );
  }

  filtered.sort((a, b) => a.priority - b.priority || new Date(a.starts_at || '9999-12-31') - new Date(b.starts_at || '9999-12-31'));
  const total = filtered.length;
  const page = filtered.slice(offset, offset + limit);
  return c.json(makeResponse(true, { events: page, total, cached_at: new Date().toISOString() }));
});

app.get('/api/v2/events/live', rateLimiterMiddleware(100, 60), async (c) => {
  const targetUrl = c.env.SPORTZFY_TARGET_URL || SPORTZFY_TARGET_URL;
  const events = await getCachedOrFetch(c, 'sportzfy_events',
    () => fetchSportzfyEvents(targetUrl), 600);
  const live = events.filter(e => e.status === 'live').sort((a, b) => a.priority - b.priority);
  return c.json(makeResponse(true, { events: live, total: live.length, cached_at: new Date().toISOString() }));
});

app.get('/api/v2/events/upcoming', rateLimiterMiddleware(100, 60), async (c) => {
  const targetUrl = c.env.SPORTZFY_TARGET_URL || SPORTZFY_TARGET_URL;
  const events = await getCachedOrFetch(c, 'sportzfy_events',
    () => fetchSportzfyEvents(targetUrl), 600);
  const upcoming = events.filter(e => e.status === 'upcoming').sort((a, b) => a.priority - b.priority);
  return c.json(makeResponse(true, { events: upcoming, total: upcoming.length, cached_at: new Date().toISOString() }));
});

app.get('/api/v2/events/:event_id', rateLimiterMiddleware(100, 60), async (c) => {
  const targetUrl = c.env.SPORTZFY_TARGET_URL || SPORTZFY_TARGET_URL;
  const events = await getCachedOrFetch(c, 'sportzfy_events',
    () => fetchSportzfyEvents(targetUrl), 600);
  const eventId = c.req.param('event_id');
  const event = events.find(e => e.id === eventId || e.enc_parent === eventId || e.parent === eventId);
  if (!event) return c.json(makeResponse(false, null, { code: 'HTTP_404', message: 'Event not found' }), 404);
  return c.json(makeResponse(true, event));
});

// --- Sportzfy Playback ---
app.get('/api/v2/events/:event_id/playback', rateLimiterMiddleware(100, 60), async (c) => {
  const targetUrl = c.env.SPORTZFY_TARGET_URL || SPORTZFY_TARGET_URL;
  const events = await getCachedOrFetch(c, 'sportzfy_events',
    () => fetchSportzfyEvents(targetUrl), 600);
  const eventId = c.req.param('event_id');
  const event = events.find(e => e.id === eventId || e.enc_parent === eventId || e.parent === eventId);
  if (!event) return c.json(makeResponse(false, null, { code: 'HTTP_404', message: 'Event not found' }), 404);
  if (!event.parent) return c.json(makeResponse(false, null, { code: 'HTTP_400', message: 'Event has no playback identifier' }), 400);

  const parent = event.parent;
  const playback = await getCachedOrFetch(c, `sportzfy_playback_${parent}`,
    () => fetchSportzfyPlayback(parent, targetUrl), 120);
  if (!playback.ok || !playback.streams || playback.streams.length === 0) {
    return c.json(makeResponse(false, null, { code: 'HTTP_502', message: 'No streams available' }), 502);
  }
  return c.json(makeResponse(true, playback));
});

// --- Sportzfy Sports ---
app.get('/api/v2/sports', rateLimiterMiddleware(100, 60), async (c) => {
  const targetUrl = c.env.SPORTZFY_TARGET_URL || SPORTZFY_TARGET_URL;
  const events = await getCachedOrFetch(c, 'sportzfy_events',
    () => fetchSportzfyEvents(targetUrl), 600);
  const counts = {};
  events.forEach(e => { const s = e.sport || 'Unknown'; counts[s] = (counts[s] || 0) + 1; });
  const sports = Object.entries(counts).map(([name, event_count]) => ({ name, event_count }))
    .sort((a, b) => b.event_count - a.event_count);
  return c.json(makeResponse(true, { sports }));
});

// --- Sportzfy Leagues ---
app.get('/api/v2/leagues', rateLimiterMiddleware(100, 60), async (c) => {
  const targetUrl = c.env.SPORTZFY_TARGET_URL || SPORTZFY_TARGET_URL;
  const events = await getCachedOrFetch(c, 'sportzfy_events',
    () => fetchSportzfyEvents(targetUrl), 600);
  const counts = {};
  events.forEach(e => { const l = e.league || 'Unknown'; counts[l] = (counts[l] || 0) + 1; });
  const leagues = Object.entries(counts).map(([name, event_count]) => ({ name, event_count }))
    .sort((a, b) => b.event_count - a.event_count);
  return c.json(makeResponse(true, { leagues }));
});

// --- Sportzfy Stats ---
app.get('/api/v2/stats', rateLimiterMiddleware(100, 60), async (c) => {
  const targetUrl = c.env.SPORTZFY_TARGET_URL || SPORTZFY_TARGET_URL;
  const events = await getCachedOrFetch(c, 'sportzfy_events',
    () => fetchSportzfyEvents(targetUrl), 600);
  return c.json(makeResponse(true, {
    total_events: events.length,
    live_events: events.filter(e => e.status === 'live').length,
    upcoming_events: events.filter(e => e.status === 'upcoming').length,
    sports_count: [...new Set(events.map(e => e.sport))].length,
    leagues_count: [...new Set(events.map(e => e.league))].length,
    cached_at: new Date().toISOString()
  }));
});

// --- Kickbd Channels ---
app.get('/api/v2/channels', rateLimiterMiddleware(100, 60), async (c) => {
  const channels = await getCachedOrFetch(c, 'kickbd_channels_v2',
    () => fetchKickbdChannels(), 1800);
  const q = c.req.query('q');
  const aliveOnly = c.req.query('alive') === 'true';
  let filtered = channels;
  if (aliveOnly) filtered = filtered.filter(ch => ch.is_alive);
  if (q) { const query = q.toLowerCase(); filtered = filtered.filter(ch => ch.name.toLowerCase().includes(query)); }
  return c.json(makeResponse(true, { channels: filtered, total: filtered.length, cached_at: new Date().toISOString() }));
});

app.get('/api/v2/channels/:channel_id', rateLimiterMiddleware(100, 60), async (c) => {
  const channels = await getCachedOrFetch(c, 'kickbd_channels_v2',
    () => fetchKickbdChannels(), 1800);
  const channelId = parseInt(c.req.param('channel_id'), 10);
  const channel = channels.find(ch => ch.id === channelId);
  if (!channel) return c.json(makeResponse(false, null, { code: 'HTTP_404', message: 'Channel not found' }), 404);
  return c.json(makeResponse(true, channel));
});

// --- Kickbd Highlights ---
app.get('/api/v2/highlights', rateLimiterMiddleware(100, 60), async (c) => {
  const highlights = await getCachedOrFetch(c, 'kickbd_highlights',
    () => fetchKickbdHighlights(), 1800);
  return c.json(makeResponse(true, { highlights, total: highlights.length, cached_at: new Date().toISOString() }));
});

app.get('/api/v2/highlights/:slug', rateLimiterMiddleware(100, 60), async (c) => {
  const highlights = await getCachedOrFetch(c, 'kickbd_highlights',
    () => fetchKickbdHighlights(), 1800);
  const slug = c.req.param('slug');
  const highlight = highlights.find(h => h.slug === slug);
  if (!highlight) return c.json(makeResponse(false, null, { code: 'HTTP_404', message: 'Highlight not found' }), 404);
  return c.json(makeResponse(true, highlight));
});

// --- Kickbd Live Matches ---
async function fetchKickbdMatches() {
  const html = await fetchText(KICKBD_HOME);
  const matches = [];
  const now = Date.now();

  const blocks = html.split(/<div\s+class="event-card"/);
  for (let i = 1; i < blocks.length; i++) {
    const chunk = blocks[i];
    const linkMatch = chunk.match(/data-link="([^"]+)"/);
    const timeMatch = chunk.match(/data-utc-time="([^"]+)"/);
    if (!linkMatch || !timeMatch) continue;

    const matchUrl = linkMatch[1];
    const startsAt = new Date(timeMatch[1]);
    if (isNaN(startsAt.getTime())) continue;

    const matchSlug = matchUrl.split('/').pop();

    const badgeMatch = chunk.match(/<div\s+class="sport-name-badge">\s*<span>([^<]*)<\/span>\s*<span\s+class="title-text">\s*([^<]*?)\s*<\/span>/);
    let sportEmoji = '', league = '';
    if (badgeMatch) {
      sportEmoji = badgeMatch[1].trim();
      league = badgeMatch[2].trim();
    }

    const teamRows = [...chunk.matchAll(/<div\s+class="fixture-team-row">\s*<div\s+class="fixture-logo-box">\s*<img\s+src="([^"]+)"\s+alt="([^"]+)"/g)];
    if (teamRows.length < 2) continue;

    const expireTime = startsAt.getTime() + 6 * 3600 * 1000;
    const isLive = startsAt.getTime() <= now && now < expireTime;

    matches.push({
      id: matchSlug,
      league,
      sport_emoji: sportEmoji,
      team_a: { name: teamRows[0][2].trim(), logo: teamRows[0][1] || null },
      team_b: { name: teamRows[1][2].trim(), logo: teamRows[1][1] || null },
      starts_at: startsAt.toISOString(),
      match_url: matchUrl,
      is_live: isLive,
      cached_at: new Date().toISOString()
    });
  }

  return matches;
}

app.get('/api/v2/matches/live', rateLimiterMiddleware(100, 60), async (c) => {
  const allMatches = await getCachedOrFetch(c, 'kickbd_matches',
    () => fetchKickbdMatches(), 120);
  const live = allMatches.filter(m => m.is_live);
  live.sort((a, b) => new Date(a.starts_at) - new Date(b.starts_at));
  return c.json(makeResponse(true, {
    matches: live,
    total: live.length,
    cached_at: new Date().toISOString()
  }));
});

// --- Proxy (rewrites m3u8/MPD URLs to bypass CORS + Referer checks) ---
app.get('/api/v2/proxy', rateLimiterMiddleware(100, 60), async (c) => {
  const url = c.req.query('url');
  if (!url || url.length < 10) return c.json(makeResponse(false, null, { code: 'HTTP_400', message: 'url parameter required' }), 400);
  try {
    const resp = await fetch(url, {
      headers: {
        'User-Agent': nextUA(),
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://kickbd.org/',
        'Origin': 'https://kickbd.org'
      },
      redirect: 'follow'
    });
    let body = await resp.arrayBuffer();
    let contentType = resp.headers.get('content-type') || 'application/octet-stream';

    if (body.byteLength > 10) {
      const head = new TextDecoder().decode(body.slice(0, 50));
      const reqUrl = new URL(c.req.url);
      const proxyBase = `${reqUrl.origin}/api/v2/proxy?url=`;
      const origUrl = new URL(url);
      const baseDir = origUrl.pathname.substring(0, origUrl.pathname.lastIndexOf('/') + 1);

      if (head.startsWith('#EXTM3U')) {
        contentType = 'application/vnd.apple.mpegurl';
        const text = new TextDecoder().decode(body);
        const rewritten = text.split('\n').map(line => {
          const trimmed = line.trim();
          if (!trimmed || trimmed.startsWith('#')) return line;
          try {
            const resolved = trimmed.startsWith('http')
              ? trimmed
              : new URL(trimmed, origUrl.origin + baseDir).href;
            return proxyBase + encodeURIComponent(resolved);
          } catch { return line; }
        }).join('\n');
        body = new TextEncoder().encode(rewritten).buffer;
      } else if (head.includes('<MPD') || head.includes('<?xml')) {
        contentType = 'application/dash+xml';
        let text = new TextDecoder().decode(body);
        const cdnBase = origUrl.origin + baseDir;
        // Inject BaseURL so Shaka resolves segments against the CDN, not the proxy
        if (!text.includes('<BaseURL')) {
          text = text.replace('<MPD', `<MPD><BaseURL>${cdnBase}</BaseURL>`);
        }
        body = new TextEncoder().encode(text).buffer;
      }
    }

    return new Response(body, {
      status: resp.status,
      headers: {
        'Content-Type': contentType,
        'Access-Control-Allow-Origin': '*',
        'Cache-Control': 'public, max-age=30'
      }
    });
  } catch (e) {
    return c.json(makeResponse(false, null, { code: 'HTTP_502', message: 'Failed to fetch stream' }), 502);
  }
});

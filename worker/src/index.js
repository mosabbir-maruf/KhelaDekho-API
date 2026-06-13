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

// Helper: Safe Float Parsing
function safeFloat(value, def = 0.0) {
  if (!value) return def;
  const cleaned = value.toString().trim().replace(/%/g, '');
  const parsed = parseFloat(cleaned);
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
  allowHeaders: ['X-Signature-Token', 'X-Signature-Timestamp', 'Content-Type']
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
  const secret = c.env.SECRET_KEY || 'production-super-secret-key-fallback-change-me';
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

// Target Scraper Service
async function scrapeAll(targetUrl) {
  const res = await fetch(targetUrl, {
    headers: {
      'User-Agent': 'Mozilla/5.0 (compatible; KhelaDekhoAggregator/1.0; CloudflareWorker)',
      'Accept': 'text/html'
    }
  });
  
  if (!res.ok) throw new Error(`Target provider returned status ${res.status}`);
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
    
    // Parse team info
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
  
  // 2. Channels Parsing (Parse CHANNELS JS array block)
  let channels = [];
  const scriptRegex = /CHANNELS\s*=\s*(\[.+?\])\s*;/s;
  const match = html.match(scriptRegex);
  if (match) {
    try {
      const parsedData = JSON.parse(match[1]);
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
  let liveViewers = safeInt($('[data-stats-live], #currentLiveCount, .watch-metric.live strong').text());
  let allViews = parseViews($('[data-stats-views], #currentViewCount, .watch-metric strong').text());
  let totalChannels = channels.length;
  
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

// Cache Stamede-Proof Getter using Cloudflare Cache API
async function getCachedScrape(c) {
  const targetUrl = c.env.TARGET_URL || "https://livekhela.tv/";
  
  // Cloudflare native cache
  const cacheKey = new Request("http://kheladekho-cache.internal/data", { method: "GET" });
  const cache = caches.default;
  const cachedResponse = await cache.match(cacheKey);
  
  if (cachedResponse) {
    return await cachedResponse.json();
  }
  
  // Fetch fresh
  const freshData = await scrapeAll(targetUrl);
  
  // Store in cache for 120 seconds
  const responseToStore = new Response(JSON.stringify(freshData), {
    headers: {
      'Content-Type': 'application/json',
      'Cache-Control': 'max-age=120'
    }
  });
  c.executionCtx.waitUntil(cache.put(cacheKey, responseToStore));
  
  return freshData;
}

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
    channels: page,
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
    channels: live,
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
function decodePayload(payload) {
  try {
    const reversed = payload.split('').reverse().join('');
    const raw = atob(reversed);
    return JSON.parse(raw);
  } catch (e) {
    throw new Error("Failed to decode base64 play payload string");
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
    const res = await fetch('https://livekhela.tv/api/channel', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
        'Origin': 'https://livekhela.tv',
        'Referer': 'https://livekhela.tv/',
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
    
    const decoded = decodePayload(respJson.payload);
    
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

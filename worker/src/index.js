import { Hono } from 'hono';
import { cors } from 'hono/cors';

const app = new Hono();

// =========================================================================
// Shared helpers
// =========================================================================

// Development-only logging. Production stays silent (set ENVIRONMENT=development
// in wrangler for verbose local logs).
const isDev = (env) => env && env.ENVIRONMENT === 'development';
const devError = (env, ...args) => { if (isDev(env)) console.error(...args); };
const devWarn = (env, ...args) => { if (isDev(env)) console.warn(...args); };

// Standard response envelope: { success, data, error }
const makeResponse = (success, data = null, error = null) => ({ success, data, error });

// CORS
app.use('*', cors({
  origin: '*',
  allowMethods: ['GET', 'OPTIONS'],
  allowHeaders: ['xkey', 'Content-Type', 'User-Agent']
}));

// Single shared API-key auth (xkey) — proxy routes are exempt because media
// players cannot attach custom headers.
app.use('*', async (c, next) => {
  const path = new URL(c.req.url).pathname;
  if (path.endsWith('/proxy')) return await next();

  const expected = c.env.XKEY;
  if (expected) {
    const provided = c.req.header('xkey');
    if (!provided || provided !== expected) {
      return c.json(makeResponse(false, null, {
        code: 'HTTP_401',
        message: 'Invalid or missing xkey.'
      }), 401);
    }
  }
  await next();
});

// Centralized error handler
app.onError((err, c) => {
  devError(c.env, 'Worker execution error:', err);
  let status = 500;
  let code = 'INTERNAL_SERVER_ERROR';
  let message = 'A critical system error occurred. Please try again later.';
  if (err.status) {
    status = err.status;
    code = `HTTP_${status}`;
    message = err.message || message;
  }
  return c.json(makeResponse(false, null, { code, message }), status);
});

app.notFound((c) => c.json(makeResponse(false, null, {
  code: 'NOT_FOUND',
  message: 'Requested API resource not found.'
}), 404));

// In-memory sliding-window rate limiter (with optional KV sync)
const rateLimitCache = new Map();
const rateLimiterMiddleware = (requests = 60, windowSecs = 60) => {
  return async (c, next) => {
    const ip = c.req.header('CF-Connecting-IP') || 'unknown';
    const path = new URL(c.req.url).pathname;
    const key = `rate:${ip}:${path}`;
    const now = Math.floor(Date.now() / 1000);

    let clientHits = rateLimitCache.get(key) || [];
    clientHits = clientHits.filter(ts => ts > now - windowSecs);
    if (clientHits.length >= requests) {
      return c.json(makeResponse(false, null, {
        code: 'HTTP_429',
        message: 'Request rate limit exceeded. Please back off.'
      }), 429);
    }
    clientHits.push(now);
    rateLimitCache.set(key, clientHits);

    if (c.env.KHELADEKHO_STORE) {
      try {
        const kvKey = `rl:${ip}:${path}`;
        const raw = await c.env.KHELADEKHO_STORE.get(kvKey);
        let kvHits = raw ? JSON.parse(raw) : [];
        kvHits = kvHits.filter(ts => ts > now - windowSecs);
        if (kvHits.length >= requests) {
          return c.json(makeResponse(false, null, {
            code: 'HTTP_429',
            message: 'Request rate limit exceeded. Please back off.'
          }), 429);
        }
        kvHits.push(now);
        await c.env.KHELADEKHO_STORE.put(kvKey, JSON.stringify(kvHits), { expirationTtl: windowSecs });
      } catch (err) {
        devWarn(c.env, 'KV rate limiting sync failed, using local memory:', err);
      }
    }
    await next();
  };
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

// Unified text fetch
async function fetchText(url, headers = {}) {
  const res = await fetch(url, {
    headers: {
      'User-Agent': nextUA(),
      'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
      'Accept-Language': 'en-US,en;q=0.9',
      ...headers
    },
    signal: AbortSignal.timeout(15000)
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return await res.text();
}

async function fetchJson(url) {
  const res = await fetch(url, { headers: { 'User-Agent': nextUA(), 'Accept': 'application/json' } });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// Concurrent batch processor
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

// Unified cache helper with stale-while-revalidate + stampede protection
const fetchPromises = new Map();
async function getCachedOrFetch(c, key, fetchFn, ttl) {
  const cache = caches.default;
  const cacheReq = new Request(`http://kheladekho-cache.internal/${key}`);
  const hit = await cache.match(cacheReq);

  if (hit) {
    const dateHeader = hit.headers.get('x-cache-date');
    const cachedAt = dateHeader ? parseInt(dateHeader, 10) : 0;
    const age = Date.now() - cachedAt;
    if (age < ttl * 1000) return await hit.json();

    c.executionCtx.waitUntil((async () => {
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
    })());
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

// =========================================================================
// V1 — Goal Score Provider
// =========================================================================

// Provider base URL comes from env (V1_HOME_URL), never hardcoded.
const providerBase = (c) => (c.env.V1_HOME_URL || '').replace(/\/+$/, '');
const BDT_OFFSET_HOURS = 6;

function extractNextData(html) {
  const m = html.match(/<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)<\/script>/);
  if (!m) return null;
  try { return JSON.parse(m[1]); } catch { return null; }
}

function goalTeam(raw) {
  if (!raw) return { id: '', name: 'TBD', code: '', short: '', image_url: null };
  return {
    id: raw.id || '',
    name: raw.name || raw.long || 'TBD',
    code: raw.code || '',
    short: raw.short || '',
    image_url: (raw.image || {}).url || null,
  };
}

function goalPeriod(raw) {
  if (!raw) return null;
  return { type: raw.type || '', minute: raw.minute || 0, extra: raw.extra || 0 };
}

function goalRound(raw) {
  if (!raw) return null;
  return { name: raw.name || '', display: raw.display !== false };
}

function goalPlayer(raw) {
  if (!raw) return null;
  return { id: raw.id || '', name: raw.name || '', image_url: (raw.image || {}).url || null };
}

function goalMatch(raw) {
  const score = raw.score;
  const agg = raw.agg;
  const penalty = raw.penalty;
  const redCards = raw.redCards || {};
  const venue = raw.venue;
  const link = raw.link || {};
  return {
    id: raw.id || '',
    start_date: raw.startDate || new Date().toISOString(),
    status: raw.status || 'FIXTURE',
    score_team_a: score ? (score.teamA ?? null) : null,
    score_team_b: score ? (score.teamB ?? null) : null,
    agg_team_a: agg ? (agg.teamA ?? null) : null,
    agg_team_b: agg ? (agg.teamB ?? null) : null,
    penalty_team_a: penalty ? (penalty.teamA ?? null) : null,
    penalty_team_b: penalty ? (penalty.teamB ?? null) : null,
    team_a: goalTeam(raw.teamA || {}),
    team_b: goalTeam(raw.teamB || {}),
    round: goalRound(raw.round),
    period: goalPeriod(raw.period),
    red_cards_team_a: redCards.teamA || 0,
    red_cards_team_b: redCards.teamB || 0,
    venue: venue ? (venue.name || null) : null,
    slug: link.slug || '',
    last_updated_at: raw.lastUpdatedAt || null,
  };
}

function parseScores(nextData) {
  let liveScores;
  try { liveScores = nextData.props.pageProps.content.liveScores; } catch { liveScores = null; }
  if (!Array.isArray(liveScores)) return { competitions: [], total_matches: 0, cached_at: new Date().toISOString() };

  const competitions = [];
  let total = 0;
  for (const rawComp of liveScores) {
    const comp = rawComp.competition || {};
    const matches = (rawComp.matches || []).map(goalMatch);
    total += matches.length;
    competitions.push({
      id: comp.id || '',
      name: comp.name || '',
      area: (comp.area || {}).name || '',
      image_url: (comp.image || {}).url || null,
      matches,
    });
  }
  return { competitions, total_matches: total, cached_at: new Date().toISOString() };
}

function matchDateInTz(iso, targetDate) {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return false;
  const shifted = new Date(d.getTime() + BDT_OFFSET_HOURS * 3600 * 1000);
  return shifted.toISOString().slice(0, 10) === targetDate;
}

async function fetchGoalScores(c, date) {
  const base = providerBase(c);
  if (date) {
    const urls = [`${base}/en/live-scores`, `${base}/en/fixtures/${date}`, `${base}/en/results/${date}`];
    for (const url of urls) {
      let html;
      try { html = await fetchText(url); } catch { continue; }
      const nd = extractNextData(html);
      if (!nd) continue;
      const result = parseScores(nd);
      for (const comp of result.competitions) {
        comp.matches = comp.matches.filter(m => matchDateInTz(m.start_date, date));
      }
      result.competitions = result.competitions.filter(comp => comp.matches.length > 0);
      result.total_matches = result.competitions.reduce((s, comp) => s + comp.matches.length, 0);
      if (result.total_matches > 0) return result;
    }
    return { competitions: [], total_matches: 0, cached_at: new Date().toISOString() };
  }

  let html;
  try { html = await fetchText(`${base}/en/live-scores`); } catch { return { competitions: [], total_matches: 0, cached_at: new Date().toISOString() }; }
  const nd = extractNextData(html);
  if (!nd) return { competitions: [], total_matches: 0, cached_at: new Date().toISOString() };
  return parseScores(nd);
}

function filterScores(data, statusVal) {
  const competitions = data.competitions
    .map(c => ({ ...c, matches: c.matches.filter(m => m.status === statusVal) }))
    .filter(c => c.matches.length > 0);
  return {
    competitions,
    total_matches: competitions.reduce((s, c) => s + c.matches.length, 0),
    cached_at: data.cached_at,
  };
}

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
function validDate(c) {
  const d = c.req.query('date');
  return d && DATE_RE.test(d) ? d : null;
}
const scoresCacheKey = (date) => `goal/scores_${date || 'today'}`;

app.get('/api/v1/health', rateLimiterMiddleware(100, 60), (c) => {
  return c.json(makeResponse(true, { status: 'ok', version: '1.0.0' }));
});

app.get('/api/v1/scores', rateLimiterMiddleware(60, 60), async (c) => {
  const date = validDate(c);
  let data = await getCachedOrFetch(c, scoresCacheKey(date), () => fetchGoalScores(c, date), 15);

  const competition = c.req.query('competition');
  const statusQ = c.req.query('status');
  if (competition) {
    const q = competition.toLowerCase();
    const competitions = data.competitions.filter(comp => comp.name.toLowerCase().includes(q));
    data = { ...data, competitions, total_matches: competitions.reduce((s, comp) => s + comp.matches.length, 0) };
  }
  if (statusQ) {
    const map = { live: 'LIVE', result: 'RESULT', fixture: 'FIXTURE' };
    const mapped = map[statusQ];
    if (mapped) data = filterScores(data, mapped);
  }
  return c.json(makeResponse(true, data));
});

app.get('/api/v1/competitions', rateLimiterMiddleware(60, 60), async (c) => {
  const date = validDate(c);
  const data = await getCachedOrFetch(c, scoresCacheKey(date), () => fetchGoalScores(c, date), 15);
  const comps = data.competitions.map(comp => ({
    id: comp.id, name: comp.name, area: comp.area, image_url: comp.image_url, match_count: comp.matches.length,
  }));
  return c.json(makeResponse(true, { competitions: comps, total: comps.length, cached_at: data.cached_at }));
});

// ---- Match / player / team detail ----

function parseMatchDetail(nextData) {
  let content;
  try { content = nextData.props.pageProps.content; } catch { return null; }
  const raw = content && content.match;
  if (!raw) return null;

  const score = raw.score, ht = raw.halfTime, ft = raw.fullTime, et = raw.extraTime;
  const venue = raw.venue, comp = raw.competition || {};
  const teamAColors = ((raw.teamA || {}).colors || []).map(x => x.value).filter(Boolean);
  const teamBColors = ((raw.teamB || {}).colors || []).map(x => x.value).filter(Boolean);

  const detail = {
    id: raw.id || '',
    status: raw.status || '',
    competition_name: comp.name || '',
    competition_area: (comp.area || {}).name || '',
    competition_image_url: (comp.image || {}).url || null,
    start_date: raw.startDate || new Date().toISOString(),
    venue: venue ? (venue.name || null) : null,
    venue_lat: venue ? (venue.latitude ?? null) : null,
    venue_lng: venue ? (venue.longitude ?? null) : null,
    score_team_a: score ? (score.teamA ?? null) : null,
    score_team_b: score ? (score.teamB ?? null) : null,
    half_time_team_a: ht ? (ht.teamA ?? null) : null,
    half_time_team_b: ht ? (ht.teamB ?? null) : null,
    full_time_team_a: ft ? (ft.teamA ?? null) : null,
    full_time_team_b: ft ? (ft.teamB ?? null) : null,
    extra_time_team_a: et ? (et.teamA ?? null) : null,
    extra_time_team_b: et ? (et.teamB ?? null) : null,
    agg_team_a: raw.agg ? (raw.agg.teamA ?? null) : null,
    agg_team_b: raw.agg ? (raw.agg.teamB ?? null) : null,
    penalty_team_a: raw.penalty ? (raw.penalty.teamA ?? null) : null,
    penalty_team_b: raw.penalty ? (raw.penalty.teamB ?? null) : null,
    team_a: goalTeam(raw.teamA || {}),
    team_b: goalTeam(raw.teamB || {}),
    team_a_colors: teamAColors.length ? teamAColors : null,
    team_b_colors: teamBColors.length ? teamBColors : null,
    round: goalRound(raw.round),
    period: goalPeriod(raw.period),
    events: [],
    stats: null,
    lineups: null,
    commentary: [],
    top_players: [],
    h2h: null,
    h2h_matches: [],
    scorers_team_a: [],
    scorers_team_b: [],
    red_cards_team_a: (raw.redCards || {}).teamA || 0,
    red_cards_team_b: (raw.redCards || {}).teamB || 0,
    last_updated_at: raw.lastUpdatedAt || null,
  };

  const mkEvent = (e) => ({
    type: e.type || '',
    side: e.side || null,
    period: goalPeriod(e.period),
    player: goalPlayer(e.player),
    scorer: goalPlayer(e.scorer),
    assist: goalPlayer(e.assist),
    in_player: goalPlayer(e.in),
    out_player: goalPlayer(e.out),
    outcome: e.outcome || null,
    decision: e.decision || null,
  });

  for (const e of raw.events || []) detail.events.push(mkEvent(e));

  const scorers = raw.scorers || {};
  for (const s of scorers.teamA || []) {
    const p = goalPlayer(s.player);
    for (const ev of s.events || []) detail.scorers_team_a.push({ type: ev.type || 'GOAL', side: null, period: goalPeriod(ev.period), player: null, scorer: p, assist: null, in_player: null, out_player: null, outcome: null, decision: null });
  }
  for (const s of scorers.teamB || []) {
    const p = goalPlayer(s.player);
    for (const ev of s.events || []) detail.scorers_team_b.push({ type: ev.type || 'GOAL', side: null, period: goalPeriod(ev.period), player: null, scorer: p, assist: null, in_player: null, out_player: null, outcome: null, decision: null });
  }

  // Stats
  if (raw.stats) {
    const stats = { summary: [], attacking: [], passing: [], duels: [], defence: [], discipline: [] };
    for (const key of Object.keys(stats)) {
      stats[key] = (raw.stats[key] || []).map(item => ({
        type: item.type || '', team_a: Number(item.teamA || 0), team_b: Number(item.teamB || 0),
      }));
    }
    detail.stats = stats;
  }

  // Lineups (from match object)
  const parseLineupPlayer = (entry) => {
    const person = entry.person || {};
    const pitch = entry.pitchPosition || {};
    return {
      player: goalPlayer(person),
      position: null,
      shirt_number: entry.shirtNumber ?? null,
      score: entry.score ?? null,
      is_substitute: false,
      formation_position: pitch && (pitch.x != null) ? `x:${pitch.x},y:${pitch.y}` : null,
    };
  };
  if (raw.lineups) {
    const lineups = { team_a: null, team_b: null };
    for (const [sideKey, teamKey] of [['teamA', 'team_a'], ['teamB', 'team_b']]) {
      const td = raw.lineups[sideKey];
      if (!td) continue;
      const tl = { formation: td.formation || null, starting_xi: [], substitutes: [] };
      for (const entry of td.lineup || []) tl.starting_xi.push(parseLineupPlayer(entry));
      for (const entry of td.substitutes || []) { const lp = parseLineupPlayer(entry); lp.is_substitute = true; tl.substitutes.push(lp); }
      lineups[teamKey] = tl;
    }
    detail.lineups = lineups;
  }

  // Commentary (real, filtering lazy placeholders)
  for (const cm of (content.tabsInfo || {}).commentary || []) {
    if (Object.keys(cm).length <= 1 && !cm.text && !cm.player) continue;
    detail.commentary.push({ type: cm.type || '', period: goalPeriod(cm.period), text: cm.text || '', player: goalPlayer(cm.player), side: cm.side || null });
  }

  // Fallback commentary from events
  if (detail.commentary.length === 0) {
    const sorted = [...detail.events].sort((a, b) => ((a.period ? a.period.minute : 999) - (b.period ? b.period.minute : 999)) || ((a.period ? a.period.extra : 0) - (b.period ? b.period.extra : 0)));
    const sideLabel = { 'TEAM_A': ` (${detail.team_a.name})`, 'TEAM_B': ` (${detail.team_b.name})` };
    const lbl = (side) => sideLabel[side] || '';
    for (const e of sorted) {
      if (e.type === 'PERIOD_FIRST_HALF') detail.commentary.push({ type: 'PERIOD', period: e.period, text: 'First Half begins', player: null, side: null });
      else if (e.type === 'PERIOD_SECOND_HALF') detail.commentary.push({ type: 'PERIOD', period: e.period, text: 'Second Half begins', player: null, side: null });
      else if (e.type === 'PERIOD_HALF_TIME') detail.commentary.push({ type: 'PERIOD', period: e.period, text: 'Half Time', player: null, side: null });
      else if (e.type === 'PERIOD_MATCH_END') detail.commentary.push({ type: 'PERIOD', period: e.period, text: 'Match ended', player: null, side: null });
      else if (e.type.includes('GOAL')) { const s = e.scorer || e.player; detail.commentary.push({ type: e.type, period: e.period, text: `Goal scored by ${s ? s.name : 'Unknown'}${lbl(e.side)}`, player: s, side: e.side }); }
      else if (e.type.includes('CARD_YELLOW')) detail.commentary.push({ type: e.type, period: e.period, text: `Yellow Card - ${e.player ? e.player.name : 'Unknown'}${lbl(e.side)}`, player: e.player, side: e.side });
      else if (e.type.includes('CARD_RED')) detail.commentary.push({ type: e.type, period: e.period, text: `Red Card - ${e.player ? e.player.name : 'Unknown'}${lbl(e.side)}`, player: e.player, side: e.side });
      else if (e.type.includes('SUBSTITUTION')) detail.commentary.push({ type: e.type, period: e.period, text: `Substitution - ${e.in_player ? e.in_player.name : 'Unknown'} replaces ${e.out_player ? e.out_player.name : 'Unknown'}${lbl(e.side)}`, player: e.in_player, side: e.side });
      else if (e.type.includes('VAR') && e.decision) detail.commentary.push({ type: e.type, period: e.period, text: `VAR - ${e.decision}${lbl(e.side)}`, player: null, side: e.side });
    }
  }

  // Top players
  const topRaw = (content.tabsInfo || {}).topPlayers;
  if (topRaw && typeof topRaw === 'object') {
    for (const [sideKey, teamSide] of [['teamA', 'TEAM_A'], ['teamB', 'TEAM_B']]) {
      for (const p of topRaw[sideKey] || []) {
        const pl = goalPlayer(p.player);
        if (pl) detail.top_players.push({ player: pl, score: p.score || 0, team_side: teamSide });
      }
    }
  }
  if (detail.top_players.length === 0 && detail.lineups) {
    for (const [teamKey, teamSide] of [['team_a', 'TEAM_A'], ['team_b', 'TEAM_B']]) {
      const t = detail.lineups[teamKey];
      if (!t) continue;
      for (const lp of [...t.starting_xi, ...t.substitutes]) {
        if (lp.player && lp.score != null) detail.top_players.push({ player: lp.player, score: lp.score, team_side: teamSide });
      }
    }
  }

  // H2H
  const h2h = content.h2h;
  if (h2h) {
    const s = h2h.stats || {};
    detail.h2h = {
      team_a_goals: s.teamAGoals || 0,
      team_a_wins: s.teamAWins || 0,
      team_b_goals: s.teamBGoals || 0,
      team_b_wins: s.teamBWins || 0,
      draws: s.draws || 0,
      games_over_two_and_half: s.gamesOverTwoAndHalf || 0,
      games_both_teams_scored: s.gamesBothTeamsScored || 0,
    };
    for (const hm of h2h.matches || []) detail.h2h_matches.push(goalMatch(hm));
  }

  return detail;
}

function toSlug(name) {
  return (name || '').toLowerCase().trim()
    .replace(/[^a-z0-9\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '');
}

function parsePlayerDetail(nextData) {
  let content;
  try {
    const props = nextData.props.pageProps;
    content = (props.page && props.page.content) || props.content || {};
  } catch { return null; }
  let raw = content.player;
  if (!raw) { raw = content; if (!raw.firstName) return null; }

  const player = {
    id: raw.id || '',
    name: raw.name || '',
    first_name: raw.firstName || '',
    last_name: raw.lastName || '',
    shirt_number: raw.shirtNumber ?? null,
    position: raw.position || null,
    age: raw.age ?? null,
    date_of_birth: raw.dateOfBirth || null,
    nationality_name: (raw.nationality || {}).name || null,
    nationality_image_url: ((raw.nationality || {}).image || {}).url || null,
    image_url: (raw.image || {}).url || null,
    current_team_name: (raw.team || {}).name || null,
    current_team_id: (raw.team || {}).id || null,
    current_team_image_url: ((raw.team || {}).image || {}).url || null,
    stats: [],
  };

  for (const s of raw.stats || []) {
    const comp = s.competition || {}, season = s.season || {}, rs = s.stats || {}, team = s.team || {};
    player.stats.push({
      competition_name: comp.name || '',
      competition_image_url: (comp.image || {}).url || null,
      season_name: season.name || '',
      team_image_url: (team.image || {}).url || null,
      appearances: rs.appearances || 0,
      starting_eleven: rs.startingEleven || 0,
      minutes_played: rs.minutesPlayed || 0,
      goals: rs.goals || 0,
      minutes_per_goal: rs.minutesPerGoal ?? null,
      assists: rs.assists || 0,
      own_goals: rs.ownGoals || 0,
      penalty_goals: rs.penaltyGoals || 0,
      penalties_missed: rs.penaltiesMissed || 0,
      shots_on_target: rs.shotsOnTarget || 0,
      shots_off_target: rs.shotsOffTarget || 0,
      blocked_shots: rs.blockedShots || 0,
      goals_outside_box: rs.goalsOutsideBox || 0,
      hit_woodwork: rs.hitWoodwork || 0,
      freekick_goals: rs.freekickGoals || 0,
      offsides: rs.offsides || 0,
      corners: rs.corners || 0,
      crosses: rs.crosses || 0,
      successful_crosses: rs.successfulCrosses || 0,
      tackles: rs.tackles || 0,
      clearances: rs.clearances || 0,
      yellow_cards: rs.yellowCards || 0,
      red_cards: rs.redCards || 0,
      fouls_committed: rs.foulsCommited || rs.foulsCommitted || 0,
      fouls_suffered: rs.foulsSuffered || 0,
      goals_conceded: rs.goalsConceded || 0,
      clean_sheets: rs.cleanSheets || 0,
      saves: rs.saves || 0,
      penalty_saves: rs.penaltySaves || 0,
    });
  }
  return player;
}

function parseTeamDetail(nextData) {
  let content;
  try {
    const props = nextData.props.pageProps;
    content = (props.page && props.page.content) || props.content || {};
  } catch { return null; }
  const raw = content.team;
  if (!raw) return null;
  const team = {
    id: raw.id || '',
    name: raw.name || '',
    long_name: raw.longName || '',
    short_name: raw.shortName || '',
    image_url: (raw.image || {}).url || null,
    recent_matches: [],
  };
  for (const rm of content.summaryMatches || []) team.recent_matches.push(goalMatch(rm.match || rm));
  return team;
}

app.get('/api/v1/matches/:match_id', rateLimiterMiddleware(60, 60), async (c) => {
  const matchId = c.req.param('match_id');
  const slug = c.req.query('slug');
  if (!slug) return c.json(makeResponse(false, null, { code: 'HTTP_400', message: 'slug query parameter is required' }), 400);
  const detail = await getCachedOrFetch(c, `goal/match_${matchId}`, async () => {
    let html;
    try { html = await fetchText(`${providerBase(c)}/en-in/match/${slug}/${matchId}`); } catch { return null; }
    const nd = extractNextData(html);
    return nd ? parseMatchDetail(nd) : null;
  }, 30);
  if (!detail) return c.json(makeResponse(false, null, { code: 'HTTP_404', message: 'Match not found' }), 404);
  return c.json(makeResponse(true, { match: detail, cached_at: new Date().toISOString() }));
});

app.get('/api/v1/player/:player_id', rateLimiterMiddleware(60, 60), async (c) => {
  const playerId = c.req.param('player_id');
  const playerName = c.req.query('player_name');
  const detail = await getCachedOrFetch(c, `goal/player_${playerId}`, async () => {
    const base = providerBase(c);
    let html = null;
    try { html = await fetchText(`${base}/en/player/${playerId}`); } catch {}
    if (!html && playerName) { try { html = await fetchText(`${base}/en/player/${toSlug(playerName)}/${playerId}`); } catch {} }
    if (!html) return null;
    const nd = extractNextData(html);
    return nd ? parsePlayerDetail(nd) : null;
  }, 300);
  if (!detail) return c.json(makeResponse(false, null, { code: 'HTTP_404', message: 'Player not found' }), 404);
  return c.json(makeResponse(true, { player: detail, cached_at: new Date().toISOString() }));
});

app.get('/api/v1/team/:team_id', rateLimiterMiddleware(60, 60), async (c) => {
  const teamId = c.req.param('team_id');
  const teamName = c.req.query('team_name');
  const detail = await getCachedOrFetch(c, `goal/team_${teamId}`, async () => {
    const base = providerBase(c);
    let html = null;
    try { html = await fetchText(`${base}/en/team/${teamId}`); } catch {}
    if (!html && teamName) { try { html = await fetchText(`${base}/en/team/${toSlug(teamName)}/${teamId}`); } catch {} }
    if (!html) return null;
    const nd = extractNextData(html);
    return nd ? parseTeamDetail(nd) : null;
  }, 300);
  if (!detail) return c.json(makeResponse(false, null, { code: 'HTTP_404', message: 'Team not found' }), 404);
  return c.json(makeResponse(true, { team: detail, cached_at: new Date().toISOString() }));
});

// Root welcome + health alias
app.get('/', rateLimiterMiddleware(100, 60), (c) => c.json(makeResponse(true, {
  message: 'KhelaDekho API Worker',
  endpoints: {
    health: '/api/v1/health',
    scores: '/api/v1/scores',
    channels_v2: '/api/v2/channels',
    channels_v4: '/api/v4/channels',
  }
})));
app.get('/health', (c) => c.redirect('/api/v1/health', 301));

export default app;

// =========================================================================
// V2 — Kickbd
// =========================================================================

// Upstream base URLs come from env, never hardcoded.
const getV2Home = (c) => c.env.V2_HOME_URL || '';
const getV4Home = (c) => c.env.V4_HOME_URL || '';

function kickbdDecrypt(payloadUrlEnc) {
  const decoded = decodeURIComponent(payloadUrlEnc);
  const k = '999999859198';
  let r = '';
  for (let i = 0; i < decoded.length; i++) {
    r += String.fromCharCode((decoded.charCodeAt(i) + 5) ^ parseInt(k[i % k.length]));
  }
  return r;
}

async function extractStreamDataFromIframe(iframeUrl) {
  if (iframeUrl.includes('/source/')) {
    try {
      const srcHtml = await fetchText(iframeUrl);
      const pMatch = srcHtml.match(/var _p\s*=\s*"([^"]+)"/);
      if (!pMatch) return null;
      const decrypted = kickbdDecrypt(pMatch[1]);
      const urlMatch = decrypted.match(/window\.player\.load\('([^']+)'\)/);
      const kidMatch = decrypted.match(/k_id='([^']+)'/);
      const kvMatch = decrypted.match(/k_v='([^']+)'/);
      if (!urlMatch) return null;
      const result = { stream_url: urlMatch[1], stream_type: urlMatch[1].includes('.mpd') ? 'dash' : 'hls' };
      if (kidMatch) result.drm_kid = kidMatch[1];
      if (kvMatch) result.drm_key = kvMatch[1];
      return result;
    } catch (e) { return null; }
  }
  if (iframeUrl.includes('yagaverse.net')) {
    try {
      const yHtml = await fetchText(iframeUrl);
      const sMatch = yHtml.match(/const streamUrl\s*=\s*'([^']+)'/) ||
        yHtml.match(/source:\s*'([^']+)'/) ||
        yHtml.match(/file:\s*'([^']+)'/) ||
        yHtml.match(/https?:\/\/[^"'\s>]+\.m3u8[^"'\s>]*/);
      if (sMatch) {
        const url = sMatch[1] || sMatch[0];
        return { stream_url: url, stream_type: 'hls' };
      }
    } catch (e) { /* skip */ }
    return null;
  }
  if (iframeUrl.includes('soccerball.st')) {
    try {
      const sHtml = await fetchText(iframeUrl);
      const proxyMatch = sHtml.match(/https?:\/\/[^"'<>\s]+s\d+\.php[^"'<>\s]*/);
      if (proxyMatch) return { stream_url: proxyMatch[0], stream_type: 'hls' };
    } catch (e) { /* skip */ }
    return null;
  }
  try {
    const pHtml = await fetchText(iframeUrl);
    const urlMatch = pHtml.match(/https?:\/\/[^"'<>\s]+\.(?:m3u8|mpd)[^"'<>\s]*/);
    if (!urlMatch) return null;
    const result = { stream_url: urlMatch[0], stream_type: urlMatch[0].includes('.mpd') ? 'dash' : 'hls' };
    const kidMatch = pHtml.match(/k_id['"]?\s*[:=]\s*['"]([^'"]+)['"]/);
    const kvMatch = pHtml.match(/k_v['"]?\s*[:=]\s*['"]([^'"]+)['"]/);
    if (kidMatch) result.drm_kid = kidMatch[1];
    if (kvMatch) result.drm_key = kvMatch[1];
    return result;
  } catch (e) { return null; }
}

async function processChannel(ch, homeUrl) {
  let iframeUrl = null;
  try {
    const watchHtml = await fetchText(`${homeUrl}/watch/${ch.id}`);
    const iframeMatch = watchHtml.match(/<iframe[^>]*src=["']([^"']+)["'][^>]*>/);
    if (iframeMatch) iframeUrl = iframeMatch[1];
  } catch (e) { /* skip */ }

  const streamData = iframeUrl ? await extractStreamDataFromIframe(iframeUrl) : null;
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

async function fetchKickbdChannels(homeUrl) {
  const html = await fetchText(homeUrl);
  const seen = new Set();
  const channels = [];
  const watchRegex = /<a[^>]*href="[^"]*\/watch\/(\d+)"[^>]*>[\s\S]*?<img[^>]*src="([^"]*)"[^>]*alt="([^"]*)"[^>]*>/g;
  let m;
  while ((m = watchRegex.exec(html)) !== null) {
    const id = parseInt(m[1], 10);
    if (seen.has(id)) continue;
    seen.add(id);
    const rawName = m[3].trim() || 'Channel ' + id;
    const name = rawName.replace(/^KickBD\s+/i, '');
    channels.push({ id, name, logo: m[2] || null });
  }
  return await concurrentMap(channels, ch => processChannel(ch, homeUrl), 9);
}

async function processHighlight(slug, homeUrl) {
  let detail = { slug, title: slug, stream_url: null, sources: [], is_alive: false };
  try {
    const detailHtml = await fetchText(`${homeUrl}/highlights/${slug}`);
    const titleMatch = detailHtml.match(/<title[^>]*>(.*?)<\/title>/);
    if (titleMatch) detail.title = titleMatch[1].replace(/\s*\|\|.*/, '').trim();
    const iframeMatch = detailHtml.match(/<iframe[^>]*src=["']([^"']+)["'][^>]*>/);
    if (iframeMatch) {
      const streamUrl = iframeMatch[1];
      const cdnHost = `cdn.${new URL(homeUrl).hostname}`;
      if (streamUrl.includes(`${cdnHost}/stream.php`)) {
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

async function fetchKickbdHighlights(homeUrl) {
  const html = await fetchText(homeUrl);
  const slugSet = new Set();
  const escapedHome = homeUrl.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const slugRegex = new RegExp(`href=["']${escapedHome}/highlights/([^"']+)["'][^>]*>`, 'g');
  let m;
  while ((m = slugRegex.exec(html)) !== null) slugSet.add(m[1]);
  return await concurrentMap([...slugSet], s => processHighlight(s, homeUrl), 5);
}

function proxyStreamUrl(url) {
  if (!url) return null;
  return `/api/v2/proxy?url=${encodeURIComponent(url)}`;
}

app.get('/api/v2/channels', rateLimiterMiddleware(100, 60), async (c) => {
  const homeUrl = getV2Home(c);
  const channels = await getCachedOrFetch(c, 'kickbd_channels_v3', () => fetchKickbdChannels(homeUrl), 1800);
  const q = c.req.query('q');
  const aliveOnly = c.req.query('alive') === 'true';
  let filtered = channels;
  if (aliveOnly) filtered = filtered.filter(ch => ch.is_alive);
  if (q) { const query = q.toLowerCase(); filtered = filtered.filter(ch => ch.name.toLowerCase().includes(query)); }
  const proxied = filtered.map(ch => ({ ...ch, stream_url: proxyStreamUrl(ch.stream_url) }));
  return c.json(makeResponse(true, { channels: proxied, total: proxied.length, cached_at: new Date().toISOString() }));
});

app.get('/api/v2/channels/:channel_id', rateLimiterMiddleware(100, 60), async (c) => {
  const homeUrl = getV2Home(c);
  const channels = await getCachedOrFetch(c, 'kickbd_channels_v3', () => fetchKickbdChannels(homeUrl), 1800);
  const channelId = parseInt(c.req.param('channel_id'), 10);
  const channel = channels.find(ch => ch.id === channelId);
  if (!channel) return c.json(makeResponse(false, null, { code: 'HTTP_404', message: 'Channel not found' }), 404);
  return c.json(makeResponse(true, { ...channel, stream_url: proxyStreamUrl(channel.stream_url) }));
});

app.get('/api/v2/highlights', rateLimiterMiddleware(100, 60), async (c) => {
  const homeUrl = getV2Home(c);
  const highlights = await getCachedOrFetch(c, 'kickbd_highlights', () => fetchKickbdHighlights(homeUrl), 1800);
  return c.json(makeResponse(true, { highlights, total: highlights.length, cached_at: new Date().toISOString() }));
});

app.get('/api/v2/highlights/:slug', rateLimiterMiddleware(100, 60), async (c) => {
  const homeUrl = getV2Home(c);
  const highlights = await getCachedOrFetch(c, 'kickbd_highlights', () => fetchKickbdHighlights(homeUrl), 1800);
  const slug = c.req.param('slug');
  const highlight = highlights.find(h => h.slug === slug);
  if (!highlight) return c.json(makeResponse(false, null, { code: 'HTTP_404', message: 'Highlight not found' }), 404);
  return c.json(makeResponse(true, highlight));
});

async function fetchKickbdMatches(homeUrl) {
  const html = await fetchText(homeUrl);
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
    if (badgeMatch) { sportEmoji = badgeMatch[1].trim(); league = badgeMatch[2].trim(); }
    const teamRows = [...chunk.matchAll(/<div\s+class="fixture-team-row">\s*<div\s+class="fixture-logo-box">\s*<img\s+src="([^"]+)"\s+alt="([^"]+)"/g)];
    if (teamRows.length < 2) continue;
    const expireTime = startsAt.getTime() + 6 * 3600 * 1000;
    const isLive = startsAt.getTime() <= now && now < expireTime;
    matches.push({
      id: matchSlug, league, sport_emoji: sportEmoji,
      team_a: { name: teamRows[0][2].trim(), logo: teamRows[0][1] || null },
      team_b: { name: teamRows[1][2].trim(), logo: teamRows[1][1] || null },
      starts_at: startsAt.toISOString(), match_url: matchUrl, is_live: isLive, cached_at: new Date().toISOString()
    });
  }
  return matches;
}

app.get('/api/v2/matches/live', rateLimiterMiddleware(100, 60), async (c) => {
  const homeUrl = getV2Home(c);
  const allMatches = await getCachedOrFetch(c, 'kickbd_matches', () => fetchKickbdMatches(homeUrl), 120);
  const live = allMatches.filter(m => m.is_live);
  live.sort((a, b) => new Date(a.starts_at) - new Date(b.starts_at));
  return c.json(makeResponse(true, { matches: live, total: live.length, cached_at: new Date().toISOString() }));
});

app.get('/api/v2/proxy', rateLimiterMiddleware(100, 60), async (c) => {
  const url = c.req.query('url');
  if (!url || url.length < 10) return c.json(makeResponse(false, null, { code: 'HTTP_400', message: 'url parameter required' }), 400);
  const source = c.req.query('source') || 'v2';
  const homeUrl = source === 'v4' ? getV4Home(c) : getV2Home(c);
  try {
    const isSegmentReq = url.match(/\.(ts|mp4|m4s)($|\?)/) || url.includes('/seg_') || url.includes('/segment') || url.includes('/init');
    const resp = await fetch(url, {
      headers: {
        'User-Agent': nextUA(),
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': `${homeUrl}/`,
        'Origin': homeUrl
      },
      redirect: 'follow',
      signal: AbortSignal.timeout(isSegmentReq ? 15000 : 8000)
    });
    if (isSegmentReq) {
      return new Response(resp.body, {
        status: resp.status,
        headers: {
          'Content-Type': resp.headers.get('content-type') || 'application/octet-stream',
          'Access-Control-Allow-Origin': '*',
          'Cache-Control': 'public, max-age=86400'
        }
      });
    }

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
            const resolved = trimmed.startsWith('http') ? trimmed : new URL(trimmed, origUrl.origin + baseDir).href;
            return proxyBase + encodeURIComponent(resolved);
          } catch { return line; }
        }).join('\n');
        body = new TextEncoder().encode(rewritten).buffer;
      } else if (head.includes('<MPD') || head.includes('<?xml')) {
        contentType = 'application/dash+xml';
        let text = new TextDecoder().decode(body);
        const cdnBase = origUrl.origin + baseDir;
        const encodeDashUrl = (u) => {
          if (u.startsWith('/api/v2/proxy')) return u;
          const absolute = u.startsWith('http') ? u : new URL(u, cdnBase).href;
          return proxyBase + absolute.split(/(\$Number\$|\$Time\$|\$RepresentationID\$|\$Bandwidth\$)/).map(part => {
            if (part.startsWith('$') && part.endsWith('$')) return part;
            return encodeURIComponent(part);
          }).join('');
        };
        const rewriteAttr = (tag, attr) => {
          const re = new RegExp(`\\b(${attr})\\s*=\\s*"([^"]*)"`, 'g');
          const re2 = new RegExp(`\\b(${attr})\\s*='([^']*)'`, 'g');
          return tag.replace(re, (m, name, val) => `${name}="${encodeDashUrl(val)}"`)
                    .replace(re2, (m, name, val) => `${name}='${encodeDashUrl(val)}'`);
        };
        text = text.replace(/<SegmentTemplate[^>]*>/g, (tag) => { tag = rewriteAttr(tag, 'media'); tag = rewriteAttr(tag, 'initialization'); return tag; });
        text = text.replace(/<SegmentURL[^>]*>/g, (tag) => rewriteAttr(tag, 'media'));
        text = text.replace(/<Initialization[^>]*>/g, (tag) => rewriteAttr(tag, 'sourceURL'));
        body = new TextEncoder().encode(text).buffer;
      }
    }

    const cacheMaxAge = url.match(/\.(ts|mp4|m4s)($|\?)/) || url.includes('/seg_') || url.includes('/segment') || url.includes('/init') ? 86400 : 0;
    return new Response(body, {
      status: resp.status,
      headers: { 'Content-Type': contentType, 'Access-Control-Allow-Origin': '*', 'Cache-Control': `public, max-age=${cacheMaxAge}` }
    });
  } catch (e) {
    return c.json(makeResponse(false, null, { code: 'HTTP_502', message: 'Failed to fetch stream' }), 502);
  }
});

// =========================================================================
// V4 — proxybdix (base URL from V4_HOME_URL)
// =========================================================================

async function fetchProxybdixChannels(baseUrl) {
  const list = await fetchJson(`${baseUrl}/api.php?action=list`);
  if (!Array.isArray(list) || list.length === 0) return [];
  const configs = await Promise.all(
    list.map(ch => fetchJson(`${baseUrl}/api.php?action=config&id=${ch.id}`).catch(() => null))
  );
  return list.map((ch, i) => {
    const cfg = configs[i];
    let stream_url = null, stream_type = 'dash', drm_kid = null, drm_key = null;
    if (cfg && cfg.m) {
      stream_url = cfg.m;
      stream_type = cfg.m.includes('.mpd') ? 'dash' : (cfg.m.includes('.m3u8') || cfg.m.includes('.m3u')) ? 'hls' : 'dash';
      drm_kid = cfg.k || null;
      drm_key = cfg.v || null;
    }
    return { id: ch.id, name: ch.name || ch.id, stream_url, stream_type, drm_kid, drm_key, cached_at: new Date().toISOString() };
  });
}

app.get('/api/v4/health', rateLimiterMiddleware(100, 60), (c) => {
  return c.json(makeResponse(true, { status: 'ok', version: '4.0.0', source: getV4Home(c) }));
});

app.get('/api/v4/channels', rateLimiterMiddleware(100, 60), async (c) => {
  const homeUrl = getV4Home(c);
  let channels = await getCachedOrFetch(c, 'proxybdix_channels', () => fetchProxybdixChannels(homeUrl), 120);
  const q = c.req.query('q');
  const alive = c.req.query('alive');
  if (alive) channels = channels.filter(ch => ch.stream_url);
  if (q) { const query = q.toLowerCase(); channels = channels.filter(ch => ch.name.toLowerCase().includes(query)); }
  return c.json(makeResponse(true, { channels, total: channels.length, cached_at: new Date().toISOString() }));
});

app.get('/api/v4/channels/:channel_id', rateLimiterMiddleware(100, 60), async (c) => {
  const homeUrl = getV4Home(c);
  const channels = await getCachedOrFetch(c, 'proxybdix_channels', () => fetchProxybdixChannels(homeUrl), 120);
  const channelId = c.req.param('channel_id');
  const channel = channels.find(ch => ch.id === channelId);
  if (!channel) return c.json(makeResponse(false, null, { code: 'HTTP_404', message: 'Channel not found' }), 404);
  return c.json(makeResponse(true, channel));
});

app.get('/api/v4/channels/:channel_id/stream', rateLimiterMiddleware(100, 60), async (c) => {
  const homeUrl = getV4Home(c);
  const channels = await getCachedOrFetch(c, 'proxybdix_channels', () => fetchProxybdixChannels(homeUrl), 120);
  const channelId = c.req.param('channel_id');
  const channel = channels.find(ch => ch.id === channelId);
  if (!channel) return c.json(makeResponse(false, null, { code: 'HTTP_404', message: 'Channel not found' }), 404);
  if (!channel.stream_url) return c.json(makeResponse(false, null, { code: 'HTTP_400', message: 'Stream URL not available' }), 400);
  return c.json(makeResponse(true, {
    id: channel.id, name: channel.name, url: channel.stream_url, type: channel.stream_type,
    drm_kid: channel.drm_kid, drm_key: channel.drm_key
  }));
});

app.get('/api/v4/proxy', rateLimiterMiddleware(100, 60), async (c) => {
  const url = c.req.query('url');
  if (!url || url.length < 10) return c.json(makeResponse(false, null, { code: 'HTTP_400', message: 'url parameter required' }), 400);
  const homeUrl = getV4Home(c);
  try {
    const resp = await fetch(url, {
      headers: {
        'User-Agent': nextUA(), 'Accept': '*/*', 'Accept-Language': 'en-US,en;q=0.9',
        'Referer': `${homeUrl}/`, 'Origin': homeUrl
      },
      redirect: 'follow'
    });
    let body = await resp.arrayBuffer();
    let contentType = resp.headers.get('content-type') || 'application/octet-stream';

    if (body.byteLength > 10) {
      const head = new TextDecoder().decode(body.slice(0, 50));
      const reqUrl = new URL(c.req.url);
      const proxyBase = `${reqUrl.origin}/api/v4/proxy?url=`;
      const origUrl = new URL(url);
      const baseDir = origUrl.pathname.substring(0, origUrl.pathname.lastIndexOf('/') + 1);

      if (head.startsWith('#EXTM3U')) {
        contentType = 'application/vnd.apple.mpegurl';
        const text = new TextDecoder().decode(body);
        const rewritten = text.split('\n').map(line => {
          const trimmed = line.trim();
          if (!trimmed || trimmed.startsWith('#')) return line;
          try {
            const resolved = trimmed.startsWith('http') ? trimmed : new URL(trimmed, origUrl.origin + baseDir).href;
            return proxyBase + encodeURIComponent(resolved);
          } catch { return line; }
        }).join('\n');
        body = new TextEncoder().encode(rewritten).buffer;
      } else if (head.includes('<MPD') || head.includes('<?xml')) {
        contentType = 'application/dash+xml';
        let text = new TextDecoder().decode(body);
        const cdnBase = origUrl.origin + baseDir;
        if (!text.includes('<BaseURL')) {
          text = text.replace(/(<MPD[^>]*>)/, `$1<BaseURL>${cdnBase}</BaseURL>`);
        }
        body = new TextEncoder().encode(text).buffer;
      }
    }

    const isSegment = url.match(/\.(ts|mp4|m4s)($|\?)/) || url.includes('/seg_') || url.includes('/segment') || url.includes('/init');
    const cacheMaxAge = isSegment ? 86400 : 60;
    return new Response(body, {
      status: resp.status,
      headers: { 'Content-Type': contentType, 'Access-Control-Allow-Origin': '*', 'Cache-Control': `public, max-age=${cacheMaxAge}` }
    });
  } catch (e) {
    return c.json(makeResponse(false, null, { code: 'HTTP_502', message: 'Failed to fetch stream' }), 502);
  }
});

app.get('/api/v4/stats', rateLimiterMiddleware(100, 60), async (c) => {
  const homeUrl = getV4Home(c);
  const channels = await getCachedOrFetch(c, 'proxybdix_channels', () => fetchProxybdixChannels(homeUrl), 120);
  let users = 0;
  try { const data = await fetchJson(`${homeUrl}/api.php?action=count`); users = data.users || 0; } catch (e) {}
  return c.json(makeResponse(true, { online_users: users, channel_count: channels.length, cached_at: new Date().toISOString() }));
});

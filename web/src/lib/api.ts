import { mockMatches, mockChannels, mockStats, Match, ChannelInfo, PlatformStats } from './mockData';

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const SECRET_KEY = process.env.KHELADEKHO_SECRET_KEY || 'production-super-secret-key-fallback-change-me';

async function fetchAPI<T>(path: string, options: RequestInit = {}): Promise<T | null> {
  try {
    const res = await fetch(`${BASE_URL}${path}`, {
      ...options,
      headers: {
        'Accept': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        ...options.headers,
      },
      next: { revalidate: 30 } // Cache at Next.js edge for 30s
    });
    if (!res.ok) return null;
    const body = await res.json();
    return body.success ? (body.data as T) : null;
  } catch (err) {
    console.error(`API Fetch failed for ${path}:`, err);
    return null;
  }
}

// Generate cryptographic headers for streaming endpoint
export async function getSignedStreamHeaders(path: string): Promise<Record<string, string>> {
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const message = `${timestamp}:${path}`;
  
  let signature = '';
  if (typeof window === 'undefined') {
    // Only run on Node.js server environment to keep secret key hidden
    const crypto = await import('crypto');
    signature = crypto
      .createHmac('sha256', SECRET_KEY)
      .update(message)
      .digest('hex');
  } else {
    console.warn("HMAC signature generation requested on client. Security risk!");
  }
  
  return {
    'X-Signature-Token': signature,
    'X-Signature-Timestamp': timestamp,
  };
}

export async function getMatches(): Promise<{ matches: Match[]; total: number }> {
  const data = await fetchAPI<{ matches: Match[]; total: number }>('/api/v1/matches');
  if (data) return data;
  return { matches: [], total: 0 };
}

export async function getLiveMatches(): Promise<Match[]> {
  const data = await fetchAPI<{ matches: Match[] }>('/api/v1/matches/live');
  if (data) return data.matches;
  return [];
}

export async function getMatch(id: string): Promise<Match | null> {
  const data = await fetchAPI<Match>(`/api/v1/matches/${id}`);
  return data;
}

export async function getChannels(): Promise<{ channels: ChannelInfo[]; total: number }> {
  const data = await fetchAPI<{ channels: ChannelInfo[]; total: number }>('/api/v1/channels');
  if (data) return data;
  return { channels: [], total: 0 };
}

export async function getLiveChannels(): Promise<ChannelInfo[]> {
  const data = await fetchAPI<{ channels: ChannelInfo[] }>('/api/v1/channels/live');
  if (data) return data.channels;
  return [];
}

export async function getStats(): Promise<PlatformStats | null> {
  const data = await fetchAPI<{ stats: PlatformStats }>('/api/v1/stats');
  if (data) return data.stats;
  return null;
}

export async function getStreamData(channelKey: string): Promise<any> {
  const path = `/api/v1/channels/${channelKey}/stream`;
  const headers = await getSignedStreamHeaders(path);
  
  const data = await fetchAPI<any>(path, { headers });
  return data;
}

export interface TeamInfo {
  name: string;
  flag_url: string | null;
}

export interface VoteSummary {
  total: number;
  team1_pct: number;
  draw_pct: number;
  team2_pct: number;
  winner: string | null;
}

export interface Match {
  match_id: string;
  group: string;
  stage: string;
  team1: TeamInfo;
  team2: TeamInfo;
  start_time: string | null;
  end_time: string | null;
  status: 'live' | 'upcoming' | 'finished';
  vote?: VoteSummary;
  countdown_label?: string;
  score1?: number;
  score2?: number;
  league_id?: string;
}

export interface ChannelInfo {
  key: string;
  name: string;
  image_url: string | null;
  category: string;
  quality: string;
  status: string;
  sort_order: number;
  total_views: number;
  live_viewers: number;
  resolution: string;
  source_types: string[];
}

export interface PlatformStats {
  live_viewers: number;
  all_views: number;
  active_channels: number;
  total_channels: number;
}

export interface League {
  id: string;
  name: string;
  logo: string;
  description: string;
  country: string;
}

// Static League Directory metadata (No standings data, just names/logos for navigation and display)
export const leagueDirectory: Record<string, League> = {
  "fifa-world-cup": {
    id: "fifa-world-cup",
    name: "FIFA World Cup 2026",
    logo: "https://upload.wikimedia.org/wikipedia/commons/4/4b/FIFA_WorldCup_logo.svg",
    description: "The premier international association football championship contested by the men's national teams.",
    country: "North America"
  },
  "premier-league": {
    id: "premier-league",
    name: "Premier League",
    logo: "https://upload.wikimedia.org/wikipedia/en/f/f2/Premier_League_Logo.svg",
    description: "The top level of the English football league system, contested by 20 clubs.",
    country: "England"
  },
  "la-liga": {
    id: "la-liga",
    name: "La Liga",
    logo: "https://upload.wikimedia.org/wikipedia/commons/1/13/LaLiga.svg",
    description: "The men's top professional football division of the Spanish football league system.",
    country: "Spain"
  }
};

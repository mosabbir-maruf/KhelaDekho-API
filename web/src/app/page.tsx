import React from 'react';
import Link from 'next/link';
import { Play, Calendar, Users, Eye, TrendingUp, Trophy } from 'lucide-react';
import { getMatches, getChannels, getStats } from '../lib/api';
import MatchCard from '../components/MatchCard';

export const revalidate = 30; // ISR cache every 30s

export default async function Home() {
  const matchesData = await getMatches();
  const channelsData = await getChannels();
  const stats = await getStats();

  const liveMatches = matchesData.matches.filter(m => m.status === 'live');
  const upcomingMatches = matchesData.matches.filter(m => m.status === 'upcoming');
  
  // Choose featured match: first live match, or first upcoming, or fallback
  const featuredMatch = liveMatches[0] || upcomingMatches[0] || matchesData.matches[0];
  const channels = channelsData.channels;

  return (
    <div className="space-y-10 pb-12">
      {/* 1. Hero Cinematic Banner */}
      {featuredMatch && (
        <div 
          className="relative overflow-hidden rounded-3xl border border-white/5 bg-cover bg-center"
          style={{
            backgroundImage: `linear-gradient(rgba(9, 9, 11, 0.2), rgba(9, 9, 11, 0.95)), url('https://images.unsplash.com/photo-1508098682722-e99c43a406b2?q=80&w=1200&auto=format&fit=crop')`,
            height: '420px'
          }}
        >
          <div className="absolute inset-0 flex flex-col justify-end p-6 md:p-12">
            <div className="flex flex-wrap items-center gap-3">
              {featuredMatch.status === 'live' ? (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-red-500/15 px-3 py-1 text-[10px] font-bold text-red-500 uppercase tracking-widest">
                  <span className="h-1.5 w-1.5 rounded-full bg-red-500 animate-ping" />
                  Live Featured Match
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-zinc-900/90 border border-white/10 px-3 py-1 text-[10px] font-medium text-zinc-400">
                  Featured Match
                </span>
              )}
              <span className="text-xs text-zinc-400 font-semibold">{featuredMatch.stage} • {featuredMatch.group || 'Tournament'}</span>
            </div>

            <h1 className="mt-4 text-3xl font-extrabold tracking-tight text-white md:text-5xl max-w-3xl leading-tight">
              {featuredMatch.team1.name} vs {featuredMatch.team2.name}
            </h1>

            <div className="mt-8 flex flex-wrap items-center gap-4">
              <Link 
                href={`/live/wctveng`} 
                className="flex items-center gap-2 rounded-xl bg-red-500 px-6 py-3 text-sm font-bold text-white transition hover:bg-red-600 shadow-lg shadow-red-500/20"
              >
                <Play className="h-4 w-4 fill-current" />
                Tune In Live
              </Link>
              {featuredMatch.start_time && (
                <span className="flex items-center gap-2 rounded-xl border border-white/10 bg-black/40 px-5 py-3 text-xs font-semibold text-zinc-400 backdrop-blur-md">
                  <Calendar className="h-4 w-4" />
                  {new Date(featuredMatch.start_time).toLocaleString(undefined, { weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                </span>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 2. Platform Real-time Metrics */}
      {stats && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="rounded-2xl border border-white/5 bg-zinc-900/25 p-5 backdrop-blur-md">
            <span className="text-[11px] font-bold uppercase tracking-wider text-zinc-500">Live Viewers</span>
            <div className="mt-2 text-2xl font-black text-white tabular-nums flex items-baseline gap-2">
              {stats.live_viewers.toLocaleString()}
              <span className="h-2 w-2 rounded-full bg-red-500 animate-pulse" />
            </div>
          </div>
          <div className="rounded-2xl border border-white/5 bg-zinc-900/25 p-5 backdrop-blur-md">
            <span className="text-[11px] font-bold uppercase tracking-wider text-zinc-500">Active Channels</span>
            <div className="mt-2 text-2xl font-black text-white tabular-nums">{stats.active_channels}</div>
          </div>
          <div className="rounded-2xl border border-white/5 bg-zinc-900/25 p-5 backdrop-blur-md">
            <span className="text-[11px] font-bold uppercase tracking-wider text-zinc-500">Platform Channels</span>
            <div className="mt-2 text-2xl font-black text-white tabular-nums">{stats.total_channels}</div>
          </div>
          <div className="rounded-2xl border border-white/5 bg-zinc-900/25 p-5 backdrop-blur-md">
            <span className="text-[11px] font-bold uppercase tracking-wider text-zinc-500">Accumulated Views</span>
            <div className="mt-2 text-2xl font-black text-white tabular-nums">{stats.all_views.toLocaleString()}</div>
          </div>
        </div>
      )}

      {/* 3. Live Channels Carousel */}
      <div>
        <div className="flex items-center gap-2 mb-6">
          <Play className="h-5 w-5 text-red-500 fill-current" />
          <h2 className="text-xl font-bold tracking-tight text-white">Live Channels</h2>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
          {channels.map((ch) => (
            <Link 
              key={ch.key}
              href={`/live/${ch.key}`}
              className="group relative overflow-hidden rounded-2xl border border-white/5 bg-zinc-900/30 transition hover:-translate-y-1 hover:border-white/10 hover:bg-zinc-900/50 backdrop-blur-md"
            >
              <div className="aspect-video w-full relative bg-zinc-950">
                <img 
                  src={ch.image_url || 'https://upload.wikimedia.org/wikipedia/commons/4/4b/FIFA_WorldCup_logo.svg'} 
                  alt={ch.name} 
                  className="h-full w-full object-contain p-4 transition-transform duration-500 group-hover:scale-105"
                />
                <span className="absolute top-3 right-3 inline-flex items-center gap-1 rounded-full bg-red-500 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider text-white">
                  Live
                </span>
              </div>
              <div className="p-4">
                <h3 className="text-sm font-semibold text-white group-hover:text-red-500 transition-colors">{ch.name}</h3>
                <div className="mt-3 flex items-center justify-between text-[11px] text-zinc-500 font-medium">
                  <span className="flex items-center gap-1"><Users className="h-3.5 w-3.5" /> {ch.live_viewers} live</span>
                  <span className="flex items-center gap-1"><Eye className="h-3.5 w-3.5" /> {ch.total_views.toLocaleString()} views</span>
                </div>
              </div>
            </Link>
          ))}
        </div>
      </div>

      {/* 4. Upcoming & Live Matches Section */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-10">
        {/* Matches lists */}
        <div className="lg:col-span-2 space-y-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Calendar className="h-5 w-5 text-zinc-400" />
              <h2 className="text-xl font-bold tracking-tight text-white">Match Schedule</h2>
            </div>
            <Link href="/matches" className="text-xs font-semibold text-zinc-500 hover:text-red-500 transition-colors">View All Schedule</Link>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
            {matchesData.matches.slice(0, 4).map((match) => (
              <MatchCard key={match.match_id} match={match} />
            ))}
          </div>
        </div>

        {/* Popular leagues */}
        <div className="space-y-6">
          <div className="flex items-center gap-2">
            <Trophy className="h-5 w-5 text-zinc-400" />
            <h2 className="text-xl font-bold tracking-tight text-white">Featured Leagues</h2>
          </div>
          <div className="space-y-4">
            {[
              { id: 'fifa-world-cup', name: 'FIFA World Cup 2026', country: 'International', matches: 72 },
              { id: 'premier-league', name: 'Premier League', country: 'England', matches: 380 },
              { id: 'la-liga', name: 'La Liga', country: 'Spain', matches: 380 }
            ].map((lg) => (
              <Link 
                key={lg.id}
                href={`/leagues/${lg.id}`}
                className="flex items-center justify-between rounded-xl border border-white/5 bg-zinc-900/20 p-4 transition hover:bg-zinc-900/50 hover:border-white/10"
              >
                <div>
                  <h4 className="text-sm font-semibold text-white">{lg.name}</h4>
                  <span className="text-[10px] text-zinc-500">{lg.country}</span>
                </div>
                <span className="text-[11px] font-semibold text-zinc-400 tabular-nums">{lg.matches} Matches</span>
              </Link>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

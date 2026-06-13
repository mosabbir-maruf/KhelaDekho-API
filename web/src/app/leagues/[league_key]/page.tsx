import React from 'react';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { Trophy, ArrowLeft, Calendar, Shield } from 'lucide-react';
import { leagueDirectory } from '../../../lib/types';
import { getMatches } from '../../../lib/api';
import MatchCard from '../../../components/MatchCard';

interface PageProps {
  params: Promise<{ league_key: string }>;
}

export default async function LeaguePage({ params }: PageProps) {
  const { league_key } = await params;
  const league = leagueDirectory[league_key];

  if (!league) {
    notFound();
  }

  // Get matches belonging to this league from the live API
  const matchesData = await getMatches();
  const leagueMatches = matchesData.matches.filter(m => 
    m.league_id === league.id || 
    m.group.toLowerCase().includes(league.id.toLowerCase()) || 
    m.stage.toLowerCase().includes(league.id.toLowerCase()) ||
    league_key === 'fifa-world-cup' // fallback since parsed matches are World Cup matches
  );
  const liveMatches = leagueMatches.filter(m => m.status === 'live');
  const upcomingMatches = leagueMatches.filter(m => m.status === 'upcoming');

  return (
    <div className="space-y-10 pb-12">
      {/* Back navigation */}
      <div className="flex items-center gap-3">
        <Link 
          href="/" 
          className="flex h-9 w-9 items-center justify-center rounded-lg border border-white/5 bg-zinc-900/40 text-zinc-400 hover:text-white transition"
        >
          <ArrowLeft className="h-4 w-4" />
        </Link>
        <span className="text-xs font-semibold text-zinc-500">Back to Dashboard</span>
      </div>

      {/* League Header Banner */}
      <div className="relative overflow-hidden rounded-2xl border border-white/5 bg-zinc-900/10 p-6 md:p-8 flex flex-col md:flex-row items-center gap-6 backdrop-blur-md">
        <div className="flex h-20 w-20 items-center justify-center rounded-2xl bg-zinc-950 p-4 border border-white/5 shadow-inner">
          <img src={league.logo} alt={league.name} className="h-full w-full object-contain" />
        </div>
        <div className="flex-1 text-center md:text-left space-y-2">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-zinc-900/80 border border-white/5 px-2.5 py-0.5 text-[9px] font-bold text-zinc-400 uppercase tracking-widest">
            {league.country}
          </span>
          <h1 className="text-2xl font-bold text-white md:text-3xl">{league.name}</h1>
          <p className="text-xs text-zinc-500 max-w-xl leading-relaxed">{league.description}</p>
        </div>
      </div>

      {/* Grid: Matches vs Standings */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-10">
        {/* Left: Standings Table */}
        <div className="lg:col-span-2 space-y-6">
          <div className="flex items-center gap-2">
            <Trophy className="h-5 w-5 text-zinc-400" />
            <h2 className="text-lg font-bold text-white">Standings Table</h2>
          </div>
          <div className="overflow-x-auto rounded-2xl border border-white/5 bg-zinc-950/30 backdrop-blur-md p-8 text-center flex flex-col items-center justify-center min-h-[200px]">
            <Trophy className="h-8 w-8 text-zinc-700 mb-3 animate-pulse" />
            <h3 className="text-sm font-semibold text-zinc-400">Standings Unavailable</h3>
            <p className="text-xs text-zinc-500 mt-1 max-w-xs">
              Live standings are currently not served by the API.
            </p>
          </div>
        </div>

        {/* Right: Matches Sidebar */}
        <div className="space-y-6">
          <div className="flex items-center gap-2">
            <Calendar className="h-5 w-5 text-zinc-400" />
            <h2 className="text-lg font-bold text-white">League Matches</h2>
          </div>
          {leagueMatches.length > 0 ? (
            <div className="space-y-4">
              {leagueMatches.map((match) => (
                <MatchCard key={match.match_id} match={match} />
              ))}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center rounded-2xl border border-white/5 bg-zinc-950/40 p-8 text-center">
              <Calendar className="h-6 w-6 text-zinc-700" />
              <h4 className="mt-3 text-xs font-semibold text-zinc-500">No Scheduled Matches</h4>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

import React from 'react';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { Trophy, ArrowLeft, Calendar, Shield } from 'lucide-react';
import { mockLeagues, mockMatches } from '../../../lib/mockData';
import MatchCard from '../../../components/MatchCard';

interface PageProps {
  params: Promise<{ league_key: string }>;
}

export default async function LeaguePage({ params }: PageProps) {
  const { league_key } = await params;
  const league = mockLeagues.find(lg => lg.id === league_key);

  if (!league) {
    notFound();
  }

  // Get matches belonging to this league
  const leagueMatches = mockMatches.filter(m => m.league_id === league.id);
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
          <div className="overflow-x-auto rounded-2xl border border-white/5 bg-zinc-950/30 backdrop-blur-md">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="border-b border-white/5 bg-[#0e0e11] text-zinc-500 font-semibold uppercase tracking-wider">
                  <th className="py-4 px-5 w-12 text-center">Pos</th>
                  <th className="py-4 px-5">Team</th>
                  <th className="py-4 px-5 text-center">P</th>
                  <th className="py-4 px-5 text-center">W</th>
                  <th className="py-4 px-5 text-center">D</th>
                  <th className="py-4 px-5 text-center">L</th>
                  <th className="py-4 px-5 text-center">Goals</th>
                  <th className="py-4 px-5 text-center">PTS</th>
                </tr>
              </thead>
              <tbody>
                {league.standings.map((team) => (
                  <tr key={team.team} className="border-b border-white/5 hover:bg-white/[0.01] transition-colors font-medium text-zinc-300">
                    <td className="py-4 px-5 text-center font-bold text-white">{team.rank}</td>
                    <td className="py-4 px-5 flex items-center gap-3">
                      <Shield className="h-4.5 w-4.5 text-zinc-600" />
                      <span className="font-semibold text-white">{team.team}</span>
                    </td>
                    <td className="py-4 px-5 text-center tabular-nums">{team.played}</td>
                    <td className="py-4 px-5 text-center tabular-nums">{team.won}</td>
                    <td className="py-4 px-5 text-center tabular-nums">{team.drawn}</td>
                    <td className="py-4 px-5 text-center tabular-nums">{team.lost}</td>
                    <td className="py-4 px-5 text-center tabular-nums text-zinc-500">{team.goals}</td>
                    <td className="py-4 px-5 text-center tabular-nums font-bold text-white">{team.points}</td>
                  </tr>
                ))}
              </tbody>
            </table>
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

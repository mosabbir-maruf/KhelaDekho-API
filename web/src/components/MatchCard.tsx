"use client";

import React from 'react';
import Link from 'next/link';
import { Calendar, Play, CheckCircle } from 'lucide-react';
import { Match } from '../lib/mockData';

interface MatchCardProps {
  match: Match;
}

export default function MatchCard({ match }: MatchCardProps) {
  const isLive = match.status === 'live';
  const isUpcoming = match.status === 'upcoming';
  const isFinished = match.status === 'finished';

  const formattedDate = match.start_time
    ? new Date(match.start_time).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
    : 'TBD';

  const formattedTime = match.start_time
    ? new Date(match.start_time).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
    : 'TBD';

  return (
    <div className="group relative overflow-hidden rounded-2xl border border-white/5 bg-zinc-900/30 p-5 transition-all duration-300 hover:-translate-y-1 hover:border-white/10 hover:bg-zinc-900/50 backdrop-blur-md">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
          {match.stage} {match.group ? `• ${match.group}` : ''}
        </span>
        
        {isLive && (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-red-500/10 px-2.5 py-0.5 text-[10px] font-bold text-red-500 uppercase tracking-widest">
            <span className="h-1.5 w-1.5 rounded-full bg-red-500 animate-ping" />
            Live
          </span>
        )}
        
        {isFinished && (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-zinc-800 px-2.5 py-0.5 text-[10px] font-medium text-zinc-400">
            <CheckCircle className="h-3 w-3" />
            FT
          </span>
        )}

        {isUpcoming && (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-zinc-900/80 border border-white/5 px-2.5 py-0.5 text-[10px] font-medium text-zinc-400">
            <Calendar className="h-3 w-3" />
            {formattedDate}
          </span>
        )}
      </div>

      <div className="mt-6 flex flex-col gap-4">
        {/* Team 1 */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {match.team1.flag_url ? (
              <img 
                src={match.team1.flag_url} 
                alt={match.team1.name} 
                className="h-6 w-8 rounded-sm object-cover border border-white/5" 
                onError={(e) => { (e.target as HTMLImageElement).src = 'https://flagcdn.com/un.svg'; }}
              />
            ) : (
              <div className="h-6 w-8 rounded-sm bg-zinc-800 border border-white/5" />
            )}
            <span className="text-sm font-semibold text-white group-hover:text-red-500 transition-colors">
              {match.team1.name}
            </span>
          </div>
          {typeof match.score1 === 'number' && (
            <span className="text-base font-bold text-white tabular-nums">{match.score1}</span>
          )}
        </div>

        {/* Team 2 */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {match.team2.flag_url ? (
              <img 
                src={match.team2.flag_url} 
                alt={match.team2.name} 
                className="h-6 w-8 rounded-sm object-cover border border-white/5"
                onError={(e) => { (e.target as HTMLImageElement).src = 'https://flagcdn.com/un.svg'; }}
              />
            ) : (
              <div className="h-6 w-8 rounded-sm bg-zinc-800 border border-white/5" />
            )}
            <span className="text-sm font-semibold text-white group-hover:text-red-500 transition-colors">
              {match.team2.name}
            </span>
          </div>
          {typeof match.score2 === 'number' && (
            <span className="text-base font-bold text-white tabular-nums">{match.score2}</span>
          )}
        </div>
      </div>

      <div className="mt-6 flex items-center justify-between border-t border-white/5 pt-4">
        {isUpcoming ? (
          <span className="text-xs font-semibold text-zinc-500">
            Starts at {formattedTime}
          </span>
        ) : (
          <span className="text-xs font-semibold text-zinc-500">
            Playable stream feeds
          </span>
        )}

        {isLive && (
          <Link 
            href={`/live/wctveng`} // fallback channel_key
            className="flex items-center gap-1.5 rounded-lg bg-red-500 px-3 py-1.5 text-xs font-bold text-white transition-all hover:bg-red-600"
          >
            <Play className="h-3 w-3 fill-current" />
            Watch
          </Link>
        )}
      </div>
    </div>
  );
}

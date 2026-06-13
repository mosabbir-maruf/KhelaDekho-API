import React from 'react';
import Link from 'next/link';
import { Search, Compass, ChevronRight, Activity } from 'lucide-react';
import { getMatches, getChannels } from '../../lib/api';
import MatchCard from '../../components/MatchCard';
import { Match, ChannelInfo } from '../../lib/mockData';

interface PageProps {
  searchParams: Promise<{ q?: string }>;
}

export const revalidate = 10;

export default async function SearchPage({ searchParams }: PageProps) {
  const { q } = await searchParams;
  
  const matchesData = await getMatches();
  const channelsData = await getChannels();
  
  let matchResults: Match[] = [];
  let channelResults: ChannelInfo[] = [];
  
  if (q) {
    const query = q.toLowerCase();
    matchResults = matchesData.matches.filter(m => 
      m.team1.name.toLowerCase().includes(query) || 
      m.team2.name.toLowerCase().includes(query) ||
      (m.group && m.group.toLowerCase().includes(query)) ||
      (m.stage && m.stage.toLowerCase().includes(query))
    );
    
    channelResults = channelsData.channels.filter(ch => 
      ch.name.toLowerCase().includes(query) || 
      ch.category.toLowerCase().includes(query)
    );
  }

  const trendingSearches = [
    "World Cup ENG",
    "Argentina vs France",
    "Premier League",
    "D Sports",
    "England vs Germany"
  ];

  return (
    <div className="space-y-10 pb-12">
      {/* Title */}
      <div className="flex items-center gap-3">
        <Search className="h-6 w-6 text-zinc-400" />
        <h1 className="text-xl font-bold tracking-tight text-white md:text-2xl">Search Streams</h1>
      </div>

      {/* Large cinematic search bar */}
      <form className="relative w-full" method="GET" action="/search">
        <Search className="absolute top-4.5 left-5 h-5 w-5 text-zinc-500" />
        <input 
          type="text" 
          name="q"
          defaultValue={q || ''}
          placeholder="Search matches, channels, leagues, or teams..." 
          className="w-full rounded-2xl border border-white/5 bg-zinc-900/30 py-4.5 pl-14 pr-6 text-sm text-white outline-none placeholder:text-zinc-600 focus:border-white/10 focus:bg-zinc-900/50 backdrop-blur-md"
        />
      </form>

      {q ? (
        // Results Area
        <div className="space-y-8">
          <div>
            <h2 className="text-xs font-bold text-zinc-500 uppercase tracking-widest mb-4">Channel Results ({channelResults.length})</h2>
            {channelResults.length > 0 ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-6">
                {channelResults.map(ch => (
                  <Link 
                    key={ch.key}
                    href={`/live/${ch.key}`}
                    className="flex items-center gap-4 rounded-xl border border-white/5 bg-zinc-900/20 p-4 transition hover:bg-zinc-900/50"
                  >
                    <div className="flex h-12 w-16 items-center justify-center rounded-lg bg-zinc-950 p-2 border border-white/5">
                      <img src={ch.image_url || 'https://upload.wikimedia.org/wikipedia/commons/4/4b/FIFA_WorldCup_logo.svg'} alt={ch.name} className="h-full w-full object-contain" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <h4 className="text-sm font-semibold text-white truncate">{ch.name}</h4>
                      <span className="text-[10px] text-zinc-500">{ch.category} • {ch.quality}</span>
                    </div>
                    <ChevronRight className="h-4 w-4 text-zinc-600" />
                  </Link>
                ))}
              </div>
            ) : (
              <p className="text-xs text-zinc-600">No channels match your query.</p>
            )}
          </div>

          <div className="border-t border-white/5 pt-8">
            <h2 className="text-xs font-bold text-zinc-500 uppercase tracking-widest mb-4">Match Results ({matchResults.length})</h2>
            {matchResults.length > 0 ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
                {matchResults.map(match => (
                  <MatchCard key={match.match_id} match={match} />
                ))}
              </div>
            ) : (
              <p className="text-xs text-zinc-600">No matches match your query.</p>
            )}
          </div>
        </div>
      ) : (
        // Suggestions Area
        <div className="grid grid-cols-1 md:grid-cols-3 gap-10">
          <div className="md:col-span-2 space-y-4">
            <div className="flex items-center gap-2 text-zinc-400">
              <Compass className="h-4.5 w-4.5" />
              <h3 className="text-xs font-bold uppercase tracking-wider">Trending Searches</h3>
            </div>
            <div className="flex flex-wrap gap-2.5">
              {trendingSearches.map((term) => (
                <Link
                  key={term}
                  href={`/search?q=${encodeURIComponent(term)}`}
                  className="rounded-xl border border-white/5 bg-zinc-900/20 px-4 py-2.5 text-xs font-semibold text-zinc-400 hover:text-white hover:border-white/10 hover:bg-zinc-900/40 transition"
                >
                  {term}
                </Link>
              ))}
            </div>
          </div>
          
          <div className="rounded-2xl border border-white/5 bg-zinc-900/10 p-5 backdrop-blur-md space-y-3">
            <h4 className="text-xs font-bold text-white uppercase tracking-wider">Decryption Search Tip</h4>
            <p className="text-[11px] text-zinc-500 leading-relaxed">
              Find and stream encrypted sporting events using their team names or league stage identifiers directly in the query field.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

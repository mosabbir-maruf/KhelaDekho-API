import React from 'react';
import { Calendar, Search, Filter } from 'lucide-react';
import { getMatches } from '../../lib/api';
import MatchCard from '../../components/MatchCard';

interface PageProps {
  searchParams: Promise<{ status?: string; search?: string }>;
}

export const revalidate = 30;

export default async function MatchesPage({ searchParams }: PageProps) {
  const { status, search } = await searchParams;
  
  const matchesData = await getMatches();
  let matches = matchesData.matches;

  // Filter by status
  if (status && status !== 'all') {
    matches = matches.filter(m => m.status === status);
  }

  // Filter by search query
  if (search) {
    const sLower = search.toLowerCase();
    matches = matches.filter(m => 
      m.team1.name.toLowerCase().includes(sLower) || 
      m.team2.name.toLowerCase().includes(sLower) ||
      (m.stage && m.stage.toLowerCase().includes(sLower))
    );
  }

  const tabs = [
    { label: 'All Matches', value: 'all', href: '/matches' },
    { label: 'Live Now', value: 'live', href: '/matches?status=live' },
    { label: 'Upcoming', value: 'upcoming', href: '/matches?status=upcoming' },
    { label: 'Finished', value: 'finished', href: '/matches?status=finished' },
  ];

  const currentTab = status || 'all';

  return (
    <div className="space-y-8 pb-12">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <Calendar className="h-6 w-6 text-zinc-400" />
          <h1 className="text-xl font-bold tracking-tight text-white md:text-2xl">Matches Schedule</h1>
        </div>
      </div>

      {/* Tabs and search filters */}
      <div className="flex flex-wrap items-center justify-between border-b border-white/5 pb-4 gap-4">
        {/* Navigation Tabs */}
        <div className="flex rounded-xl bg-zinc-950 p-1 border border-white/5">
          {tabs.map((tab) => (
            <a
              key={tab.value}
              href={tab.href}
              className={`rounded-lg px-4 py-2 text-xs font-semibold transition ${
                currentTab === tab.value
                  ? 'bg-zinc-800 text-white shadow-sm ring-1 ring-white/10'
                  : 'text-zinc-500 hover:text-white'
              }`}
            >
              {tab.label}
            </a>
          ))}
        </div>

        {/* Search Input Box */}
        <form className="relative w-full sm:w-72" method="GET" action="/matches">
          {status && <input type="hidden" name="status" value={status} />}
          <Search className="absolute top-2.5 left-3.5 h-4 w-4 text-zinc-600" />
          <input 
            type="text" 
            name="search"
            defaultValue={search || ''}
            placeholder="Search matches or teams..." 
            className="w-full rounded-xl border border-white/5 bg-zinc-900/40 py-2.5 pl-10 pr-4 text-xs text-white outline-none placeholder:text-zinc-600 focus:border-white/10 focus:bg-zinc-900/60"
          />
        </form>
      </div>

      {/* Matches Grid */}
      {matches.length > 0 ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
          {matches.map((match) => (
            <MatchCard key={match.match_id} match={match} />
          ))}
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center rounded-2xl border border-white/5 bg-zinc-950/40 p-12 text-center">
          <Filter className="h-8 w-8 text-zinc-600" />
          <h3 className="mt-4 text-sm font-semibold text-white">No Matches Found</h3>
          <p className="mt-1 text-xs text-zinc-500 max-w-xs">
            We couldn't find any matches matching your filters. Try adjusting your query.
          </p>
        </div>
      )}
    </div>
  );
}

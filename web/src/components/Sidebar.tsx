"use client";

import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Home, Tv, Calendar, Search, Settings, Activity } from 'lucide-react';

export default function Sidebar() {
  const pathname = usePathname();

  const menuItems = [
    { name: 'Home', href: '/', icon: Home },
    { name: 'Live TV', href: '/matches?status=live', icon: Tv },
    { name: 'Matches', href: '/matches', icon: Calendar },
    { name: 'Search', href: '/search', icon: Search },
    { name: 'Settings', href: '/settings', icon: Settings },
  ];

  return (
    <aside className="fixed inset-y-0 left-0 z-20 hidden w-64 flex-col border-r border-white/5 bg-[#09090B] px-6 py-8 md:flex">
      <div className="flex items-center gap-3 px-2">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-red-500/10 text-red-500">
          <Activity className="h-6 w-6 animate-pulse" />
        </div>
        <div>
          <span className="text-lg font-bold tracking-tight text-white">KhelaDekho</span>
          <span className="block text-[10px] uppercase tracking-wider text-zinc-500">Premium Stream</span>
        </div>
      </div>

      <nav className="mt-12 flex-1 space-y-1.5">
        {menuItems.map((item) => {
          const Icon = item.icon;
          const isActive = pathname === item.href || (item.href !== '/' && pathname.startsWith(item.href));

          return (
            <Link
              key={item.name}
              href={item.href}
              className={`flex items-center gap-4 rounded-xl px-4 py-3 text-sm font-medium transition-all duration-300 ${
                isActive
                  ? 'bg-white/5 text-white shadow-sm ring-1 ring-white/10'
                  : 'text-zinc-400 hover:bg-white/[0.02] hover:text-white'
              }`}
            >
              <Icon className={`h-5 w-5 ${isActive ? 'text-red-500' : ''}`} />
              {item.name}
            </Link>
          );
        })}
      </nav>

      <div className="rounded-2xl border border-white/5 bg-zinc-900/40 p-4 backdrop-blur-md">
        <span className="inline-flex items-center gap-1.5 rounded-full bg-red-500/10 px-2 py-0.5 text-[10px] font-medium text-red-400">
          <span className="h-1.5 w-1.5 rounded-full bg-red-500 animate-ping" />
          Live Platform
        </span>
        <h4 className="mt-3 text-xs font-semibold text-white">DRM ClearKey Stream</h4>
        <p className="mt-1 text-[11px] text-zinc-500 leading-relaxed">
          Aggregating and decrypting live feeds natively at the edge.
        </p>
      </div>
    </aside>
  );
}

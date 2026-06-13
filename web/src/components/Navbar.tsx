"use client";

import React, { useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Activity, Menu, X, Home, Tv, Calendar, Search, Settings } from 'lucide-react';

export default function Navbar() {
  const pathname = usePathname();
  const [isOpen, setIsOpen] = useState(false);

  const menuItems = [
    { name: 'Home', href: '/', icon: Home },
    { name: 'Live TV', href: '/matches?status=live', icon: Tv },
    { name: 'Matches', href: '/matches', icon: Calendar },
    { name: 'Search', href: '/search', icon: Search },
    { name: 'Settings', href: '/settings', icon: Settings },
  ];

  return (
    <>
      <header className="sticky top-0 z-10 flex h-16 w-full items-center justify-between border-b border-white/5 bg-[#09090B]/80 px-6 backdrop-blur-md md:pl-72">
        <div className="flex items-center gap-3 md:hidden">
          <Activity className="h-6 w-6 text-red-500 animate-pulse" />
          <span className="text-base font-bold text-white tracking-tight">KhelaDekho</span>
        </div>

        <div className="ml-auto flex items-center gap-4">
          <button 
            className="flex h-10 w-10 items-center justify-center rounded-xl border border-white/5 bg-zinc-900/50 text-zinc-400 hover:text-white md:hidden"
            onClick={() => setIsOpen(!isOpen)}
          >
            {isOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
      </header>

      {/* Mobile Drawer menu */}
      {isOpen && (
        <div className="fixed inset-0 z-30 bg-black/60 backdrop-blur-sm md:hidden" onClick={() => setIsOpen(false)}>
          <aside 
            className="fixed inset-y-0 left-0 w-64 border-r border-white/5 bg-[#09090B] px-6 py-8 flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-3 px-2">
              <Activity className="h-6 w-6 text-red-500 animate-pulse" />
              <span className="text-lg font-bold text-white tracking-tight">KhelaDekho</span>
            </div>

            <nav className="mt-12 flex-1 space-y-1">
              {menuItems.map((item) => {
                const Icon = item.icon;
                const isActive = pathname === item.href || (item.href !== '/' && pathname.startsWith(item.href));

                return (
                  <Link
                    key={item.name}
                    href={item.href}
                    onClick={() => setIsOpen(false)}
                    className={`flex items-center gap-4 rounded-xl px-4 py-3 text-sm font-medium transition-all ${
                      isActive
                        ? 'bg-white/5 text-white ring-1 ring-white/10'
                        : 'text-zinc-400 hover:bg-white/[0.02] hover:text-white'
                    }`}
                  >
                    <Icon className="h-5 w-5" />
                    {item.name}
                  </Link>
                );
              })}
            </nav>
          </aside>
        </div>
      )}
    </>
  );
}

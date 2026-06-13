import React from 'react';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { Activity, Tv, Users, Calendar, ArrowLeft, MessageSquare, ListMusic } from 'lucide-react';
import { getChannels, getStreamData } from '../../../lib/api';
import VideoPlayer from '../../../components/VideoPlayer';

interface PageProps {
  params: Promise<{ channel_key: string }>;
}

export default async function LiveMatchPage({ params }: PageProps) {
  const { channel_key } = await params;
  
  // Fetch channels to get detail metadata
  const channelsData = await getChannels();
  const channel = channelsData.channels.find(ch => ch.key === channel_key);
  
  if (!channel) {
    notFound();
  }

  // Fetch decrypter stream info from API
  const streamData = await getStreamData(channel.key);
  
  const otherChannels = channelsData.channels.filter(ch => ch.key !== channel.key);

  return (
    <div className="space-y-6 pb-12">
      {/* Back button */}
      <div className="flex items-center gap-3">
        <Link 
          href="/" 
          className="flex h-9 w-9 items-center justify-center rounded-lg border border-white/5 bg-zinc-900/40 text-zinc-400 hover:text-white transition"
        >
          <ArrowLeft className="h-4 w-4" />
        </Link>
        <span className="text-xs font-semibold text-zinc-500">Back to Dashboard</span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 items-start">
        {/* Left Video Area & Info */}
        <div className="lg:col-span-2 space-y-6">
          {streamData ? (
            <VideoPlayer 
              streamUrl={streamData.url}
              streamType={streamData.type}
              clearKeys={streamData.clearkey?.keys || null}
              title={channel.name}
            />
          ) : (
            <div className="flex aspect-video w-full flex-col items-center justify-center rounded-2xl border border-white/5 bg-zinc-950 p-6 text-center">
              <Activity className="h-10 w-10 text-red-500 animate-pulse" />
              <h3 className="mt-4 text-base font-bold text-white">Stream Decryption Offline</h3>
              <p className="mt-2 text-xs text-zinc-500 max-w-sm">
                ClearKey tokens or source feeds are currently offline. Check rate limits or verify the token key.
              </p>
            </div>
          )}

          {/* Details Card */}
          <div className="rounded-2xl border border-white/5 bg-zinc-900/20 p-6 backdrop-blur-md space-y-6">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <span className="inline-flex items-center gap-1.5 rounded-full bg-red-500/10 px-2.5 py-0.5 text-[9px] font-bold text-red-500 uppercase tracking-widest">
                  Live Stream
                </span>
                <h1 className="mt-2 text-xl font-bold text-white md:text-2xl">{channel.name}</h1>
              </div>
              <div className="flex items-center gap-4 text-xs font-semibold text-zinc-400">
                <span className="flex items-center gap-1.5"><Users className="h-4 w-4" /> {channel.live_viewers} Watching</span>
                <span className="flex items-center gap-1.5"><Tv className="h-4 w-4" /> {channel.quality} Quality</span>
              </div>
            </div>

            <div className="border-t border-white/5 pt-6">
              <h3 className="text-sm font-semibold text-white">Match Overview</h3>
              <p className="mt-2 text-xs text-zinc-400 leading-relaxed">
                Tune in to live transmission feeds from {channel.name}. Supported on all modern HTML5 browsers featuring dynamic adaptive bitrate (ABR) stream rendering.
              </p>
            </div>
          </div>
        </div>

        {/* Right Sidebar - Other streams & Chat placeholder */}
        <div className="space-y-6">
          {/* Chat placeholder */}
          <div className="rounded-2xl border border-white/5 bg-zinc-900/20 backdrop-blur-md overflow-hidden">
            <div className="flex items-center gap-2 border-b border-white/5 bg-[#0e0e11] px-5 py-4">
              <MessageSquare className="h-4.5 w-4.5 text-red-500" />
              <h3 className="text-xs font-bold text-white uppercase tracking-wider">Live Chat Room</h3>
            </div>
            <div className="h-[280px] p-5 flex flex-col justify-end gap-3 text-xs">
              <div className="space-y-3 flex-1 overflow-y-auto pr-2">
                <div className="flex flex-col gap-0.5">
                  <span className="font-bold text-red-400">MarufMaruf</span>
                  <span className="text-zinc-300">Let's go Argentina! Clean win today!</span>
                </div>
                <div className="flex flex-col gap-0.5">
                  <span className="font-bold text-zinc-500">Alex99</span>
                  <span className="text-zinc-300">Is the stream lagging for anyone else?</span>
                </div>
                <div className="flex flex-col gap-0.5">
                  <span className="font-bold text-zinc-500">VampCloud</span>
                  <span className="text-zinc-300">Just switch to 1080p from the selectors. Works perfect.</span>
                </div>
              </div>
              <div className="mt-4 flex gap-2">
                <input 
                  type="text" 
                  placeholder="Send a chat message..." 
                  disabled
                  className="flex-1 rounded-lg border border-white/5 bg-zinc-950 px-3 py-2 text-xs text-zinc-300 outline-none placeholder:text-zinc-600"
                />
              </div>
            </div>
          </div>

          {/* Related streams */}
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <ListMusic className="h-4.5 w-4.5 text-zinc-400" />
              <h3 className="text-xs font-bold text-white uppercase tracking-wider">Other Channels</h3>
            </div>
            <div className="space-y-3">
              {otherChannels.map((ch) => (
                <Link 
                  key={ch.key}
                  href={`/live/${ch.key}`}
                  className="flex items-center gap-3 rounded-xl border border-white/5 bg-zinc-900/10 p-3 transition hover:bg-zinc-900/40"
                >
                  <div className="h-10 w-16 relative rounded-lg bg-zinc-950 flex items-center justify-center overflow-hidden">
                    <img 
                      src={ch.image_url || 'https://upload.wikimedia.org/wikipedia/commons/4/4b/FIFA_WorldCup_logo.svg'} 
                      alt={ch.name} 
                      className="h-full w-full object-contain p-1.5"
                    />
                  </div>
                  <div>
                    <h4 className="text-xs font-bold text-white truncate max-w-[120px]">{ch.name}</h4>
                    <span className="text-[10px] text-zinc-500">{ch.live_viewers} live</span>
                  </div>
                </Link>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

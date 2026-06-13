"use client";

import React, { useEffect, useRef, useState } from 'react';
import shaka from 'shaka-player';
import Hls from 'hls.js';
import { Sliders, Copy, Check, Play, Pause, Volume2, VolumeX, Maximize2, ShieldCheck } from 'lucide-react';

interface VideoPlayerProps {
  streamUrl: string;
  streamType: string;
  clearKeys?: Record<string, string> | null;
  title?: string;
  onClose?: () => void;
}

export default function VideoPlayer({ streamUrl, streamType, clearKeys, title }: VideoPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [loading, setLoading] = useState(true);
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(false);
  const [copied, setCopied] = useState(false);
  const [qualities, setQualities] = useState<string[]>([]);
  const [currentQuality, setCurrentQuality] = useState('Auto');
  const [drmType, setDrmType] = useState('ClearKey DRM');

  const shakaPlayerRef = useRef<any>(null);
  const hlsRef = useRef<any>(null);

  useEffect(() => {
    let active = true;
    const video = videoRef.current;
    if (!video || !streamUrl) return;

    setLoading(true);
    cleanUp();

    const initPlayer = async () => {
      try {
        if (streamType === 'dash' || streamUrl.endsWith('.mpd')) {
          // Initialize Shaka
          shaka.polyfill.installAll();
          if (!shaka.Player.isBrowserSupported()) {
            throw new Error('Shaka Player is not supported in this browser.');
          }

          const player = new shaka.Player();
          shakaPlayerRef.current = player;
          await player.attach(video);

          if (clearKeys && Object.keys(clearKeys).length > 0) {
            setDrmType('ClearKey DRM');
            player.configure({
              drm: {
                clearKeys: clearKeys
              }
            });
          } else {
            setDrmType('Unencrypted');
          }

          await player.load(streamUrl);
          
          if (active) {
            setLoading(false);
            setPlaying(true);
            video.play().catch(() => setPlaying(false));
            
            // Extract Variant Tracks
            const tracks = player.getVariantTracks();
            const uniqueQualities = Array.from(new Set(tracks.map((t: any) => `${t.height}p`))).sort((a, b) => parseInt(b) - parseInt(a));
            setQualities(uniqueQualities);
          }
        } else if (streamType === 'hls' || streamUrl.endsWith('.m3u8')) {
          setDrmType('Unencrypted HLS');
          if (Hls.isSupported()) {
            const hls = new Hls({ maxMaxBufferLength: 10 });
            hlsRef.current = hls;
            hls.loadSource(streamUrl);
            hls.attachMedia(video);
            
            hls.on(Hls.Events.MANIFEST_PARSED, (_, data) => {
              if (active) {
                setLoading(false);
                setPlaying(true);
                video.play().catch(() => setPlaying(false));
                
                const uniqueQualities = data.levels.map((l: any) => `${l.height}p`).sort((a, b) => parseInt(b) - parseInt(a));
                setQualities(uniqueQualities);
              }
            });
          } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
            video.src = streamUrl;
            video.addEventListener('loadedmetadata', () => {
              if (active) {
                setLoading(false);
                setPlaying(true);
                video.play().catch(() => setPlaying(false));
              }
            });
          }
        }
      } catch (err) {
        console.error("Player initialization failed:", err);
        if (active) setLoading(false);
      }
    };

    initPlayer();

    return () => {
      active = false;
      cleanUp();
    };
  }, [streamUrl, streamType, clearKeys]);

  const cleanUp = () => {
    if (shakaPlayerRef.current) {
      shakaPlayerRef.current.destroy();
      shakaPlayerRef.current = null;
    }
    if (hlsRef.current) {
      hlsRef.current.destroy();
      hlsRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.src = "";
      videoRef.current.load();
    }
  };

  const handlePlayPause = () => {
    const video = videoRef.current;
    if (!video) return;
    if (playing) {
      video.pause();
      setPlaying(false);
    } else {
      video.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
    }
  };

  const handleMuteToggle = () => {
    const video = videoRef.current;
    if (!video) return;
    video.muted = !muted;
    setMuted(!muted);
  };

  const handleFullscreen = () => {
    const video = videoRef.current;
    if (!video) return;
    if (video.requestFullscreen) video.requestFullscreen();
  };

  const copyUrl = () => {
    navigator.clipboard.writeText(streamUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleQualityChange = (q: string) => {
    setCurrentQuality(q);
    if (shakaPlayerRef.current) {
      const player = shakaPlayerRef.current;
      const tracks = player.getVariantTracks();
      if (q === 'Auto') {
        player.configure({ abr: { enabled: true } });
      } else {
        const height = parseInt(q);
        const selectedTrack = tracks.find((t: any) => t.height === height);
        if (selectedTrack) {
          player.configure({ abr: { enabled: false } });
          player.selectVariantTrack(selectedTrack, true);
        }
      }
    } else if (hlsRef.current) {
      const hls = hlsRef.current;
      if (q === 'Auto') {
        hls.currentLevel = -1;
      } else {
        const height = parseInt(q);
        const index = hls.levels.findIndex((l: any) => l.height === height);
        if (index !== -1) {
          hls.currentLevel = index;
        }
      }
    }
  };

  return (
    <div className="relative overflow-hidden rounded-2xl border border-white/5 bg-black">
      <div className="relative aspect-video w-full">
        {loading && (
          <div className="absolute inset-0 z-10 flex flex-col items-center justify-center bg-black/90 backdrop-blur-sm">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-white/10 border-t-red-500" />
            <span className="mt-4 text-xs font-medium text-zinc-500">Decrypting Edge Feeds...</span>
          </div>
        )}
        
        <video 
          ref={videoRef} 
          onClick={handlePlayPause}
          className="h-full w-full object-contain"
        />

        {/* Top Indicators Overlay */}
        <div className="absolute top-4 left-4 z-10 flex gap-2">
          <span className="inline-flex items-center gap-1 rounded-full bg-black/60 px-3 py-1 text-[10px] font-bold text-zinc-300 backdrop-blur-md">
            <ShieldCheck className="h-3.5 w-3.5 text-green-500" />
            {drmType}
          </span>
          {title && (
            <span className="inline-flex items-center rounded-full bg-black/60 px-3 py-1 text-[10px] font-bold text-zinc-300 backdrop-blur-md">
              {title}
            </span>
          )}
        </div>
      </div>

      {/* Control Bar */}
      <div className="flex flex-wrap items-center justify-between border-t border-white/5 bg-[#0e0e11] px-5 py-3 gap-3">
        <div className="flex items-center gap-3">
          <button 
            className="flex h-9 w-9 items-center justify-center rounded-lg hover:bg-white/5 text-zinc-400 hover:text-white transition"
            onClick={handlePlayPause}
          >
            {playing ? <Pause className="h-4.5 w-4.5 fill-current" /> : <Play className="h-4.5 w-4.5 fill-current" />}
          </button>

          <button 
            className="flex h-9 w-9 items-center justify-center rounded-lg hover:bg-white/5 text-zinc-400 hover:text-white transition"
            onClick={handleMuteToggle}
          >
            {muted ? <VolumeX className="h-4.5 w-4.5" /> : <Volume2 className="h-4.5 w-4.5" />}
          </button>
        </div>

        <div className="flex flex-1 max-w-md items-center justify-between rounded-lg bg-zinc-950 px-4 py-2 border border-white/5 font-mono text-[10px] text-zinc-500 overflow-x-auto gap-4">
          <span className="truncate">{streamUrl}</span>
          <button onClick={copyUrl} className="text-zinc-400 hover:text-red-500 transition-colors">
            {copied ? <Check className="h-3.5 w-3.5 text-green-500" /> : <Copy className="h-3.5 w-3.5" />}
          </button>
        </div>

        <div className="flex items-center gap-2">
          {qualities.length > 0 && (
            <div className="flex items-center gap-1">
              <label htmlFor="videoQualitySelect" className="flex h-9 w-9 items-center justify-center text-zinc-400">
                <Sliders className="h-4 w-4" />
              </label>
              <select 
                id="videoQualitySelect"
                value={currentQuality}
                onChange={(e) => handleQualityChange(e.target.value)}
                className="rounded-lg border border-white/5 bg-zinc-950 px-3 py-1.5 text-xs font-semibold text-white outline-none cursor-pointer"
              >
                <option value="Auto">Auto (ABR)</option>
                {qualities.map(q => (
                  <option key={q} value={q}>{q}</option>
                ))}
              </select>
            </div>
          )}

          <button 
            className="flex h-9 w-9 items-center justify-center rounded-lg hover:bg-white/5 text-zinc-400 hover:text-white transition"
            onClick={handleFullscreen}
          >
            <Maximize2 className="h-4.5 w-4.5" />
          </button>
        </div>
      </div>
    </div>
  );
}

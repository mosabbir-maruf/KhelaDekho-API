import React from 'react';
import { Settings, Sliders, Shield, Bell, Disc } from 'lucide-react';

export default function SettingsPage() {
  return (
    <div className="space-y-8 pb-12 max-w-2xl">
      <div className="flex items-center gap-3">
        <Settings className="h-6 w-6 text-zinc-400" />
        <h1 className="text-xl font-bold tracking-tight text-white md:text-2xl">Application Settings</h1>
      </div>

      <div className="space-y-6">
        {/* Stream presets */}
        <div className="rounded-2xl border border-white/5 bg-zinc-900/20 p-6 backdrop-blur-md space-y-4">
          <div className="flex items-center gap-3">
            <Sliders className="h-5 w-5 text-red-500" />
            <h2 className="text-sm font-semibold text-white">Streaming Quality Presets</h2>
          </div>
          <p className="text-xs text-zinc-500 leading-relaxed">
            Configure the default playback quality when launching streams. Lower qualities save network bandwidth.
          </p>
          <div className="flex flex-col gap-2">
            {[
              { label: 'Auto (Adaptive Bitrate)', value: 'auto', desc: 'Dynamically adapts to your network speed (Recommended)' },
              { label: '1080p Full HD', value: '1080', desc: 'Highest resolution, requires high speed connections' },
              { label: '720p HD', value: '720', desc: 'Balanced HD quality' },
              { label: '480p Standard', value: '480', desc: 'Data saver preset' }
            ].map((opt, i) => (
              <label 
                key={opt.value}
                className="flex items-start gap-3 rounded-xl border border-white/5 bg-zinc-950/40 p-4 cursor-pointer hover:bg-zinc-900/30 transition"
              >
                <input 
                  type="radio" 
                  name="qualityPreset" 
                  defaultChecked={i === 0} 
                  className="mt-1 accent-red-500"
                />
                <div>
                  <h4 className="text-xs font-semibold text-white">{opt.label}</h4>
                  <span className="block text-[10px] text-zinc-500 mt-1">{opt.desc}</span>
                </div>
              </label>
            ))}
          </div>
        </div>

        {/* Security / Cryptography */}
        <div className="rounded-2xl border border-white/5 bg-zinc-900/20 p-6 backdrop-blur-md space-y-4">
          <div className="flex items-center gap-3">
            <Shield className="h-5 w-5 text-red-500" />
            <h2 className="text-sm font-semibold text-white">Security & API Credentials</h2>
          </div>
          <p className="text-xs text-zinc-500 leading-relaxed">
            Requests are signed with dynamic client-side Web Crypto HMAC signatures. No private keys are stored on the client.
          </p>
          <div className="rounded-xl bg-zinc-950/60 p-4 border border-white/5 font-mono text-[10px] text-zinc-500">
            <div>Signature Algorithm: HMAC-SHA256</div>
            <div className="mt-1">Drift Protection Threshold: 60 Seconds</div>
          </div>
        </div>

        {/* Notifications */}
        <div className="rounded-2xl border border-white/5 bg-zinc-900/20 p-6 backdrop-blur-md space-y-4">
          <div className="flex items-center gap-3">
            <Bell className="h-5 w-5 text-red-500" />
            <h2 className="text-sm font-semibold text-white">Notification Preferences</h2>
          </div>
          <p className="text-xs text-zinc-500 leading-relaxed">
            Get notified when your favorite sports leagues or teams go live.
          </p>
          <div className="space-y-2.5">
            {[
              { label: 'Live Events', desc: 'Receive instant notifications when matches transition to live' },
              { label: 'Weekly Schedule', desc: 'Weekly match schedules and upcoming highlights digests' }
            ].map((pref) => (
              <label key={pref.label} className="flex items-center justify-between p-2 cursor-pointer">
                <div>
                  <h4 className="text-xs font-semibold text-white">{pref.label}</h4>
                  <span className="block text-[10px] text-zinc-500 mt-0.5">{pref.desc}</span>
                </div>
                <input 
                  type="checkbox" 
                  defaultChecked 
                  className="h-4 w-4 rounded border-zinc-800 bg-zinc-950 text-red-500 focus:ring-0 focus:ring-offset-0 accent-red-500"
                />
              </label>
            ))}
          </div>
        </div>

        {/* Platform Info */}
        <div className="flex items-center justify-between text-[10px] text-zinc-600 font-medium px-2">
          <span>KhelaDekho Web Client v1.0.0</span>
          <span className="flex items-center gap-1"><Disc className="h-3 w-3 text-green-500 animate-pulse" /> Edge Node Active</span>
        </div>
      </div>
    </div>
  );
}

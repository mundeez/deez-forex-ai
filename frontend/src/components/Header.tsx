"use client";

import { Activity } from "lucide-react";

export default function Header() {
  return (
    <header className="border-b border-slate-700 bg-forex-card">
      <div className="max-w-7xl mx-auto px-4 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Activity className="w-7 h-7 text-forex-accent" />
          <h1 className="text-xl font-bold tracking-tight">deez-forex-ai</h1>
        </div>
        <div className="flex items-center gap-4 text-sm text-slate-400">
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
            24/7 Live
          </span>
          <span>Paper Mode</span>
        </div>
      </div>
    </header>
  );
}

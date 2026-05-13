"use client";

import { Activity, Settings } from "lucide-react";
import Link from "next/link";

export default function Header() {
  return (
    <header className="border-b border-slate-700 bg-forex-card">
      <div className="max-w-7xl mx-auto px-4 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Activity className="w-7 h-7 text-forex-accent" />
          <Link href="/" className="text-xl font-bold tracking-tight hover:text-forex-accent transition">
            deez-forex-ai
          </Link>
        </div>
        <div className="flex items-center gap-4 text-sm text-slate-400">
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
            24/7 Live
          </span>
          <span>Paper Mode</span>
          <Link href="/settings" className="hover:text-white transition">
            <Settings className="w-5 h-5" />
          </Link>
        </div>
      </div>
    </header>
  );
}

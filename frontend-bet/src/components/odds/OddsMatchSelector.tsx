"use client";

import React from 'react';
import type { TrackedMatch } from '@/types/odds';

interface OddsMatchSelectorProps {
  matches: TrackedMatch[];
  selectedMatchId: string | null;
  onSelect: (matchId: string) => void;
  isLoading: boolean;
}

export default function OddsMatchSelector({
  matches,
  selectedMatchId,
  onSelect,
  isLoading,
}: OddsMatchSelectorProps) {
  if (isLoading) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {[1, 2, 3].map((i) => (
          <div
            key={i}
            className="animate-pulse bg-gray-100 dark:bg-slate-700/50 rounded-lg p-4 h-24"
          />
        ))}
      </div>
    );
  }

  if (!matches.length) {
    return (
      <div className="text-center py-10">
        <svg
          className="mx-auto h-14 w-14 text-gray-400 dark:text-gray-500 mb-3"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1.5}
            d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
          />
        </svg>
        <h3 className="text-lg font-semibold text-gray-700 dark:text-gray-200">
          No Tracked Matches
        </h3>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400 max-w-md mx-auto">
          Start tracking a match via the API to see its odds history here.
          Use <code className="text-xs bg-gray-100 dark:bg-slate-700 px-1.5 py-0.5 rounded">POST /odds/track</code> with a team or match ID.
        </p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
      {matches.map((m) => {
        const isSelected = selectedMatchId === m.match_id;
        const sport = m.meta.sport || 'football';
        const matchLabel =
          sport === 'tennis'
            ? `${m.meta.player1 || m.meta.home_team} vs ${m.meta.player2 || m.meta.away_team}`
            : `${m.meta.home_team} vs ${m.meta.away_team}`;

        const startTime = m.meta.start_time
          ? new Date(m.meta.start_time).toLocaleString([], {
              month: 'short',
              day: 'numeric',
              hour: '2-digit',
              minute: '2-digit',
            })
          : m.meta.start_time_raw || '—';

        return (
          <button
            key={m.match_id}
            onClick={() => onSelect(m.match_id)}
            className={`
              text-left p-4 rounded-lg border-2 transition-all duration-150
              ${isSelected
                ? 'border-sky-500 bg-sky-50 dark:bg-sky-900/20 shadow-md'
                : 'border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 hover:border-gray-300 dark:hover:border-slate-600 hover:shadow-sm'
              }
            `}
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p
                  className={`font-semibold text-sm truncate ${
                    isSelected
                      ? 'text-sky-700 dark:text-sky-300'
                      : 'text-gray-800 dark:text-gray-100'
                  }`}
                  title={matchLabel}
                >
                  {matchLabel}
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  {startTime}
                </p>
              </div>
              <div className="flex flex-col items-end gap-1 flex-shrink-0">
                <span
                  className={`text-[10px] font-medium px-2 py-0.5 rounded-full ${
                    m.job_active
                      ? 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400'
                      : m.is_live
                      ? 'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400'
                      : m.meta.status === 'completed'
                      ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400'
                      : 'bg-gray-100 dark:bg-slate-700 text-gray-500 dark:text-gray-400'
                  }`}
                >
                  {m.job_active ? 'Live' : m.meta.status === 'completed' ? 'Completed' : 'Stopped'}
                </span>
                <span className="text-[10px] text-gray-400 dark:text-gray-500 capitalize">
                  {sport}
                </span>
              </div>
            </div>
          </button>
        );
      })}
    </div>
  );
}

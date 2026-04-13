"use client";

import React, { useState } from 'react';
import { RefreshCw, TrendingUp } from 'lucide-react';
import OddsMatchSelector from '@/components/odds/OddsMatchSelector';
import OddsSummaryChart from '@/components/odds/OddsSummaryChart';
import { useTrackedMatches, useOddsSummary } from '@/hooks/useOddsSummary';

export default function OddsPage() {
  const [selectedMatchId, setSelectedMatchId] = useState<string | null>(null);

  const {
    matches,
    isLoading: matchesLoading,
    error: matchesError,
    refetch: refetchMatches,
  } = useTrackedMatches();

  const {
    data: oddsSummary,
    isLoading: summaryLoading,
    error: summaryError,
    refetch: refetchSummary,
  } = useOddsSummary(selectedMatchId);

  return (
    <div className="flex flex-col min-h-screen bg-gray-100 dark:bg-slate-900 font-sans">
      <main className="flex-grow container mx-auto px-4 py-8 md:py-12 max-w-6xl">
        {/* Header */}
        <header className="text-center mb-10">
          <h1 className="text-4xl sm:text-5xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-sky-500 via-blue-500 to-indigo-500 dark:from-sky-400 dark:via-blue-400 dark:to-indigo-400 pb-2">
            Odds Tracker
          </h1>
          <p className="text-lg text-gray-600 dark:text-gray-300 mt-3 max-w-2xl mx-auto">
            Monitor odds movement over time and compare with sharp bookmaker lines to find value.
          </p>
        </header>

        {/* Match selection */}
        <section className="mb-8">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-100 flex items-center gap-2">
              <TrendingUp className="h-5 w-5 text-sky-500" />
              Tracked Matches
            </h2>
            <button
              onClick={refetchMatches}
              disabled={matchesLoading}
              className="p-2 text-gray-500 dark:text-gray-400 hover:text-sky-500 dark:hover:text-sky-400 hover:bg-gray-100 dark:hover:bg-slate-800 rounded-lg transition-colors disabled:opacity-50"
              title="Refresh tracked matches"
            >
              <RefreshCw className={`h-4 w-4 ${matchesLoading ? 'animate-spin' : ''}`} />
            </button>
          </div>

          {matchesError && (
            <div className="mb-4 p-3 text-sm text-red-700 dark:text-red-300 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800/30 rounded-lg">
              {matchesError}
            </div>
          )}

          <OddsMatchSelector
            matches={matches}
            selectedMatchId={selectedMatchId}
            onSelect={setSelectedMatchId}
            isLoading={matchesLoading}
          />
        </section>

        {/* Odds chart section */}
        {selectedMatchId && (
          <section className="mt-8">
            <div className="flex items-center justify-between mb-5">
              <div>
                <h2 className="text-xl font-semibold text-gray-800 dark:text-gray-100">
                  Odds Summary
                </h2>
                {oddsSummary && (
                  <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                    {oddsSummary.match}
                    {oddsSummary.start_time && (
                      <span>
                        {' '}
                        &middot; Kickoff:{' '}
                        {new Date(oddsSummary.start_time).toLocaleString([], {
                          month: 'short',
                          day: 'numeric',
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                      </span>
                    )}
                    <span> &middot; {oddsSummary.total_snapshots} snapshots</span>
                  </p>
                )}
              </div>
              <button
                onClick={refetchSummary}
                disabled={summaryLoading}
                className="px-3 py-1.5 text-sm text-sky-600 dark:text-sky-400 hover:bg-sky-50 dark:hover:bg-sky-900/20 rounded-lg transition-colors border border-sky-200 dark:border-sky-800/30 disabled:opacity-50 flex items-center gap-1.5"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${summaryLoading ? 'animate-spin' : ''}`} />
                Refresh
              </button>
            </div>

            {summaryLoading && (
              <div className="flex items-center justify-center py-16">
                <div className="flex flex-col items-center gap-3">
                  <div className="h-8 w-8 border-3 border-sky-500 border-t-transparent rounded-full animate-spin" />
                  <p className="text-sm text-gray-500 dark:text-gray-400">Loading odds history...</p>
                </div>
              </div>
            )}

            {summaryError && (
              <div className="p-4 text-sm text-red-700 dark:text-red-300 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800/30 rounded-lg">
                {summaryError}
              </div>
            )}

            {oddsSummary && !summaryLoading && (
              <OddsSummaryChart summary={oddsSummary} />
            )}
          </section>
        )}

        {/* Empty state when no match selected */}
        {!selectedMatchId && matches.length > 0 && (
          <div className="text-center py-16 text-gray-500 dark:text-gray-400">
            <svg
              className="mx-auto h-16 w-16 mb-4 opacity-50"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M15 15l-2 5L9 9l11 4-5 2zm0 0l5 5M7.188 2.239l.777 2.897M5.136 7.965l-2.898-.777M13.95 4.05l-2.122 2.122m-5.657 5.656l-2.12 2.122"
              />
            </svg>
            <p className="text-lg font-medium">Select a match above</p>
            <p className="text-sm mt-1">to view its odds movement chart</p>
          </div>
        )}
      </main>
    </div>
  );
}

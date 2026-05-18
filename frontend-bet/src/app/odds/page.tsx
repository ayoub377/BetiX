"use client";

import React, { Suspense, useEffect, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { Activity, Loader2, Plus, RefreshCw, TrendingUp, Users } from 'lucide-react';

import MarketTabs from '@/components/odds/MarketTabs';
import OddsMatchSelector from '@/components/odds/OddsMatchSelector';
import OddsSummaryChart from '@/components/odds/OddsSummaryChart';
import { useAuth } from '@/contexts/AuthContext';
import { useTrackedMatches, useOddsSummary } from '@/hooks/useOddsSummary';

// useSearchParams() forces a CSR bailout in Next 15, so the component that
// reads the query string must be wrapped in <Suspense>. Default-export keeps
// the wrapper so the route entrypoint shape stays unchanged.
export default function OddsPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center min-h-[60vh]">
          <Loader2 className="h-8 w-8 animate-spin text-sky-500" />
        </div>
      }
    >
      <OddsPageContent />
    </Suspense>
  );
}

function OddsPageContent() {
  const searchParams = useSearchParams();
  const initialMatch = searchParams.get('match');
  const [selectedMatchId, setSelectedMatchId] = useState<string | null>(initialMatch);
  // Active market for the chart. Defaults to 1X2 — when the user
  // switches matches, we reset to 1X2 (every match has 1X2 by definition,
  // so this is always safe and never lands on a tab that doesn't exist).
  const [activeMarket, setActiveMarket] = useState<string>('1x2');
  useEffect(() => {
    setActiveMarket('1x2');
  }, [selectedMatchId]);
  const { customUserProfile } = useAuth();

  const {
    matches,
    isLoading: matchesLoading,
    error: matchesError,
    refetch: refetchMatches,
  } = useTrackedMatches();

  // If we landed here from /track with ?match=..., make sure that match is
  // visible in the selector even if useTrackedMatches hasn't loaded yet.
  useEffect(() => {
    if (initialMatch) setSelectedMatchId(initialMatch);
  }, [initialMatch]);

  // Active tracker count = matches with job_active === true.
  const activeTrackerCount = matches.filter((m) => m.job_active).length;
  const concurrentLimit = customUserProfile?.quotas.concurrent_tracker_limit ?? 1;
  const concurrentLabel = concurrentLimit === -1 ? '∞' : `${concurrentLimit}`;
  const dailyTrackLimit = customUserProfile?.quotas.daily_track_limit ?? 1;
  const dailyTrackLabel = dailyTrackLimit === -1 ? '∞' : `${dailyTrackLimit}`;
  const pollMinutes = customUserProfile
    ? Math.round(customUserProfile.quotas.track_poll_interval_seconds / 60)
    : 45;

  const {
    data: oddsSummary,
    isLoading: summaryLoading,
    error: summaryError,
    refetch: refetchSummary,
  } = useOddsSummary(selectedMatchId, activeMarket);

  // Tab strip needs the list of markets this match was configured for.
  // The summary response carries it; fall back to ['1x2'] until the first
  // fetch lands so we don't flash an empty strip.
  const configuredMarkets = oddsSummary?.configured_markets ?? ['1x2'];

  return (
    <div className="bg-gray-50 dark:bg-slate-950 font-sans">
      <div className="container mx-auto px-4 py-8 md:py-12 max-w-6xl">
        {/* Header */}
        <header className="mb-8">
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <h1 className="text-3xl sm:text-4xl font-bold text-gray-900 dark:text-gray-50">
                Odds Tracker
              </h1>
              <p className="text-base text-gray-600 dark:text-gray-300 mt-2 max-w-2xl">
                Monitor live odds movement and compare with sharp bookmaker lines to find value.
              </p>
            </div>
            <Link
              href="/track"
              className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-600 hover:to-indigo-700 text-white font-semibold shadow-md hover:shadow-lg transition-all duration-200"
            >
              <Plus className="h-4 w-4" />
              Track new match
            </Link>
          </div>

          {/* Quota pills */}
          {customUserProfile && (
            <div className="mt-6 flex flex-wrap items-center gap-2 text-sm">
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-white dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-gray-700 dark:text-gray-200">
                <Users className="h-3.5 w-3.5 text-sky-500" />
                Active <span className="font-semibold">{activeTrackerCount}/{concurrentLabel}</span>
              </span>
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-white dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-gray-700 dark:text-gray-200">
                <Activity className="h-3.5 w-3.5 text-emerald-500" />
                Daily limit <span className="font-semibold">{dailyTrackLabel}</span>
              </span>
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-white dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-gray-700 dark:text-gray-200">
                <RefreshCw className="h-3.5 w-3.5 text-amber-500" />
                Polling every <span className="font-semibold">{pollMinutes} min</span>
              </span>
            </div>
          )}
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

            {oddsSummary && (
              // Render the tab strip outside the summaryLoading gate so
              // switching markets feels instant — the chart below shows
              // a spinner while the new market loads, but the user keeps
              // their tabs visible the whole time.
              <div className="mb-4">
                <MarketTabs
                  configuredMarkets={configuredMarkets}
                  activeMarket={activeMarket}
                  onChange={setActiveMarket}
                />
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

        {/* Empty state when there are no matches at all */}
        {!matchesLoading && matches.length === 0 && !matchesError && (
          <div className="text-center py-16 bg-white dark:bg-slate-800 rounded-2xl border border-gray-200 dark:border-slate-700">
            <TrendingUp className="mx-auto h-12 w-12 text-gray-300 dark:text-gray-600 mb-4" />
            <h3 className="text-lg font-semibold text-gray-800 dark:text-gray-100 mb-1">No tracked matches yet</h3>
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-6 max-w-md mx-auto">
              Start tracking a match to see live odds movement and sharp bookmaker comparisons.
            </p>
            <Link
              href="/track"
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-600 hover:to-indigo-700 text-white font-semibold shadow-md transition-all"
            >
              <Plus className="h-4 w-4" />
              Track your first match
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}

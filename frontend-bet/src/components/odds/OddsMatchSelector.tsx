"use client";

import React, { useMemo, useState } from 'react';
import { ChevronDown, Trophy } from 'lucide-react';
import type { TrackedMatch } from '@/types/odds';
import {
  sportGroupKey,
  SPORT_GROUP_LABELS,
  leagueLabelFromSportKey,
  type SportGroupKey,
} from '@/types/odds';

interface OddsMatchSelectorProps {
  matches: TrackedMatch[];
  selectedMatchId: string | null;
  onSelect: (matchId: string) => void;
  isLoading: boolean;
}

// Order sports appear in the accordion. Anything not in this list falls through
// to alphabetical at the bottom.
const SPORT_ORDER: SportGroupKey[] = ['football', 'tennis', 'other'];

// Soccer ball / tennis ball icons rendered inline so we don't drag in new deps.
function SportIcon({ sport }: { sport: SportGroupKey }) {
  if (sport === 'tennis') {
    return (
      <svg
        viewBox="0 0 24 24"
        className="h-4 w-4 text-emerald-500"
        fill="currentColor"
        aria-hidden
      >
        <circle cx="12" cy="12" r="9" fill="#d9f99d" stroke="currentColor" strokeWidth="1.5" />
        <path
          d="M3.2 9.2c3.5 1 5.8 3.5 6.6 7"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
        <path
          d="M20.8 14.8c-3.5-1-5.8-3.5-6.6-7"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
      </svg>
    );
  }
  if (sport === 'football') {
    return (
      <svg
        viewBox="0 0 24 24"
        className="h-4 w-4 text-sky-500"
        fill="currentColor"
        aria-hidden
      >
        <circle cx="12" cy="12" r="9" fill="white" stroke="currentColor" strokeWidth="1.5" />
        <path d="M12 6.5l3 2.2-1.1 3.4h-3.8L9 8.7z" fill="currentColor" />
        <path
          d="M12 6.5V3M15 8.7l3.2-1M13.9 12.1l2 2.9M10.1 12.1l-2 2.9M9 8.7l-3.2-1"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.2"
          strokeLinecap="round"
        />
      </svg>
    );
  }
  return <Trophy className="h-4 w-4 text-gray-400" aria-hidden />;
}

interface GroupedMatches {
  sport: SportGroupKey;
  count: number;
  leagues: { leagueKey: string; leagueLabel: string; matches: TrackedMatch[] }[];
}

function groupMatches(matches: TrackedMatch[]): GroupedMatches[] {
  // sport → leagueKey → matches[]
  const buckets = new Map<SportGroupKey, Map<string, TrackedMatch[]>>();

  for (const m of matches) {
    const sport = sportGroupKey(m.meta.sport);
    const leagueKey = m.meta.odds_api_sport_key || `__unknown__:${sport}`;
    if (!buckets.has(sport)) buckets.set(sport, new Map());
    const inner = buckets.get(sport)!;
    if (!inner.has(leagueKey)) inner.set(leagueKey, []);
    inner.get(leagueKey)!.push(m);
  }

  const result: GroupedMatches[] = [];
  const allSports = new Set<SportGroupKey>(buckets.keys());

  const ordered: SportGroupKey[] = [
    ...SPORT_ORDER.filter((s) => allSports.has(s)),
    ...Array.from(allSports).filter((s) => !SPORT_ORDER.includes(s)),
  ];

  for (const sport of ordered) {
    const leagueMap = buckets.get(sport)!;
    const leagues = Array.from(leagueMap.entries())
      .map(([leagueKey, ms]) => ({
        leagueKey,
        leagueLabel: leagueKey.startsWith('__unknown__')
          ? 'Unmapped league'
          : leagueLabelFromSportKey(leagueKey),
        matches: ms.slice().sort((a, b) => {
          // Soonest kickoff first within a league.
          const at = a.meta.start_time ? Date.parse(a.meta.start_time) : Infinity;
          const bt = b.meta.start_time ? Date.parse(b.meta.start_time) : Infinity;
          return at - bt;
        }),
      }))
      .sort((a, b) => a.leagueLabel.localeCompare(b.leagueLabel));
    const count = leagues.reduce((sum, l) => sum + l.matches.length, 0);
    result.push({ sport, count, leagues });
  }

  return result;
}

function MatchCard({
  m,
  isSelected,
  onSelect,
}: {
  m: TrackedMatch;
  isSelected: boolean;
  onSelect: (id: string) => void;
}) {
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
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">{startTime}</p>
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
        </div>
      </div>
    </button>
  );
}

export default function OddsMatchSelector({
  matches,
  selectedMatchId,
  onSelect,
  isLoading,
}: OddsMatchSelectorProps) {
  const grouped = useMemo(() => groupMatches(matches), [matches]);

  // Open state for sport sections (default: all open). Leagues are always
  // visible inside their section — flat enough that double-collapse felt
  // fiddly, but each sport collapses as one block.
  const [openSports, setOpenSports] = useState<Record<string, boolean>>({});

  const isOpen = (sport: SportGroupKey) =>
    openSports[sport] === undefined ? true : openSports[sport];

  const toggle = (sport: SportGroupKey) =>
    setOpenSports((prev) => ({ ...prev, [sport]: !isOpen(sport) }));

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
    <div className="space-y-4">
      {grouped.map((group) => {
        const opened = isOpen(group.sport);
        return (
          <div
            key={group.sport}
            className="bg-white dark:bg-slate-800 rounded-xl border border-gray-200 dark:border-slate-700 overflow-hidden"
          >
            <button
              onClick={() => toggle(group.sport)}
              className="w-full flex items-center justify-between gap-3 px-4 py-3 text-left hover:bg-gray-50 dark:hover:bg-slate-700/40 transition-colors"
              aria-expanded={opened}
            >
              <div className="flex items-center gap-2.5">
                <SportIcon sport={group.sport} />
                <span className="text-base font-semibold text-gray-800 dark:text-gray-100">
                  {SPORT_GROUP_LABELS[group.sport]}
                </span>
                <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-gray-100 dark:bg-slate-700 text-gray-600 dark:text-gray-300">
                  {group.count}
                </span>
              </div>
              <ChevronDown
                className={`h-4 w-4 text-gray-500 dark:text-gray-400 transition-transform ${
                  opened ? 'rotate-180' : ''
                }`}
              />
            </button>

            {opened && (
              <div className="px-4 pb-4 pt-1 space-y-4 border-t border-gray-100 dark:border-slate-700/60">
                {group.leagues.map((league) => (
                  <div key={league.leagueKey}>
                    <div className="flex items-center gap-2 mb-2 mt-3">
                      <span className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
                        {league.leagueLabel}
                      </span>
                      <span className="text-[10px] text-gray-400 dark:text-gray-500">
                        · {league.matches.length}
                      </span>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                      {league.matches.map((m) => (
                        <MatchCard
                          key={m.match_id}
                          m={m}
                          isSelected={selectedMatchId === m.match_id}
                          onSelect={onSelect}
                        />
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

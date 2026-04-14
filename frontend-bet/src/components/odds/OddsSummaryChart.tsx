"use client";

import React, { useMemo, useState } from 'react';
import { Line } from 'react-chartjs-2';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler,
  TimeScale,
} from 'chart.js';
import 'chartjs-adapter-date-fns';
import type { OddsSummaryResponse, OutcomeKey } from '@/types/odds';
import {
  OUTCOME_LABELS,
  SHARP_BOOKMAKER_LABELS,
  FOOTBALL_OUTCOMES,
  TENNIS_OUTCOMES,
} from '@/types/odds';

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler,
  TimeScale
);

// Color palette — muted, professional tones
const OUTCOME_COLORS: Record<string, { main: string; bg: string }> = {
  home:    { main: 'rgb(34, 197, 94)',  bg: 'rgba(34, 197, 94, 0.08)' },   // green
  draw:    { main: 'rgb(59, 130, 246)', bg: 'rgba(59, 130, 246, 0.08)' },  // blue
  away:    { main: 'rgb(239, 68, 68)',  bg: 'rgba(239, 68, 68, 0.08)' },   // red
  player1: { main: 'rgb(34, 197, 94)',  bg: 'rgba(34, 197, 94, 0.08)' },   // green
  player2: { main: 'rgb(239, 68, 68)',  bg: 'rgba(239, 68, 68, 0.08)' },   // red
};

const SHARP_COLORS: Record<string, string> = {
  pinnacle: 'rgb(168, 85, 247)',       // purple
  betfair_ex_eu: 'rgb(245, 158, 11)', // amber
  betonlineag: 'rgb(6, 182, 212)',     // cyan
};

interface OddsSummaryChartProps {
  summary: OddsSummaryResponse;
}

export default function OddsSummaryChart({ summary }: OddsSummaryChartProps) {
  const { history, sport } = summary;
  const isTennis = sport === 'tennis';

  const outcomes: OutcomeKey[] = isTennis ? TENNIS_OUTCOMES : FOOTBALL_OUTCOMES;

  // Build dynamic labels for tennis using player names from match label
  const outcomeDisplayLabels = useMemo(() => {
    if (!isTennis) return OUTCOME_LABELS;
    // summary.match is "Player1 vs Player2"
    const parts = summary.match.split(' vs ');
    return {
      ...OUTCOME_LABELS,
      player1: parts[0]?.trim() || 'Player 1',
      player2: parts[1]?.trim() || 'Player 2',
    };
  }, [isTennis, summary.match]);

  const [activeOutcome, setActiveOutcome] = useState<OutcomeKey>(outcomes[0]);

  // Extract which sharp bookmakers appear in the data
  const availableSharps = useMemo(() => {
    const sharps = new Set<string>();
    for (const snap of history) {
      if (snap.sharp_odds) {
        Object.keys(snap.sharp_odds).forEach((k) => sharps.add(k));
      }
    }
    return Array.from(sharps);
  }, [history]);

  const [showSharpOdds, setShowSharpOdds] = useState(true);

  // Build chart datasets
  const chartData = useMemo(() => {
    const timestamps = history.map((s) => s.timestamp);
    const color = OUTCOME_COLORS[activeOutcome] || OUTCOME_COLORS.home;

    // Main bookmaker line
    const mainData = history.map((s) => {
      const val = s[activeOutcome as keyof typeof s];
      return typeof val === 'number' ? val : null;
    });
    const mainBookmaker = history[0]?.bookmaker || 'FlashScore';

    const datasets: any[] = [
      {
        label: `${outcomeDisplayLabels[activeOutcome]} — ${mainBookmaker}`,
        data: mainData,
        borderColor: color.main,
        backgroundColor: color.bg,
        borderWidth: 2.5,
        pointRadius: mainData.length > 40 ? 0 : 3,
        pointHoverRadius: 5,
        tension: 0.3,
        fill: true,
        order: 0,
      },
    ];

    // Sharp bookmaker lines (dashed) — only for football outcomes
    // Sharp odds use home/draw/away keys even when the main snapshot uses player1/player2
    if (showSharpOdds && !isTennis) {
      availableSharps.forEach((sharpKey) => {
        const sharpData = history.map(
          (s) => s.sharp_odds?.[sharpKey]?.[activeOutcome as 'home' | 'draw' | 'away'] ?? null
        );
        const hasData = sharpData.some((v) => v !== null);
        if (!hasData) return;

        datasets.push({
          label: `${outcomeDisplayLabels[activeOutcome]} — ${SHARP_BOOKMAKER_LABELS[sharpKey] || sharpKey}`,
          data: sharpData,
          borderColor: SHARP_COLORS[sharpKey] || 'rgb(156, 163, 175)',
          backgroundColor: 'transparent',
          borderWidth: 2,
          borderDash: [6, 3],
          pointRadius: sharpData.length > 40 ? 0 : 2,
          pointHoverRadius: 4,
          tension: 0.3,
          fill: false,
          order: 1,
        });
      });
    }

    return { labels: timestamps, datasets };
  }, [history, activeOutcome, showSharpOdds, availableSharps, isTennis, outcomeDisplayLabels]);

  const chartOptions = useMemo(
    () => ({
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        mode: 'index' as const,
        intersect: false,
      },
      plugins: {
        legend: {
          display: true,
          position: 'bottom' as const,
          labels: {
            usePointStyle: true,
            pointStyle: 'circle',
            padding: 16,
            font: { size: 12 },
            color: 'rgb(156, 163, 175)',
          },
        },
        tooltip: {
          backgroundColor: 'rgba(15, 23, 42, 0.95)',
          titleColor: 'rgb(226, 232, 240)',
          bodyColor: 'rgb(203, 213, 225)',
          borderColor: 'rgba(100, 116, 139, 0.3)',
          borderWidth: 1,
          padding: 12,
          cornerRadius: 8,
          titleFont: { size: 12, weight: 'bold' as const },
          bodyFont: { size: 12 },
          callbacks: {
            title: (items: any[]) => {
              if (!items.length) return '';
              const date = new Date(items[0].label);
              return date.toLocaleString([], {
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
              });
            },
            label: (item: any) => {
              return `  ${item.dataset.label}: ${item.parsed.y?.toFixed(2) ?? '—'}`;
            },
          },
        },
      },
      scales: {
        x: {
          type: 'time' as const,
          time: {
            tooltipFormat: 'PPpp',
            displayFormats: {
              minute: 'HH:mm',
              hour: 'HH:mm',
              day: 'MMM d',
            },
          },
          title: {
            display: true,
            text: 'Time',
            color: 'rgb(148, 163, 184)',
            font: { size: 12 },
          },
          ticks: {
            color: 'rgb(148, 163, 184)',
            maxTicksLimit: 10,
            font: { size: 11 },
          },
          grid: {
            color: 'rgba(148, 163, 184, 0.1)',
          },
        },
        y: {
          title: {
            display: true,
            text: 'Odds',
            color: 'rgb(148, 163, 184)',
            font: { size: 12 },
          },
          ticks: {
            color: 'rgb(148, 163, 184)',
            font: { size: 11 },
          },
          grid: {
            color: 'rgba(148, 163, 184, 0.1)',
          },
        },
      },
    }),
    []
  );

  // Compute summary stats for the active outcome
  const stats = useMemo(() => {
    const values = history
      .map((s) => {
        const val = s[activeOutcome as keyof typeof s];
        return typeof val === 'number' ? val : null;
      })
      .filter((v): v is number => v != null);
    if (!values.length) return null;
    const current = values[values.length - 1];
    const opening = values[0];
    const high = Math.max(...values);
    const low = Math.min(...values);
    const movement = current - opening;
    return { current, opening, high, low, movement };
  }, [history, activeOutcome]);

  if (!history.length) {
    return (
      <div className="text-center py-12 text-gray-500 dark:text-gray-400">
        No odds snapshots recorded yet for this match.
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {/* Outcome toggle tabs */}
      <div className="flex flex-wrap items-center gap-2">
        {outcomes.map((key) => {
          const isActive = activeOutcome === key;
          const color = OUTCOME_COLORS[key] || OUTCOME_COLORS.home;
          return (
            <button
              key={key}
              onClick={() => setActiveOutcome(key)}
              className={`
                px-4 py-2 rounded-lg text-sm font-medium transition-all duration-150
                ${isActive
                  ? 'text-white shadow-md scale-105'
                  : 'bg-gray-100 dark:bg-slate-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-slate-600'
                }
              `}
              style={isActive ? { backgroundColor: color.main } : undefined}
            >
              {outcomeDisplayLabels[key]}
            </button>
          );
        })}

        {availableSharps.length > 0 && !isTennis && (
          <label className="ml-auto flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={showSharpOdds}
              onChange={(e) => setShowSharpOdds(e.target.checked)}
              className="h-4 w-4 rounded border-gray-300 dark:border-slate-600 text-sky-500 focus:ring-sky-500 dark:bg-slate-700"
            />
            Show Sharp Odds
          </label>
        )}
      </div>

      {/* Stats row */}
      {stats && (
        <div className={`grid grid-cols-2 ${isTennis ? 'sm:grid-cols-4' : 'sm:grid-cols-4'} gap-3`}>
          <StatCard label="Current" value={stats.current.toFixed(2)} />
          <StatCard label="Opening" value={stats.opening.toFixed(2)} />
          <StatCard
            label="Movement"
            value={`${stats.movement >= 0 ? '+' : ''}${stats.movement.toFixed(2)}`}
            valueClass={
              stats.movement > 0
                ? 'text-green-500'
                : stats.movement < 0
                ? 'text-red-500'
                : 'text-gray-500 dark:text-gray-400'
            }
          />
          <StatCard label="Range" value={`${stats.low.toFixed(2)} — ${stats.high.toFixed(2)}`} />
        </div>
      )}

      {/* Chart */}
      <div className="bg-white dark:bg-slate-800 rounded-xl border border-gray-200 dark:border-slate-700 p-4 sm:p-6">
        <div className="h-[350px] sm:h-[420px]">
          <Line data={chartData} options={chartOptions} />
        </div>
      </div>

      {/* Sharp odds info callout — only for football */}
      {availableSharps.length > 0 && showSharpOdds && !isTennis && (
        <div className="flex items-start gap-3 p-4 bg-indigo-50 dark:bg-indigo-900/20 border border-indigo-100 dark:border-indigo-800/30 rounded-lg text-sm text-indigo-700 dark:text-indigo-300">
          <svg className="w-5 h-5 mt-0.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <p>
            <strong>Sharp bookmakers</strong> (Pinnacle, Betfair Exchange, BetOnline) set odds based on
            professional bettors. When their odds diverge from the main line, it can signal where the
            &ldquo;true&rdquo; probability lies — a key edge for value betting.
          </p>
        </div>
      )}
    </div>
  );
}

function StatCard({
  label,
  value,
  valueClass,
}: {
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div className="bg-gray-50 dark:bg-slate-700/50 rounded-lg p-3 text-center">
      <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">{label}</p>
      <p className={`text-lg font-semibold ${valueClass || 'text-gray-800 dark:text-gray-100'}`}>
        {value}
      </p>
    </div>
  );
}

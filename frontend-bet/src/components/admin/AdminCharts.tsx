"use client";

import React from 'react';
import { Bar, Doughnut } from 'react-chartjs-2';
import {
  ArcElement,
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Legend,
  LinearScale,
  Title,
  Tooltip,
} from 'chart.js';
import type { AdminDailyCall, AdminUsersSection } from '@/types/admin';

ChartJS.register(
  ArcElement,
  BarElement,
  CategoryScale,
  LinearScale,
  Title,
  Tooltip,
  Legend,
);

// Shared color palette so all the charts feel like one dashboard.
const COLORS = {
  normal: 'rgb(148, 163, 184)',  // slate-400
  premium: 'rgb(56, 189, 248)',  // sky-400
  admin: 'rgb(244, 114, 182)',   // pink-400
  bars: 'rgb(99, 102, 241)',     // indigo-500
  barsBg: 'rgba(99, 102, 241, 0.15)',
};

interface UserRoleDonutProps {
  users: AdminUsersSection;
}

export function UserRoleDonut({ users }: UserRoleDonutProps) {
  const { by_role } = users;
  const total = by_role.normal + by_role.premium + by_role.admin;

  const data = {
    labels: ['Free', 'Premium', 'Admin'],
    datasets: [
      {
        data: [by_role.normal, by_role.premium, by_role.admin],
        backgroundColor: [COLORS.normal, COLORS.premium, COLORS.admin],
        borderColor: 'rgba(255, 255, 255, 0.9)',
        borderWidth: 2,
      },
    ],
  };

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    cutout: '65%',
    plugins: {
      legend: {
        position: 'bottom' as const,
        labels: {
          padding: 12,
          usePointStyle: true,
          font: { size: 12 },
        },
      },
      tooltip: {
        callbacks: {
          label: (ctx: { label: string; raw: unknown }) => {
            const n = Number(ctx.raw) || 0;
            const pct = total ? Math.round((n / total) * 100) : 0;
            return `${ctx.label}: ${n} (${pct}%)`;
          },
        },
      },
    },
  };

  return (
    <div className="relative h-64">
      <Doughnut data={data} options={options} />
      <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none pb-12">
        <div className="text-3xl font-bold text-gray-900 dark:text-gray-50">{total}</div>
        <div className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide">
          Total users
        </div>
      </div>
    </div>
  );
}

interface OddsApiDailyChartProps {
  history: AdminDailyCall[];
}

export function OddsApiDailyChart({ history }: OddsApiDailyChartProps) {
  // Backend returns most-recent-first; chart reads left-to-right oldest-first.
  const ordered = [...history].reverse();

  const data = {
    labels: ordered.map((d) =>
      // "Mon 05" — compact for narrow cards
      new Date(d.date + 'T00:00:00Z').toLocaleDateString(undefined, {
        weekday: 'short',
        day: '2-digit',
      }),
    ),
    datasets: [
      {
        label: 'Odds API calls',
        data: ordered.map((d) => d.calls),
        backgroundColor: COLORS.barsBg,
        borderColor: COLORS.bars,
        borderWidth: 1.5,
        borderRadius: 4,
      },
    ],
  };

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          label: (ctx: { raw: unknown }) => `${ctx.raw} calls`,
        },
      },
    },
    scales: {
      x: {
        grid: { display: false },
        ticks: { font: { size: 10 } },
      },
      y: {
        beginAtZero: true,
        ticks: { precision: 0, font: { size: 10 } },
        grid: { color: 'rgba(148, 163, 184, 0.12)' },
      },
    },
  };

  return (
    <div className="h-56">
      <Bar data={data} options={options} />
    </div>
  );
}

interface SportBreakdownChartProps {
  bySport: Record<string, number>;
  activeBySport: Record<string, number>;
}

export function SportBreakdownChart({ bySport, activeBySport }: SportBreakdownChartProps) {
  // Union of sport keys so we don't drop a category that has only-active or
  // only-historical entries.
  const sports = Array.from(new Set([...Object.keys(bySport), ...Object.keys(activeBySport)]));
  const labels = sports.map((s) => s.charAt(0).toUpperCase() + s.slice(1));

  const data = {
    labels,
    datasets: [
      {
        label: 'Total (lifetime)',
        data: sports.map((s) => bySport[s] || 0),
        backgroundColor: 'rgba(148, 163, 184, 0.4)',
        borderColor: 'rgb(148, 163, 184)',
        borderWidth: 1.5,
        borderRadius: 4,
      },
      {
        label: 'Currently active',
        data: sports.map((s) => activeBySport[s] || 0),
        backgroundColor: 'rgba(56, 189, 248, 0.5)',
        borderColor: 'rgb(56, 189, 248)',
        borderWidth: 1.5,
        borderRadius: 4,
      },
    ],
  };

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        position: 'bottom' as const,
        labels: { padding: 12, usePointStyle: true, font: { size: 11 } },
      },
    },
    scales: {
      x: { grid: { display: false } },
      y: {
        beginAtZero: true,
        ticks: { precision: 0 },
        grid: { color: 'rgba(148, 163, 184, 0.12)' },
      },
    },
  };

  return (
    <div className="h-56">
      <Bar data={data} options={options} />
    </div>
  );
}

// Tab strip above the odds chart that switches which market the user is
// viewing. The list is filtered to the markets actually configured for
// the selected match (intersected with the catalogue from /odds/markets
// so we don't render a tab for an id the frontend doesn't recognise).

"use client";

import React from "react";

import { useMarkets } from "@/hooks/useMarkets";

interface MarketTabsProps {
  configuredMarkets: string[];
  activeMarket: string;
  onChange: (market: string) => void;
}

export default function MarketTabs({
  configuredMarkets,
  activeMarket,
  onChange,
}: MarketTabsProps) {
  const { markets: catalogue } = useMarkets();

  // Show tabs in catalogue order, but only for markets actually configured
  // on this match. Catalogue order is the intended display order (1X2 first,
  // then totals, then BTTS when we add it).
  const visible = catalogue.filter((m) => configuredMarkets.includes(m.id));

  // No point rendering a single-tab strip — it's noise.
  if (visible.length <= 1) return null;

  return (
    <div className="flex flex-wrap items-center gap-1 p-1 rounded-lg bg-gray-100 dark:bg-slate-700/50 border border-gray-200 dark:border-slate-700 w-fit">
      {visible.map((m) => {
        const isActive = m.id === activeMarket;
        return (
          <button
            key={m.id}
            type="button"
            onClick={() => onChange(m.id)}
            aria-pressed={isActive}
            className={`px-3 py-1.5 text-xs sm:text-sm font-medium rounded-md transition-all ${
              isActive
                ? "bg-white dark:bg-slate-900 text-gray-900 dark:text-gray-50 shadow-sm"
                : "text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100"
            }`}
          >
            {m.label}
          </button>
        );
      })}
    </div>
  );
}

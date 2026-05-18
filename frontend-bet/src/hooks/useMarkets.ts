// Fetches the supported-markets catalogue from /api/odds/markets.
//
// We cache the result module-side so navigating between /track and /odds
// (or rendering the catalogue in multiple components on one page) doesn't
// re-fetch. The catalogue is static per backend deploy — if a deploy adds
// a new market and the user is mid-session, they just see the new market
// after their next full page reload, which is acceptable.

"use client";

import { useEffect, useState } from "react";

import { apiClient } from "@/lib/apiClient";
import {
  FALLBACK_MARKETS,
  MarketsResponse,
  SupportedMarket,
} from "@/types/markets";

// Promise-level cache so concurrent callers share one in-flight request.
let cachedPromise: Promise<SupportedMarket[]> | null = null;

async function loadMarkets(): Promise<SupportedMarket[]> {
  if (!cachedPromise) {
    cachedPromise = apiClient
      .get<MarketsResponse>("/odds/markets")
      .then((res) => res.data.markets)
      .catch((err) => {
        // Bust the cache on failure so a transient network blip doesn't
        // permanently strand the user on the fallback list.
        cachedPromise = null;
        throw err;
      });
  }
  return cachedPromise;
}

export function useMarkets() {
  const [markets, setMarkets] = useState<SupportedMarket[]>(FALLBACK_MARKETS);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    loadMarkets()
      .then((catalogue) => {
        if (!cancelled) {
          setMarkets(catalogue);
          setError(null);
        }
      })
      .catch(() => {
        if (!cancelled) {
          // Keep the fallback list visible — the user can still pick 1X2
          // and submit, the backend will accept it.
          setError("Could not load markets catalogue. Showing defaults.");
        }
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { markets, isLoading, error };
}

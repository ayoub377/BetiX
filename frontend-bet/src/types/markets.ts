// Shape of the /api/odds/markets discovery endpoint.
// Mirrors app/models/markets.py — keep in sync.

export interface SupportedMarket {
  id: string; // canonical id, e.g. "1x2", "ou_2.5"
  label: string; // human label, e.g. "Over/Under 2.5"
  outcomes: string[]; // outcome keys, e.g. ["home","draw","away"] or ["over","under"]
  line: number | null; // 2.5 for OU 2.5; null for markets without a line
  is_default: boolean; // pre-selected in the track form
}

export interface MarketsResponse {
  markets: SupportedMarket[];
}

// Default fallback used when the registry endpoint can't be reached
// (e.g. cold load, offline). Keeps the track form usable even with no
// catalogue data — the backend will accept these ids regardless.
export const FALLBACK_MARKETS: SupportedMarket[] = [
  { id: "1x2", label: "1X2 Full Time", outcomes: ["home", "draw", "away"], line: null, is_default: true },
];

// Types matching the backend /odds/history/{match_id}/summary response

export interface SharpBookmakerOdds {
  home: number;
  draw: number;
  away: number;
}

export interface OddsSnapshot {
  timestamp: string;
  sport: string;
  // Market id ("1x2" | "ou_2.5" | …). Optional for backward-compat with
  // snapshots persisted before the multi-market column existed.
  market?: string;
  bookmaker: string;
  // 1X2 outcomes (populated when market === "1x2" or omitted for
  // pre-multi-market rows).
  home?: number;
  draw?: number;
  away?: number;
  // Tennis fields (optional)
  player1?: number;
  player2?: number;
  // Totals fields (populated when market starts with "ou_").
  over?: number;
  under?: number;
  line?: number;
  sharp_odds?: Record<string, SharpBookmakerOdds>;
  // Backend-resolved canonical odds for change indicators.
  // Pinnacle when available, otherwise the FlashScore bookmaker.
  primary_source: string | null;
  primary_odds: Record<string, number> | null;
  primary_change: Record<string, number> | null;
  primary_change_pct: Record<string, number> | null;
  seconds_since_last: number;
  display_interval: string;
}

export interface OddsSummaryResponse {
  sport: string;
  // Market id this response is filtered to.
  market?: string;
  // Markets this tracked match was configured for at /track time.
  // The frontend uses this to render the per-match tab strip.
  configured_markets?: string[];
  match: string;
  start_time: string | null;
  total_snapshots: number;
  history: OddsSnapshot[];
}

export interface TrackedMatchMeta {
  match_id: string;
  sport: string;
  home_team: string;
  away_team: string;
  player1?: string;
  player2?: string;
  start_time: string | null;
  start_time_raw?: string;
  status: string;
  tracked_since: string;
  odds_api_event_id?: string;
  odds_api_sport_key?: string;
  user_id?: string | null;
}

export interface TrackedMatch {
  match_id: string;
  meta: TrackedMatchMeta;
  job_active: boolean;
  is_live?: boolean;
}

export interface AllMatchesResponse {
  matches: TrackedMatch[];
  count: number;
}

export type FootballOutcomeKey = 'home' | 'draw' | 'away';
export type TennisOutcomeKey = 'player1' | 'player2';
export type OutcomeKey = FootballOutcomeKey | TennisOutcomeKey;

export const FOOTBALL_OUTCOMES: FootballOutcomeKey[] = ['home', 'draw', 'away'];
export const TENNIS_OUTCOMES: TennisOutcomeKey[] = ['player1', 'player2'];

export const OUTCOME_LABELS: Record<OutcomeKey, string> = {
  home: 'Home',
  draw: 'Draw',
  away: 'Away',
  player1: 'Player 1',
  player2: 'Player 2',
};

export const SHARP_BOOKMAKER_LABELS: Record<string, string> = {
  pinnacle: 'Pinnacle',
  betfair_ex_eu: 'Betfair Exchange',
  betonlineag: 'BetOnline',
};

// Display label for the resolved primary source (covers both sharp keys and
// FlashScore-scraped fallback names like "betclic" / "bet365").
export function formatPrimarySource(source: string | null | undefined): string {
  if (!source) return '—';
  if (SHARP_BOOKMAKER_LABELS[source]) return SHARP_BOOKMAKER_LABELS[source];
  return source.charAt(0).toUpperCase() + source.slice(1);
}

// ---------------------------------------------------------------------------
// Sport + league grouping helpers (used by the tracked-matches accordion).
//
// Backend stamps each tracker with the Odds API sport key (e.g.
// "soccer_spain_la_liga", "tennis_atp_miami_open") when it can resolve the
// fixture. The mappings below turn that key into a human-readable league
// label; anything missing falls back to a "title-cased" transform of the key.
// ---------------------------------------------------------------------------

export type SportGroupKey = 'football' | 'tennis' | 'other';

export function sportGroupKey(sport: string | null | undefined): SportGroupKey {
  if (sport === 'tennis') return 'tennis';
  if (sport === 'football' || sport === 'soccer') return 'football';
  return 'other';
}

export const SPORT_GROUP_LABELS: Record<SportGroupKey, string> = {
  football: 'Soccer',
  tennis: 'Tennis',
  other: 'Other',
};

const LEAGUE_LABELS: Record<string, string> = {
  // Soccer — domestic
  soccer_spain_la_liga: 'La Liga',
  soccer_epl: 'Premier League',
  soccer_england_efl_champ: 'Championship',
  soccer_italy_serie_a: 'Serie A',
  soccer_germany_bundesliga: 'Bundesliga',
  soccer_france_ligue_one: 'Ligue 1',
  soccer_netherlands_eredivisie: 'Eredivisie',
  soccer_portugal_primeira_liga: 'Primeira Liga',
  soccer_belgium_first_div: 'Belgian Pro League',
  soccer_turkey_super_league: 'Süper Lig',
  soccer_brazil_campeonato: 'Brasileirão',
  soccer_argentina_primera_division: 'Primera División',
  soccer_usa_mls: 'MLS',
  // Soccer — continental / international
  soccer_uefa_champs_league: 'UEFA Champions League',
  soccer_uefa_europa_league: 'UEFA Europa League',
  soccer_uefa_europa_conference_league: 'UEFA Conference League',
  soccer_uefa_nations_league: 'UEFA Nations League',
  soccer_fifa_world_cup: 'FIFA World Cup',
  soccer_uefa_european_championship: 'UEFA Euro',
  soccer_copa_libertadores: 'Copa Libertadores',
  // Tennis — Grand Slams
  tennis_atp_australian_open: 'ATP – Australian Open',
  tennis_atp_french_open: 'ATP – Roland-Garros',
  tennis_atp_wimbledon: 'ATP – Wimbledon',
  tennis_atp_us_open: 'ATP – US Open',
  tennis_wta_australian_open: 'WTA – Australian Open',
  tennis_wta_french_open: 'WTA – Roland-Garros',
  tennis_wta_wimbledon: 'WTA – Wimbledon',
  tennis_wta_us_open: 'WTA – US Open',
  // Tennis — ATP 1000 / 500
  tennis_atp_indian_wells: 'ATP – Indian Wells',
  tennis_atp_miami_open: 'ATP – Miami Open',
  tennis_atp_monte_carlo: 'ATP – Monte Carlo',
  tennis_atp_madrid_open: 'ATP – Madrid Open',
  tennis_atp_italian_open: 'ATP – Italian Open',
  tennis_atp_canadian_open: 'ATP – Canadian Open',
  tennis_atp_cincinnati_open: 'ATP – Cincinnati Open',
  tennis_atp_shanghai_masters: 'ATP – Shanghai Masters',
  tennis_atp_paris_masters: 'ATP – Paris Masters',
  // Tennis — WTA 1000 / 500
  tennis_wta_indian_wells: 'WTA – Indian Wells',
  tennis_wta_miami_open: 'WTA – Miami Open',
  tennis_wta_madrid_open: 'WTA – Madrid Open',
  tennis_wta_italian_open: 'WTA – Italian Open',
  tennis_wta_canadian_open: 'WTA – Canadian Open',
  tennis_wta_cincinnati_open: 'WTA – Cincinnati Open',
};

function titleCase(s: string): string {
  return s
    .replace(/[_\-]+/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function leagueLabelFromSportKey(sportKey: string | null | undefined): string {
  if (!sportKey) return 'Other matches';
  if (LEAGUE_LABELS[sportKey]) return LEAGUE_LABELS[sportKey];
  // Strip the leading "soccer_" / "tennis_" prefix for the fallback label so
  // we don't show the redundant sport name a second time inside the section.
  const stripped = sportKey.replace(/^(soccer|tennis|baseball|basketball|americanfootball|icehockey)_/, '');
  return titleCase(stripped);
}

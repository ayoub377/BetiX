// Types matching the backend /odds/history/{match_id}/summary response

export interface SharpBookmakerOdds {
  home: number;
  draw: number;
  away: number;
}

export interface OddsSnapshot {
  timestamp: string;
  sport: string;
  bookmaker: string;
  home: number;
  draw: number;
  away: number;
  // Tennis fields (optional)
  player1?: number;
  player2?: number;
  sharp_odds?: Record<string, SharpBookmakerOdds>;
  seconds_since_last: number;
  display_interval: string;
}

export interface OddsSummaryResponse {
  sport: string;
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

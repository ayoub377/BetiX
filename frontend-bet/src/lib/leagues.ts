// Curated catalogue of leagues and tournaments we surface in the /track
// competition picker. Keys match The Odds API sport keys exactly so the
// backend can pass them straight through to find_event() without aliasing.
//
// Source of truth: https://the-odds-api.com/sports-odds-data/sports-apis.html
// If you add a key here, verify it returns events for an active season
// before shipping — wrong keys aren't catastrophic (backend falls back to
// auto-detect), but they pollute the UI.

export interface LeagueOption {
  sport_key: string;
  label: string;
  group: string;
}

// ─── Football (soccer) ────────────────────────────────────────────────
// Grouped by region with the most-bet European leagues first.
export const FOOTBALL_LEAGUES: LeagueOption[] = [
  // Top 5 European leagues
  { sport_key: "soccer_epl", label: "Premier League — England", group: "Top European Leagues" },
  { sport_key: "soccer_spain_la_liga", label: "La Liga — Spain", group: "Top European Leagues" },
  { sport_key: "soccer_italy_serie_a", label: "Serie A — Italy", group: "Top European Leagues" },
  { sport_key: "soccer_germany_bundesliga", label: "Bundesliga — Germany", group: "Top European Leagues" },
  { sport_key: "soccer_france_ligue_one", label: "Ligue 1 — France", group: "Top European Leagues" },

  // European cup competitions
  { sport_key: "soccer_uefa_champs_league", label: "UEFA Champions League", group: "European Competitions" },
  { sport_key: "soccer_uefa_europa_league", label: "UEFA Europa League", group: "European Competitions" },
  { sport_key: "soccer_uefa_europa_conference_league", label: "UEFA Conference League", group: "European Competitions" },
  { sport_key: "soccer_uefa_nations_league", label: "UEFA Nations League", group: "European Competitions" },

  // Second-tier and other European
  { sport_key: "soccer_efl_champ", label: "Championship — England (2nd tier)", group: "Other European Leagues" },
  { sport_key: "soccer_spain_segunda_division", label: "La Liga 2 — Spain", group: "Other European Leagues" },
  { sport_key: "soccer_italy_serie_b", label: "Serie B — Italy", group: "Other European Leagues" },
  { sport_key: "soccer_germany_bundesliga2", label: "Bundesliga 2 — Germany", group: "Other European Leagues" },
  { sport_key: "soccer_france_ligue_two", label: "Ligue 2 — France", group: "Other European Leagues" },
  { sport_key: "soccer_portugal_primeira_liga", label: "Primeira Liga — Portugal", group: "Other European Leagues" },
  { sport_key: "soccer_netherlands_eredivisie", label: "Eredivisie — Netherlands", group: "Other European Leagues" },
  { sport_key: "soccer_belgium_first_div", label: "Pro League — Belgium", group: "Other European Leagues" },
  { sport_key: "soccer_turkey_super_league", label: "Süper Lig — Turkey", group: "Other European Leagues" },
  { sport_key: "soccer_scotland_premiership", label: "Premiership — Scotland", group: "Other European Leagues" },
  { sport_key: "soccer_greece_super_league", label: "Super League — Greece", group: "Other European Leagues" },

  // Domestic cups
  { sport_key: "soccer_fa_cup", label: "FA Cup — England", group: "Domestic Cups" },
  { sport_key: "soccer_efl_cup", label: "EFL Cup — England", group: "Domestic Cups" },

  // Americas
  { sport_key: "soccer_usa_mls", label: "MLS — USA & Canada", group: "Americas" },
  { sport_key: "soccer_mexico_ligamx", label: "Liga MX — Mexico", group: "Americas" },
  { sport_key: "soccer_brazil_campeonato", label: "Brasileirão — Brazil", group: "Americas" },
  { sport_key: "soccer_argentina_primera_division", label: "Liga Profesional — Argentina", group: "Americas" },
  { sport_key: "soccer_chile_campeonato", label: "Primera División — Chile", group: "Americas" },
  { sport_key: "soccer_conmebol_copa_libertadores", label: "Copa Libertadores — CONMEBOL", group: "Americas" },
  { sport_key: "soccer_conmebol_copa_sudamericana", label: "Copa Sudamericana — CONMEBOL", group: "Americas" },

  // Asia-Pacific
  { sport_key: "soccer_japan_j_league", label: "J1 League — Japan", group: "Asia-Pacific" },
  { sport_key: "soccer_korea_kleague1", label: "K League 1 — South Korea", group: "Asia-Pacific" },
  { sport_key: "soccer_australia_aleague", label: "A-League — Australia", group: "Asia-Pacific" },

  // International (active around tournaments)
  { sport_key: "soccer_fifa_world_cup", label: "FIFA World Cup", group: "International" },
  { sport_key: "soccer_fifa_club_world_cup", label: "FIFA Club World Cup", group: "International" },
  { sport_key: "soccer_uefa_european_championship", label: "UEFA European Championship", group: "International" },
  { sport_key: "soccer_africa_cup_of_nations", label: "Africa Cup of Nations", group: "International" },
];

// ─── Tennis ───────────────────────────────────────────────────────────
// Tennis sport keys are per-tournament and rotate through the calendar,
// so listing every event would surface a lot of inactive options. We
// surface only the Grand Slams + ATP Finals — these run yearly on fixed
// dates and dominate betting interest. For mid-season events leave the
// picker on auto-detect.
export const TENNIS_LEAGUES: LeagueOption[] = [
  { sport_key: "tennis_atp_aus_open", label: "Australian Open — ATP (men)", group: "Grand Slams — ATP" },
  { sport_key: "tennis_atp_french_open", label: "Roland-Garros — ATP (men)", group: "Grand Slams — ATP" },
  { sport_key: "tennis_atp_wimbledon", label: "Wimbledon — ATP (men)", group: "Grand Slams — ATP" },
  { sport_key: "tennis_atp_us_open", label: "US Open — ATP (men)", group: "Grand Slams — ATP" },

  { sport_key: "tennis_wta_aus_open", label: "Australian Open — WTA (women)", group: "Grand Slams — WTA" },
  { sport_key: "tennis_wta_french_open", label: "Roland-Garros — WTA (women)", group: "Grand Slams — WTA" },
  { sport_key: "tennis_wta_wimbledon", label: "Wimbledon — WTA (women)", group: "Grand Slams — WTA" },
  { sport_key: "tennis_wta_us_open", label: "US Open — WTA (women)", group: "Grand Slams — WTA" },

  { sport_key: "tennis_atp_finals", label: "ATP Finals (men)", group: "Year-end Championships" },
  { sport_key: "tennis_wta_finals", label: "WTA Finals (women)", group: "Year-end Championships" },
];

/**
 * Return the league list for a sport, grouped for an <optgroup>-rendered
 * native <select>. Insertion order of groups is preserved.
 */
export function groupedLeaguesFor(sport: "football" | "tennis"): Array<{
  group: string;
  options: LeagueOption[];
}> {
  const source = sport === "football" ? FOOTBALL_LEAGUES : TENNIS_LEAGUES;
  const order: string[] = [];
  const buckets = new Map<string, LeagueOption[]>();
  for (const opt of source) {
    if (!buckets.has(opt.group)) {
      buckets.set(opt.group, []);
      order.push(opt.group);
    }
    buckets.get(opt.group)!.push(opt);
  }
  return order.map((group) => ({ group, options: buckets.get(group)! }));
}

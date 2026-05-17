// Mirrors the FastAPI response/request schemas in
// `app/api/endpoints/telegram.py`. Keep these in sync — if you change a
// field name on the backend, change it here too.

export interface TelegramStatus {
  linked: boolean;
  alerts_enabled: boolean;
  threshold_pct: number | null;
  chat_id_suffix: string | null;
}

export interface TelegramLinkResponse {
  deep_link: string;
  expires_in_seconds: number;
}

export interface TelegramPreferencesUpdate {
  threshold_pct?: number;
  enabled?: boolean;
}

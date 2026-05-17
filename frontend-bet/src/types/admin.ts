// Types matching the backend GET /admin/info response.
//
// Server source of truth: transfermarkt-api/app/api/endpoints/admin_info.py

export interface AdminUsersSection {
  total: number;
  by_role: {
    normal: number;
    premium: number;
    admin: number;
  };
  // Subset that currently pays us (active + on_trial). A cancelled premium
  // subscriber still has role=premium until their period ends, so this is
  // not the same as by_role.premium.
  paying: number;
  signups_last_7d: number;
  signups_last_30d: number;
}

export interface AdminTopUser {
  user_id: string;
  email: string | null;
  role: 'normal' | 'premium' | 'admin' | 'unknown';
  active_trackers: number;
}

export interface AdminTrackingSection {
  total_matches_ever: number;
  active_trackers: number;
  by_status: Record<string, number>;
  by_sport: Record<string, number>;
  active_by_sport: Record<string, number>;
  top_active_users: AdminTopUser[];
  redis_index_size: number | null;
  scheduler_job_count: number | null;
  pending_match_results: number;
  total_snapshots: number;
  // Cost driver: 86400 / poll_interval_seconds summed across active trackers.
  projected_odds_api_calls_per_day: number;
}

export interface AdminDailyCall {
  date: string;
  calls: number;
}

export interface AdminOddsApiSection {
  configured: boolean;
  calls_today: number | null;
  calls_total: number | null;
  daily_history: AdminDailyCall[];
}

export interface AdminRedisSection {
  daily_track_counters_active: number | null;
}

export interface AdminInfoResponse {
  generated_at: string;
  users: AdminUsersSection;
  tracking: AdminTrackingSection;
  odds_api: AdminOddsApiSection;
  redis: AdminRedisSection;
}

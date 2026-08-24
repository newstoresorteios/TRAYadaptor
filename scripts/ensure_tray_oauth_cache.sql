-- Shared Tray OAuth tokens for TrayAdaptor (multi-instance / cold start).
CREATE TABLE IF NOT EXISTS public.tray_oauth_cache (
    store_id text PRIMARY KEY,
    access_token text NOT NULL DEFAULT '',
    refresh_token text NOT NULL,
    access_expires_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now()
);

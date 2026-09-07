-- Shared Tray OAuth tokens for TrayAdaptor (multi-instance / cold start).
CREATE TABLE IF NOT EXISTS public.tray_oauth_cache (
    store_id text PRIMARY KEY,
    access_token text NOT NULL DEFAULT '',
    refresh_token text NOT NULL,
    access_expires_at timestamptz,
    refresh_expires_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.tray_oauth_cache
    ADD COLUMN IF NOT EXISTS refresh_expires_at timestamptz;

CREATE TABLE IF NOT EXISTS public.tray_webhook_events (
    id bigserial PRIMARY KEY,
    seller_id text NOT NULL,
    scope_name text NOT NULL,
    scope_id text NOT NULL,
    act text NOT NULL,
    app_code text,
    received_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS tray_webhook_events_received_at_idx
    ON public.tray_webhook_events (received_at DESC);

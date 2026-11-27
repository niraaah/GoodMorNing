-- Social login only. No local usernames or password hashes.
CREATE TABLE IF NOT EXISTS account_profiles(
 user_id uuid PRIMARY KEY REFERENCES app_users(id),
 owner text NOT NULL UNIQUE REFERENCES app_owner_bindings(owner),
 display_name text NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS account_sessions(
 token_hash text PRIMARY KEY, user_id uuid NOT NULL REFERENCES account_profiles(user_id),
 created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL,
 last_seen timestamptz NOT NULL DEFAULT now(), revoked_at timestamptz);
CREATE INDEX IF NOT EXISTS account_sessions_user ON account_sessions(user_id);
CREATE TABLE IF NOT EXISTS oauth_attempts(
 state_hash text PRIMARY KEY, verifier_hash text NOT NULL, client_hash text NOT NULL,
 config_hash text NOT NULL, origin text NOT NULL, guest_owner text,
 created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL,
 consumed_at timestamptz);
CREATE INDEX IF NOT EXISTS oauth_attempts_client ON oauth_attempts(client_hash,created_at);

ALTER TABLE account_profiles ADD COLUMN IF NOT EXISTS avatar bytea;
ALTER TABLE account_profiles ADD COLUMN IF NOT EXISTS profile_ready boolean NOT NULL DEFAULT false;
ALTER TABLE account_profiles ADD COLUMN IF NOT EXISTS terms_version text;
ALTER TABLE account_profiles ADD COLUMN IF NOT EXISTS privacy_version text;
ALTER TABLE account_profiles ADD COLUMN IF NOT EXISTS agreed_at timestamptz;
ALTER TABLE account_profiles ADD COLUMN IF NOT EXISTS deleting boolean NOT NULL DEFAULT false;
ALTER TABLE account_profiles ADD COLUMN IF NOT EXISTS deletion_requested_at timestamptz;
ALTER TABLE oauth_attempts ADD COLUMN IF NOT EXISTS policy_version text;
CREATE TABLE IF NOT EXISTS retired_guest_owners(
 owner_hash text PRIMARY KEY, expires_at timestamptz NOT NULL);

INSERT INTO schema_migrations VALUES('20261127_profiles_erasure_v1',now()) ON CONFLICT DO NOTHING;

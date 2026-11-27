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

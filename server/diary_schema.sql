-- Additive account/diary structure. notebook_pages remains the compatible source.
CREATE TABLE IF NOT EXISTS app_users(
 id uuid PRIMARY KEY, kind text NOT NULL CHECK(kind IN ('local','guest','member','legacy')),
 created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS app_owner_bindings(
 owner text PRIMARY KEY, user_id uuid NOT NULL REFERENCES app_users(id),
 created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS app_owner_user ON app_owner_bindings(user_id);
-- Provider credentials and sessions belong to the future login implementation.
CREATE TABLE IF NOT EXISTS auth_identities(
 provider text NOT NULL, subject text NOT NULL, user_id uuid NOT NULL REFERENCES app_users(id),
 created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(provider,subject));
CREATE INDEX IF NOT EXISTS auth_identity_user ON auth_identities(user_id);
CREATE TABLE IF NOT EXISTS user_notebooks(
 id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES app_users(id),
 notebook_key text NOT NULL DEFAULT 'default', title text NOT NULL DEFAULT '내 다이어리',
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(user_id,notebook_key));
CREATE TABLE IF NOT EXISTS diary_pages(
 id uuid PRIMARY KEY, notebook_id uuid NOT NULL REFERENCES user_notebooks(id),
 legacy_owner text NOT NULL REFERENCES app_owner_bindings(owner), page_key text NOT NULL,
 paper_style jsonb NOT NULL DEFAULT '{}', source_hash text NOT NULL, updated_at timestamptz NOT NULL,
 UNIQUE(legacy_owner,page_key),
 FOREIGN KEY(legacy_owner,page_key) REFERENCES notebook_pages(owner,page_key) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS diary_pages_notebook ON diary_pages(notebook_id,page_key);
CREATE TABLE IF NOT EXISTS diary_page_items(
 id uuid PRIMARY KEY, page_id uuid NOT NULL REFERENCES diary_pages(id) ON DELETE CASCADE,
 kind text NOT NULL CHECK(kind IN ('photo','sticker')), slot integer NOT NULL CHECK(slot>=0),
 layer_group smallint GENERATED ALWAYS AS (CASE WHEN kind='photo' THEN 0 ELSE 1 END) STORED,
 stack_order integer NOT NULL CHECK(stack_order>=0),
 asset_id text REFERENCES assets(id), file_id text REFERENCES notebook_files(id),
 x_percent double precision, y_percent double precision, size_percent double precision,
 rotation double precision, caption text, removed boolean NOT NULL DEFAULT false,
 properties jsonb NOT NULL, UNIQUE(page_id,kind,slot));
CREATE INDEX IF NOT EXISTS diary_items_stack ON diary_page_items(page_id,layer_group,stack_order);

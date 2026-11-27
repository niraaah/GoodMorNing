"""Offline provisioning. Runtime services do not import this module."""
import secrets
from psycopg import sql
from . import db

API_TABLES = ('ownership','assets','jobs','diaries','notebook_pages','notebook_files','asset_trash',
    'goods_searches','asset_product_links','app_users','app_owner_bindings','auth_identities',
    'user_notebooks','diary_pages','diary_page_items','account_profiles','account_sessions','oauth_attempts')
CATALOG_TABLES = ('catalog_products','catalog_variants','catalog_malls','catalog_offers',
    'catalog_offer_history','catalog_collect_jobs','catalog_raw_listings','catalog_query_cache',
    'catalog_query_offers','catalog_images','catalog_embeddings')
SEARCH_WRITE_TABLES = tuple(t for t in CATALOG_TABLES if t not in ('catalog_products','catalog_variants'))
PRIVATE_AUTH = ('auth_identities','account_profiles','account_sessions','oauth_attempts')
RLS_TABLES = ('ownership','assets','jobs','diaries','notebook_pages','notebook_files','asset_trash',
              'goods_searches','asset_product_links','user_notebooks','diary_pages','diary_page_items')


def credentials():
    values = {}
    db.data_dir().mkdir(parents=True, exist_ok=True)
    for service in db.ROLES:
        path = db.data_dir()/('postgres-'+service+'.key')
        if not path.exists():
            path.write_text(secrets.token_urlsafe(32), encoding='utf-8')
        values[service] = path.read_text(encoding='utf-8').strip()
    key = db.data_dir()/'search-service.key'
    if not key.exists():
        key.write_text(secrets.token_urlsafe(32), encoding='utf-8')
    return values


def identifiers(names):
    return sql.SQL(',').join(map(sql.Identifier, names))


def provision(con, passwords):
    """Only additive data change: bind formerly implicit local ownership explicitly."""
    con.execute('CREATE EXTENSION IF NOT EXISTS vector')
    for schema in db.SCHEMAS:
        con.execute(schema.read_text(encoding='utf-8'))
    for service, name in db.ROLES.items():
        role = sql.Identifier(name)
        if not con.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (name,)).fetchone():
            con.execute(sql.SQL('CREATE ROLE {}').format(role))
        con.execute(sql.SQL('ALTER ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT PASSWORD {}')
                    .format(role, sql.Literal(passwords[service])))
        parents = con.execute('SELECT r.rolname FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.roleid JOIN pg_roles u ON u.oid=m.member WHERE u.rolname=%s', (name,)).fetchall()
        for parent in parents:
            con.execute(sql.SQL('REVOKE {} FROM {}').format(sql.Identifier(parent['rolname']), role))
        con.execute(sql.SQL("ALTER ROLE {} SET statement_timeout='30s'").format(role))
        con.execute(sql.SQL("ALTER ROLE {} SET idle_in_transaction_session_timeout='60s'").format(role))
        con.execute(sql.SQL('ALTER ROLE {} SET search_path=pg_catalog,public').format(role))
        con.execute(sql.SQL('REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}; REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {}; REVOKE ALL ON SCHEMA public FROM {}').format(role, role, role))
    database = sql.Identifier(con.info.dbname)
    con.execute(sql.SQL('REVOKE ALL ON DATABASE {} FROM PUBLIC').format(database))
    con.execute('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
    con.execute('REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC')
    con.execute('REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC')
    for name in db.ROLES.values():
        con.execute(sql.SQL('REVOKE ALL ON DATABASE {} FROM {}; GRANT CONNECT ON DATABASE {} TO {}; GRANT USAGE ON SCHEMA public TO {}')
                    .format(database,sql.Identifier(name),database,sql.Identifier(name),sql.Identifier(name)))
    api, search, reader = (sql.Identifier(db.ROLES[s]) for s in ('api','search','reader'))
    con.execute(sql.SQL('GRANT SELECT,INSERT,UPDATE,DELETE ON {} TO {}').format(identifiers(API_TABLES),api))
    con.execute(sql.SQL('GRANT SELECT ON {} TO {},{}').format(identifiers((*CATALOG_TABLES,'schema_migrations')),api,search))
    con.execute(sql.SQL('GRANT INSERT,UPDATE ON {} TO {}').format(identifiers(SEARCH_WRITE_TABLES),search))
    con.execute(sql.SQL('GRANT USAGE ON SEQUENCE catalog_offer_history_id_seq,catalog_raw_listings_id_seq TO {}').format(search))
    visible = tuple(t for t in (*API_TABLES,*CATALOG_TABLES,'schema_migrations') if t not in PRIVATE_AUTH)
    con.execute(sql.SQL('GRANT SELECT ON {} TO {}').format(identifiers(visible),reader))
    for table, kind in (('assets','asset'),('jobs','job'),('diaries','diary')):
        con.execute(sql.SQL("INSERT INTO ownership(kind,ident,owner) SELECT %s,id,'private' FROM {} ON CONFLICT DO NOTHING").format(sql.Identifier(table)), (kind,))
    own = "owner=current_setting('goodmorning.owner',true)"
    conditions = {table:own for table in ('ownership','notebook_pages','notebook_files','asset_trash','goods_searches','asset_product_links')}
    conditions['diary_pages'] = "legacy_owner=current_setting('goodmorning.owner',true)"
    conditions['user_notebooks'] = "EXISTS(SELECT 1 FROM app_owner_bindings b WHERE b.user_id=user_notebooks.user_id AND b.owner=current_setting('goodmorning.owner',true))"
    conditions['diary_page_items'] = 'EXISTS(SELECT 1 FROM diary_pages p WHERE p.id=diary_page_items.page_id)'
    for table, kind in (('assets','asset'),('jobs','job'),('diaries','diary')):
        conditions[table] = f"EXISTS(SELECT 1 FROM ownership o WHERE o.kind='{kind}' AND o.ident={table}.id)"
    for table, condition in conditions.items():
        ident = sql.Identifier(table)
        con.execute(sql.SQL('ALTER TABLE {} ENABLE ROW LEVEL SECURITY; ALTER TABLE {} FORCE ROW LEVEL SECURITY').format(ident,ident))
        for policy in ('gm_owner','gm_reader','gm_samples'):
            con.execute(sql.SQL('DROP POLICY IF EXISTS {} ON {}').format(sql.Identifier(policy),ident))
        con.execute(sql.SQL('CREATE POLICY gm_owner ON {} TO {} USING ({}) WITH CHECK ({})').format(ident,api,sql.SQL(condition),sql.SQL(condition)))
        con.execute(sql.SQL('CREATE POLICY gm_reader ON {} FOR SELECT TO {} USING (true)').format(ident,reader))
    con.execute(sql.SQL("CREATE POLICY gm_samples ON assets FOR SELECT TO {} USING (id IN ('pochita','2026_11_24_08_15','2026_11_24_08_16'))").format(api))
    con.execute('''CREATE OR REPLACE FUNCTION public.gm_recover_jobs() RETURNS void
        LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
        UPDATE public.jobs SET state='failed',message='서버가 재시작되어 중단됐어요. 다시 시도해 주세요.' WHERE state IN ('queued','running');
        UPDATE public.goods_searches SET state='failed',body='{"message":"서버가 재시작됐어요. 다시 검색해 주세요."}'::jsonb WHERE state='running';
        DELETE FROM public.goods_searches WHERE created<now()-interval '1 day';
        $$''')
    con.execute('REVOKE ALL ON FUNCTION public.gm_recover_jobs() FROM PUBLIC')
    con.execute(sql.SQL('GRANT EXECUTE ON FUNCTION public.gm_recover_jobs() TO {}').format(api))
    con.execute('INSERT INTO schema_migrations VALUES(%s,now()) ON CONFLICT DO NOTHING', (db.SECURITY_VERSION,))


def initialize():
    with db.admin_connection() as con:
        provision(con, credentials())

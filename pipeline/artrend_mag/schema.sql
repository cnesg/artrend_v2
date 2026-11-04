-- ARTREND magazine normalized store. Schema version is recorded in meta.
-- Conventions:
--   * NULL means "not observed / unknown"; it is never replaced by 0.
--   * Dates are ISO strings; *_precision in (day, month, year, unknown).
--   * Deterministic IDs (see artrend_mag/ids.py) make re-collection idempotent.
--   * Every displayed fact must trace to evidence(evidence_id).
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS region_map (
  country_code TEXT PRIMARY KEY,          -- ISO 3166-1 alpha-2
  country_name TEXT NOT NULL,
  m49_region TEXT NOT NULL,               -- UN M49 region (Americas, Europe, Asia, Africa, Oceania)
  edition_region TEXT NOT NULL CHECK (edition_region IN ('KR','JP','AMERICAS','EUROPE','OTHER')),
  version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
  source_id TEXT PRIMARY KEY,
  blueprint_data_id TEXT,                 -- D01..D71 (comma separated when several)
  blueprint_org_id TEXT,                  -- O01..O36 when applicable
  name TEXT NOT NULL,
  owner_group TEXT,                       -- parent organisation; used for independence checks
  source_kind TEXT NOT NULL,              -- museum, gallery, biennial, fair, award, residency, media, identifier, api, report, legacy_local
  region_scope TEXT,                      -- KR, JP, AMERICAS, EUROPE, OTHER, GLOBAL
  country_codes TEXT,                     -- where the source's events happen (comma separated)
  access_method TEXT NOT NULL,            -- download, api, rss, html, pdf, local
  base_url TEXT,
  entry_url TEXT,
  terms_url TEXT,
  text_storage_policy TEXT NOT NULL DEFAULT 'metadata_only',  -- metadata_only, short_excerpt, raw_internal
  priority TEXT,
  -- separate status axes (never merged into one "usable" flag)
  st_local_file TEXT DEFAULT 'unknown',
  st_official_doc TEXT DEFAULT 'unknown',
  st_live_response TEXT DEFAULT 'unknown',
  st_fields_extracted TEXT DEFAULT 'unknown',
  st_history TEXT DEFAULT 'unknown',
  st_incremental TEXT DEFAULT 'unknown',
  st_collection_terms TEXT DEFAULT 'unknown',
  st_image_terms TEXT DEFAULT 'unknown',
  robots_status TEXT DEFAULT 'unknown',
  operational_state TEXT DEFAULT 'not_attempted', -- active, partial, blocked_credentials, blocked_permission, blocked_access, error, not_attempted, local_only
  notes TEXT,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS entities (
  entity_id TEXT PRIMARY KEY,
  entity_type TEXT NOT NULL,              -- person, group, institution, gallery, foundation, fair, biennial, media, program, unknown
  canonical_name TEXT NOT NULL,
  name_lang TEXT,
  id_namespace TEXT NOT NULL,             -- wikidata, aic, moma, apj, or src:<source_id> for source-local IDs
  id_value TEXT NOT NULL,
  parent_entity_id TEXT REFERENCES entities(entity_id),
  nationality_text TEXT,                  -- filter only; never used for edition region
  birth_year INTEGER,
  death_year INTEGER,
  official_url TEXT,
  verification_status TEXT NOT NULL DEFAULT 'source_asserted', -- source_asserted, confirmed, candidate
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  UNIQUE (id_namespace, id_value)
);

CREATE TABLE IF NOT EXISTS aliases (
  entity_id TEXT NOT NULL REFERENCES entities(entity_id),
  name TEXT NOT NULL,
  lang TEXT,
  namespace TEXT NOT NULL,                -- name, wikidata, ulan, apj, aic, moma, ...
  external_id TEXT NOT NULL DEFAULT '',
  source_id TEXT REFERENCES sources(source_id),
  evidence_id TEXT REFERENCES evidence(evidence_id),
  match_status TEXT NOT NULL DEFAULT 'source_asserted',
  PRIMARY KEY (entity_id, namespace, external_id, name)
);

-- Cross-source identity links. Candidates are never auto-merged.
CREATE TABLE IF NOT EXISTS entity_links (
  entity_id_a TEXT NOT NULL REFERENCES entities(entity_id),
  entity_id_b TEXT NOT NULL REFERENCES entities(entity_id),
  link_type TEXT NOT NULL DEFAULT 'same_as',
  status TEXT NOT NULL,                   -- candidate, confirmed, rejected
  method TEXT NOT NULL,                   -- shared_external_id, exact_normalized_name, manual
  evidence TEXT,
  created_at TEXT NOT NULL,
  reversed_at TEXT,
  PRIMARY KEY (entity_id_a, entity_id_b, link_type)
);

CREATE TABLE IF NOT EXISTS venues (
  venue_id TEXT PRIMARY KEY,
  owner_entity_id TEXT REFERENCES entities(entity_id),
  parent_venue_id TEXT REFERENCES venues(venue_id),
  name TEXT NOT NULL,
  city TEXT,
  country_code TEXT REFERENCES region_map(country_code),
  edition_region TEXT,
  source_id TEXT REFERENCES sources(source_id),
  valid_from TEXT,
  valid_to TEXT
);

CREATE TABLE IF NOT EXISTS events (
  event_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(source_id),
  source_event_key TEXT NOT NULL,
  event_type TEXT NOT NULL,               -- exhibition, biennial_edition, award, residency, open_call_selection, fair_edition, fair_presentation, representation, acquisition, publication, program
  subtype TEXT,                           -- solo, group, collection_display, project, two_person, unknown
  title TEXT NOT NULL,
  title_lang TEXT,
  organizer_entity_id TEXT REFERENCES entities(entity_id),
  venue_id TEXT REFERENCES venues(venue_id),
  city TEXT,
  country_code TEXT REFERENCES region_map(country_code),
  edition_region TEXT,                    -- derived from country_code via region_map; NULL when venue unknown
  start_date TEXT,
  start_precision TEXT,
  end_date TEXT,
  end_precision TEXT,
  announced_date TEXT,
  date_text TEXT,                         -- original date string as published
  announced_status TEXT,                  -- as published: scheduled, cancelled, postponed, NULL
  tour_id TEXT,
  parent_event_id TEXT REFERENCES events(event_id),
  url TEXT,
  description_excerpt TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  parser_version TEXT NOT NULL,
  UNIQUE (source_id, source_event_key)
);

CREATE TABLE IF NOT EXISTS event_participants (
  event_id TEXT NOT NULL REFERENCES events(event_id),
  entity_id TEXT NOT NULL REFERENCES entities(entity_id),
  role TEXT NOT NULL,                     -- artist, curator, winner, nominee, finalist, resident, exhibitor_gallery, organizer, co_organizer
  name_as_listed TEXT NOT NULL,
  evidence_id TEXT REFERENCES evidence(evidence_id),
  extraction_method TEXT NOT NULL,        -- structured_field, title_pattern, list_markup, manual
  confidence TEXT NOT NULL DEFAULT 'high',
  PRIMARY KEY (event_id, entity_id, role)
);

CREATE TABLE IF NOT EXISTS event_evidence (
  event_id TEXT NOT NULL REFERENCES events(event_id),
  evidence_id TEXT NOT NULL REFERENCES evidence(evidence_id),
  PRIMARY KEY (event_id, evidence_id)
);

CREATE TABLE IF NOT EXISTS relationships (
  rel_id TEXT PRIMARY KEY,
  subject_entity_id TEXT NOT NULL REFERENCES entities(entity_id),
  object_entity_id TEXT NOT NULL REFERENCES entities(entity_id),
  rel_type TEXT NOT NULL,                 -- represents, co_represents, supports, residency, listed_artist
  scope TEXT,
  valid_from TEXT,
  valid_to TEXT,
  announced_date TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  source_id TEXT NOT NULL REFERENCES sources(source_id),
  evidence_id TEXT REFERENCES evidence(evidence_id),
  status TEXT NOT NULL DEFAULT 'source_asserted'
);

CREATE TABLE IF NOT EXISTS works (
  work_id TEXT PRIMARY KEY,
  id_namespace TEXT NOT NULL,
  id_value TEXT NOT NULL,
  artist_entity_id TEXT REFERENCES entities(entity_id),
  title TEXT,
  date_text TEXT,
  medium TEXT,
  classification TEXT,
  holding_entity_id TEXT REFERENCES entities(entity_id),
  acquisition_text TEXT,
  url TEXT,
  is_public_domain INTEGER,
  source_id TEXT NOT NULL REFERENCES sources(source_id),
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  UNIQUE (id_namespace, id_value)
);

CREATE TABLE IF NOT EXISTS articles (
  article_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(source_id),
  canonical_url TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  author_text TEXT,
  publisher TEXT,
  owner_group TEXT,
  article_type TEXT NOT NULL DEFAULT 'unknown', -- review, criticism, news, announcement, interview, listing, sponsored, unknown
  type_basis TEXT,                        -- how article_type was assigned (feed category, url path, ...)
  lang TEXT,
  published_at TEXT,
  modified_at TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  categories TEXT,
  excerpt TEXT,                           -- <= 300 chars, only when policy allows
  origin_group_key TEXT,                  -- normalized title key for syndication grouping
  content_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS article_mentions (
  article_id TEXT NOT NULL REFERENCES articles(article_id),
  entity_id TEXT NOT NULL REFERENCES entities(entity_id),
  mention_type TEXT NOT NULL,             -- title_mention, category_tag, structured
  evidence_text TEXT,
  status TEXT NOT NULL DEFAULT 'candidate',
  PRIMARY KEY (article_id, entity_id, mention_type)
);

CREATE TABLE IF NOT EXISTS evidence (
  evidence_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(source_id),
  url TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  http_status INTEGER,
  raw_path TEXT,                          -- relative to WORK_ROOT; NULL when storage policy forbids
  raw_sha256 TEXT,
  locator TEXT,
  excerpt TEXT,
  parser_version TEXT
);

CREATE TABLE IF NOT EXISTS reports (
  report_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  publisher TEXT,
  authors TEXT,
  sponsor TEXT,
  published_date TEXT,
  observation_period TEXT,
  geo_scope TEXT,
  methodology TEXT,
  sample TEXT,
  price_basis TEXT,
  official_url TEXT,
  local_path TEXT,
  sha256 TEXT,
  pages INTEGER,
  rights_note TEXT,
  access_status TEXT,                     -- local, downloaded, link_only, paid_not_purchased, not_found
  next_check TEXT,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS report_metrics (
  metric_id TEXT PRIMARY KEY,
  report_id TEXT NOT NULL REFERENCES reports(report_id),
  metric_name TEXT NOT NULL,
  value REAL,
  value_text TEXT,
  unit TEXT,
  geography TEXT,
  period TEXT,
  page TEXT,
  table_ref TEXT,
  excerpt TEXT,
  comparability_note TEXT
);

CREATE TABLE IF NOT EXISTS image_rights (
  asset_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(source_id),
  entity_id TEXT REFERENCES entities(entity_id),
  event_id TEXT REFERENCES events(event_id),
  work_id TEXT REFERENCES works(work_id),
  page_url TEXT,
  image_url TEXT,
  rights_holder TEXT,
  license TEXT,
  credit TEXT,
  usage_status TEXT NOT NULL,             -- public_domain_cc0, metadata_only, press_use_unverified, restricted, unknown
  basis TEXT,
  checked_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS crawl_runs (
  run_id TEXT NOT NULL,
  source_id TEXT NOT NULL REFERENCES sources(source_id),
  mode TEXT NOT NULL,                     -- initial, incremental
  started_at TEXT NOT NULL,
  finished_at TEXT,
  state TEXT NOT NULL,                    -- success, no_change, partial, blocked, error, skipped
  http_requests INTEGER DEFAULT 0,
  http_not_modified INTEGER DEFAULT 0,
  http_errors INTEGER DEFAULT 0,
  last_http_status INTEGER,
  records_fetched INTEGER DEFAULT 0,
  records_parsed INTEGER DEFAULT 0,
  records_inserted INTEGER DEFAULT 0,
  records_updated INTEGER DEFAULT 0,
  records_unchanged INTEGER DEFAULT 0,
  error TEXT,
  parser_version TEXT,
  PRIMARY KEY (run_id, source_id)
);

CREATE TABLE IF NOT EXISTS coverage (
  source_id TEXT NOT NULL REFERENCES sources(source_id),
  asof TEXT NOT NULL,
  edition_region TEXT NOT NULL,
  country_code TEXT NOT NULL DEFAULT '',
  record_kind TEXT NOT NULL,              -- event, article, work, relationship
  n_records INTEGER NOT NULL,
  earliest_date TEXT,
  latest_date TEXT,
  n_last_90d INTEGER,
  n_prev_90d INTEGER,
  n_upcoming INTEGER,
  history_note TEXT,                      -- e.g. "listing shows current+upcoming only"
  completeness TEXT NOT NULL,             -- full_listing, partial_listing, sample, unknown
  PRIMARY KEY (source_id, asof, edition_region, country_code, record_kind)
);

CREATE TABLE IF NOT EXISTS review_queue (
  item_id TEXT PRIMARY KEY,
  item_type TEXT NOT NULL,                -- identity, date, classification, rights, region, parser
  ref_table TEXT NOT NULL,
  ref_id TEXT NOT NULL,
  issue TEXT NOT NULL,
  detail TEXT,
  suggested_action TEXT,
  status TEXT NOT NULL DEFAULT 'open',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS signals (
  signal_id TEXT PRIMARY KEY,
  subject_type TEXT NOT NULL,
  subject_id TEXT NOT NULL,
  edition_region TEXT NOT NULL,
  asof TEXT NOT NULL,
  metric TEXT NOT NULL,
  window TEXT NOT NULL,
  value REAL,                             -- NULL when not observable
  denominator TEXT,
  model_version TEXT NOT NULL,
  evidence_ids TEXT,
  publishable INTEGER NOT NULL DEFAULT 0,
  reason TEXT
);

CREATE TABLE IF NOT EXISTS evidence_cards (
  card_id TEXT PRIMARY KEY,
  edition_region TEXT NOT NULL,
  section TEXT NOT NULL,                  -- H01..H08
  card_kind TEXT NOT NULL,                -- fact_card, observation_card, rookie_watch, gap_notice
  title TEXT NOT NULL,
  facts TEXT NOT NULL,
  comparison TEXT,
  interpretation TEXT,
  counter_evidence TEXT,
  limitations TEXT NOT NULL,
  event_ids TEXT,
  evidence_urls TEXT NOT NULL,
  n_independent_sources INTEGER,
  status TEXT NOT NULL DEFAULT 'draft_unreviewed',
  asof TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_events_region_start ON events(edition_region, start_date);
CREATE INDEX IF NOT EXISTS ix_participants_entity ON event_participants(entity_id);
CREATE INDEX IF NOT EXISTS ix_aliases_name ON aliases(name);
CREATE INDEX IF NOT EXISTS ix_articles_pub ON articles(published_at);
CREATE INDEX IF NOT EXISTS ix_works_artist ON works(artist_entity_id);

-- Reference FX (ECB euro reference rates). Used only for P2 market conversions with explicit date.
CREATE TABLE IF NOT EXISTS fx_rates (
  rate_date TEXT NOT NULL,
  base TEXT NOT NULL,
  quote TEXT NOT NULL,
  rate REAL NOT NULL,
  source_id TEXT NOT NULL REFERENCES sources(source_id),
  PRIMARY KEY (rate_date, base, quote)
);

-- Cache negative and ambiguous identifier lookups too, so later names are not starved by request caps.
CREATE TABLE IF NOT EXISTS identifier_queries (
  source_id TEXT NOT NULL REFERENCES sources(source_id),
  query_key TEXT NOT NULL,
  name_as_listed TEXT NOT NULL,
  checked_at TEXT NOT NULL,
  outcome TEXT NOT NULL CHECK(outcome IN ('unique_candidate', 'ambiguous', 'no_match')),
  evidence_id TEXT NOT NULL REFERENCES evidence(evidence_id),
  PRIMARY KEY (source_id, query_key)
);

-- Content layer for onlinedoctranslator.ai.
--
-- Ported from the SQLite schema the six sibling sites share, with the changes
-- Postgres and a serverless host actually require. It is deliberately NOT a
-- transliteration:
--
--  * `text not null default (datetime('now'))` becomes a real timestamptz. The
--    SQLite template stores dates as strings, which is why every date in those
--    codebases is sliced with .slice(0,10) and why a lexicographic sort once
--    put October before September in an estate report.
--  * autoincrement integer ids become identity columns.
--  * faq_json / files_json become jsonb, so a malformed value fails on write
--    rather than at render.
--  * Everything lives in its own schema, `content`, so a future table here can
--    never collide with Supabase's auth or storage tables.
--
-- The audience is translators and agencies who certify translations, not
-- document owners — that decides `type`, below.

create schema if not exists content;

-- A page's TYPE drives the publish queue order, the sitemap section, the
-- breadcrumb label and which pages the related rail will pair it with. The six
-- sibling sites learned this the hard way: 36 of traduzionemilano's pages were
-- service pages typed `blog`, which excluded them from its home page and
-- footer and labelled them "Article". Pick from a constrained set so that
-- cannot happen silently.
create type content.page_type as enum (
  'tool',        -- the category/comparison pages: CAT tools, translation memory
  'certify',     -- how to certify, accuracy statements, templates
  'credential',  -- ATA, sworn translator, becoming certified
  'workflow',    -- XLIFF, OCR, QA, post-editing
  'practice',    -- rates, invoices, finding clients
  'question',    -- a supporting question page in some hub
  'legal',
  'generic',
  'home'
);

create type content.page_status as enum ('draft', 'published');

create table content.pages (
  slug              text primary key,
  title             text not null,
  h1                text not null default '',
  meta_description  text not null default '',
  body_html         text not null default '',
  excerpt           text not null default '',
  type              content.page_type not null default 'generic',
  -- The HUB this page supports. A question page points at the commercial page
  -- it belongs to; a commercial page points at nothing. The sibling sites had
  -- to derive this from title tokens because nothing recorded it — record it.
  hub_slug          text references content.pages(slug) on delete set null,
  status            content.page_status not null default 'draft',
  faq               jsonb not null default '[]'::jsonb,
  schema_json       jsonb,
  canonical         text not null default '',
  in_nav            boolean not null default false,
  sort              integer not null default 100,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);
-- Serving a page is `where slug = ? and status = 'published'`, and the sitemap
-- and nav are `where status = 'published'` ordered by (sort, title).
create index pages_published on content.pages (status, sort, title);
create index pages_hub on content.pages (hub_slug) where hub_slug is not null;
create index pages_type on content.pages (type, status);

create table content.revisions (
  id          bigint generated always as identity primary key,
  slug        text not null,
  title       text not null,
  body_html   text not null,
  created_at  timestamptz not null default now()
);
create index revisions_slug on content.revisions (slug, id desc);

create table content.settings (
  key    text primary key,
  value  text not null
);

-- WordPress REST addresses a post by integer, and SemanticWP speaks that
-- contract: it reads an id from the create response and PUTs to /pages/<id> to
-- update. Nothing here is WordPress, so the id has to come from somewhere and
-- be STABLE — if a slug's id changed, every later update would write to the
-- wrong page or 404.
create table content.wp_ids (
  id    bigint generated always as identity primary key,
  slug  text not null unique
);
alter table content.wp_ids enable row level security;

-- NO LEADS TABLE. The six sibling sites are agencies that quote for work, so
-- each carries a quote form and a leads table. This is a SaaS: a reader goes to
-- pricing and subscribes, so the conversion is a signup the product already
-- records, and a lead table here would be a copied assumption with nothing to
-- put in it.
--
-- The question worth answering later is which GUIDE preceded a signup. That is
-- attribution on the existing registration, not a second store of people.

create table content.redirects (
  from_path  text primary key,
  to_path    text not null,
  created_at timestamptz not null default now()
);

-- Assistant referrals, counted per day and path. No IP, no user agent: a
-- counter, not analytics on individuals. Count a landing only when the
-- referrer HOST matches, never a substring — matching the string anywhere in a
-- log line once inflated a sibling site's figure nineteen-fold by counting RSC
-- prefetches.
create table content.ai_visits (
  day     date not null,
  source  text not null,
  path    text not null,
  visits  integer not null default 0,
  primary key (day, source, path)
);
create index ai_visits_day on content.ai_visits (day desc);

-- Row level security on every table. The site reads through the service role
-- from server components only; nothing here is ever queried from the browser,
-- and a draft in particular must never be readable with the anon key.
alter table content.pages      enable row level security;
alter table content.revisions  enable row level security;
alter table content.settings   enable row level security;
alter table content.redirects  enable row level security;
alter table content.ai_visits  enable row level security;

-- Published pages and redirects are the only things a public role may read, and
-- only for serving the site. No policy is created for leads: with RLS on and no
-- policy, anon and authenticated get nothing, which is the intent.
create policy pages_read_published on content.pages
  for select to anon, authenticated using (status = 'published');
create policy redirects_read on content.redirects
  for select to anon, authenticated using (true);

comment on schema content is
  'Content site for onlinedoctranslator.ai. Audience: translators and agencies who certify translations.';

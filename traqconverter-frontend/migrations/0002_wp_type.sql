-- Record WHICH REST ROUTE a page arrived through, separately from what the page
-- editorially is.
--
-- These were one column, and conflating them broke the pipeline's two most basic
-- operations. SemanticWP decides the post type itself (lib/content/publish-page.ts
-- defaults to post_type: "post"), POSTs to /wp/v2/posts or /wp/v2/pages
-- accordingly, stores that choice on its own row, and from then on addresses the
-- page only through that route — /posts/<id> for an update, /posts?slug= for the
-- duplicate probe, and lib/wp.ts listPosts derives each mirrored page's type
-- from the route it was found on, not from the response body.
--
-- The shim instead re-derived the route from the title: a question-shaped title
-- became a "post" and everything else a "page". So a page created at /pages with
-- the title "What is a translation memory?" was filed as a post and then:
--   * /pages?slug=... found nothing, so the duplicate probe said the page did
--     not exist and the pipeline would create it again on every run, forever;
--   * /pages/<id> 404ed, so no update could ever reach it.
--
-- wp_type is the route. `type` stays the editorial kind that picks the template
-- and pairs a question with the service page it supports.
alter table content.pages
  add column if not exists wp_type text not null default 'page'
    check (wp_type in ('page', 'post'));

-- The seed rows predate the column. A question is a post, matching what the old
-- derivation would have said, so nothing the pipeline has already seen moves.
update content.pages set wp_type = 'post' where type = 'question';

-- The listing is partitioned on this column on every inventory sync.
create index if not exists pages_wp_type_status_idx
  on content.pages (wp_type, status);

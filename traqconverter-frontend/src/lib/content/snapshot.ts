import "server-only"
import type { ContentPage } from "./shim-naming"

/**
 * The committed copy of every published page.
 *
 * WHY IT EXISTS. This section served 62 pages out of a hosted Postgres, and on
 * 2026-10-29 that database hit its free-tier EGRESS limit and answered HTTP 402
 * to every query. All 62 guides served 500s for a week; the homepage, which
 * touches no database, stayed up throughout. Shipping page bodies over the wire
 * on every revalidation — to render content that changes a few times a day — is
 * the entire fault.
 *
 * Read from here and that egress is ZERO, the pages cannot be taken down by a
 * billing limit, and the content has a backup that is not the database it is
 * backing up. The database stays the write path: the pipeline publishes through
 * the WP shim exactly as before, and `npx tsx scripts/export-snapshot.mts`
 * refreshes this file.
 *
 * THE TRADE, STATED PLAINLY: a newly published page appears when the snapshot
 * is regenerated and deployed, not the moment it is written. For a section that
 * gains a handful of pages a day that is the right side of the trade, and the
 * publish hook can trigger a deploy if it ever stops being.
 */
type Snapshot = { exported_at?: string; pages?: ContentPage[] }

let loaded: Snapshot | null = null

function load(): Snapshot {
  if (loaded) return loaded
  try {
    // Required lazily so a missing file is a degraded read rather than a build
    // failure — the snapshot is absent until the first export runs.

    loaded = require("@/content/snapshot.json") as Snapshot
  } catch {
    loaded = {}
  }
  return loaded
}

/** Every published page, or an empty list when no snapshot is committed yet. */
export function snapshotPages(): ContentPage[] {
  return load().pages ?? []
}

export function snapshotHasContent(): boolean {
  return snapshotPages().length > 0
}

export function snapshotExportedAt(): string | null {
  return load().exported_at ?? null
}

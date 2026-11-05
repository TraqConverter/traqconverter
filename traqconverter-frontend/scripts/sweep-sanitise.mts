/**
 * Re-sanitise every stored body.
 *
 * 57 of the 60 pages were written before this site had a sanitiser, so they
 * carry the WordPress page the pipeline generated: Gutenberg block comments, a
 * ~100KB scoped stylesheet, `has-white-color` text on a white background, and
 * the excerpt repeated as a full-width banner under the one the template
 * already prints.
 *
 * Writes the snapshot, and emits a patch for the live database.
 *
 *   npx tsx scripts/sweep-sanitise.mts            # report
 *   npx tsx scripts/sweep-sanitise.mts --apply    # rewrite snapshot + emit patch
 */
import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { parse } from "node-html-parser"
import { sanitiseBody, needsSanitising } from "../src/lib/content/sanitise.ts"

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..")
const SNAP = path.join(root, "src/content/snapshot.json")
const PATCH = path.join(root, ".sanitise-patch.json")
const APPLY = process.argv.includes("--apply")
/** Above this, something is being destroyed rather than stripped. */
const MAX_LOSS = 0.15

const visible = (h: string) => {
  const r = parse(h, { blockTextElements: { script: false, style: false, noscript: false } })
  for (const el of r.querySelectorAll("style, script, noscript")) el.remove()
  return r.text.replace(/\s+/g, " ").trim().split(" ").filter(Boolean).length
}

const snap = JSON.parse(fs.readFileSync(SNAP, "utf8")) as { exported_at?: string; pages: Array<Record<string, string>> }
const patch: Record<string, string> = {}
let changed = 0, skipped = 0, wordsBefore = 0, wordsAfter = 0

for (const p of snap.pages) {
  const before = p.body_html || ""
  if (!needsSanitising(before)) continue
  const after = sanitiseBody(before)
  const vb = visible(before), va = visible(after)
  wordsBefore += vb; wordsAfter += va
  const loss = vb ? 1 - va / vb : 0
  if (loss > MAX_LOSS) {
    skipped++
    console.log(`  SKIP ${p.slug} — would lose ${Math.round(loss * 100)}% of its visible text`)
    continue
  }
  patch[p.slug] = after
  if (APPLY) p.body_html = after
  changed++
}

console.log(`${changed} page(s) sanitised, ${skipped} skipped`)
console.log(`visible words ${wordsBefore} -> ${wordsAfter} (${Math.round(100 * (1 - wordsAfter / wordsBefore))}% removed — the hero, TOC and related rail the template renders itself)`)
if (!APPLY) { console.log("\ndry run — pass --apply"); process.exit(0) }
fs.writeFileSync(SNAP, JSON.stringify(snap, null, 0))
fs.writeFileSync(PATCH, JSON.stringify(patch))
console.log(`\nsnapshot rewritten; patch for the live database at ${path.basename(PATCH)} (${Math.round(fs.statSync(PATCH).size / 1024)}KB)`)

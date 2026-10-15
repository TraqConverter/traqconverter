export {}

// The pure parts of the WP shim, tested on the real titles the plan will send.
//
//   npx tsx scripts/test-wp-shim.ts
//
// Both functions here shipped broken in ways that no call site reveals:
// typeForTitle wrote `\bcertif\b`, which cannot match "certificate", so the
// first published page was filed `generic`; and the body's H1 was left in the
// markup, so every page rendered two.
import { extractLeadingH1, slugForTitle, typeForTitle } from "../src/lib/content/shim-naming"

let failures = 0
function eq(name: string, got: unknown, want: unknown) {
  const a = JSON.stringify(got)
  const b = JSON.stringify(want)
  if (a !== b) {
    console.error(`FAIL ${name}\n  got  ${a}\n  want ${b}`)
    failures += 1
  } else {
    console.log(`ok   ${name}`)
  }
}

// ── typeForTitle, on the 27 titles actually queued ──────────────────────────
// A credential is something a PERSON holds; a certification is something a
// DOCUMENT carries. Both say "certif", so the pairs below are the test.
const TITLES: Array<[string, "page" | "post", string]> = [
  ["Certificate of translation for USCIS: what it must say", "page", "certify"],
  ["Certified translation template, and when to stop using one", "page", "certify"],
  ["Certificate of translation accuracy: the wording, line by line", "page", "certify"],
  ["ATA certification: what it costs, what it tests, what it is worth", "page", "credential"],
  ["Sworn translator: which countries appoint them and what the title allows", "page", "credential"],
  ["Becoming a sworn translator for Spanish: what the appointment lets you sign", "page", "credential"],
  ["Sworn, certified or notarised: what the client is actually asking you to produce", "page", "certify"],
  ["CAT tools for translators: what they do and what they cost", "page", "tool"],
  ["Translation memory software: what to look for before you pay", "page", "tool"],
  ["OmegaT and the free CAT tools, honestly compared", "page", "tool"],
  ["TMX files, and moving a memory between tools", "page", "tool"],
  ["XLIFF files: how to open, edit and deliver them", "page", "tool"],
  ["XLIFF editors compared", "page", "tool"],
  ["Machine translation post-editing: what the work actually involves", "page", "workflow"],
  ["Translation rates per word, and what to charge instead", "page", "practice"],
  ["Translation rates per hour versus per word", "page", "practice"],
  // A question keeps its own type whichever route it arrives on, so the hub
  // rail can pair it with the page it supports.
  ["What does USCIS require on a certified translation?", "page", "question"],
  ["How much does ATA certification cost?", "page", "question"],
  ["Can a translator certify their own translation?", "page", "question"],
  ["How to become a sworn translator in Spain and in France", "page", "question"],
  ["What is a translation memory, and what is it worth per repeated segment?", "page", "question"],
  // The route can also say "post", which always means a question here.
  ["Translation rates per word", "post", "question"],
]
for (const [title, route, want] of TITLES) {
  eq(`type: ${title.slice(0, 54)}`, typeForTitle(title, route), want)
}

// The exact regression: a trailing \b on an open-ended stem.
eq("'certificate' is reached by the certif stem", typeForTitle("Certificate of accuracy", "page"), "certify")
eq("'notarised' is reached by the notaris stem", typeForTitle("Notarised translations explained", "page"), "certify")
eq("'qualifications' is reached by the qualif stem", typeForTitle("Translator qualifications", "page"), "credential")
// And the boundaries that must stay whole words, or they catch the wrong thing.
eq("'example' is not an exam", typeForTitle("An XLIFF file example for production", "page"), "tool")
eq("'automatic' is not ATA", typeForTitle("Automatic layout rebuilding", "page"), "workflow")

// ── extractLeadingH1 ───────────────────────────────────────────────────────
eq("a plain leading H1 is lifted and removed", extractLeadingH1('<h1 class="x">The Title</h1><p>Body.</p>'), {
  h1: "The Title",
  body: "<p>Body.</p>",
})
// The pipeline writes Gutenberg block markup, and the comment pair must go with
// the heading — an orphan `<!-- wp:heading -->` with no block is malformed.
eq(
  "the Gutenberg comment pair goes with it",
  extractLeadingH1('<!-- wp:heading {"level":1} -->\n<h1>The Title</h1>\n<!-- /wp:heading -->\n<p>Body.</p>'),
  { h1: "The Title", body: "\n<p>Body.</p>" },
)
eq("entities in the heading are decoded", extractLeadingH1("<h1>The Producer&#x27;s Playbook &amp; Guide</h1>"), {
  h1: "The Producer's Playbook & Guide",
  body: "",
})
eq("nested markup inside the heading is stripped", extractLeadingH1("<h1><span>Two</span> <em>parts</em></h1>x"), {
  h1: "Two parts",
  body: "x",
})
eq("a body with no H1 is returned untouched", extractLeadingH1("<p>No heading here.</p>"), {
  h1: null,
  body: "<p>No heading here.</p>",
})
// Only the FIRST H1 is lifted. A second one is a defect in the draft, and
// silently swallowing it would hide that from the rendered check.
eq("a second H1 is left in place", extractLeadingH1("<h1>One</h1><p>a</p><h1>Two</h1>"), {
  h1: "One",
  body: "<p>a</p><h1>Two</h1>",
})
eq("an H1 further down the body is still lifted", extractLeadingH1("<p>intro</p><h1>Late</h1><p>b</p>"), {
  h1: "Late",
  body: "<p>intro</p><p>b</p>",
})
eq("an empty H1 yields null rather than an empty title", extractLeadingH1("<h1>  </h1><p>a</p>"), {
  h1: null,
  body: "<p>a</p>",
})

// ── slugForTitle ───────────────────────────────────────────────────────────
eq("slug from a title", slugForTitle("Certificate of translation for USCIS: what it must say"), "certificate-of-translation-for-uscis-what-it-must-say")
eq("apostrophes are dropped, not hyphenated", slugForTitle("The Producer's Playbook"), "the-producers-playbook")
// A sibling site served /chi-pu%C3%B2-fare-... for months.
eq("accents are folded, not percent-encoded", slugForTitle("Traduzione giurata è valida"), "traduzione-giurata-e-valida")
eq("no trailing hyphen survives", slugForTitle("Rates, per word —"), "rates-per-word")
eq("an empty title falls back to the section root", slugForTitle(""), "home")

if (failures > 0) {
  console.error(`\n${failures} failure(s)`)
  process.exit(1)
}
console.log(`\nall ${TITLES.length + 18} wp-shim tests passed`)

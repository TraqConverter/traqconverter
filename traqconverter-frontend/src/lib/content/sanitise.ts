import "server-only"
import { parse } from "node-html-parser"

/**
 * Strip the WordPress page the pipeline wrote, leaving the article.
 *
 * SemanticWP publishes a fully "designed" page — its own hero, CTA bands,
 * stat strips and a scoped stylesheet — because it normally lands in a
 * WordPress theme it cannot style. This site has its own design, so none of
 * that belongs here, and without the strip it renders raw: Gutenberg block
 * comments, `has-white-color` on a white background, and the page excerpt
 * printed a second time as an enormous centred banner under the one the
 * template already shows.
 *
 * 57 of this section's 60 pages shipped that way. The sibling sites have run
 * this strip since launch; this one was cloned before it existed.
 */

/**
 * Chrome that is REMOVED WHOLE, content and all.
 *
 * Each of these is presentation this site's template already provides, so
 * keeping the text would duplicate what the page renders anyway: the hero is
 * the excerpt the template prints under the H1, the TOC is the "On this page"
 * block, the related rail is the related rail.
 *
 * NARROWER THAN THE SIBLING SITES' LIST, deliberately. Theirs also deletes
 * `swp-check` and `swp-stepnum`, where those classes mark an icon and a step
 * number. In this section's markup `swp-check` wraps the checklist ITEM, so
 * the sibling rule would have deleted four blocks of real article text per
 * page — measured, not assumed, before this list was cut down.
 *
 * The table of contents is kept for the same reason. This template builds no
 * TOC of its own, so removing the generated one left a 2,300-word guide with
 * no way to navigate it. Stripped of its classes it renders as a plain list of
 * working anchor links, which is the point of it.
 */
const REMOVE_WHOLE =
  /\bswp-(hero|related|cta|form|breadcrumb|nav|footer|header|banner|divider|pills|statband|stats|stat|ico|ico-[\w-]+)\b/

const WP_PRESENTATION = /\b(has-[\w-]*-color|has-text-color|has-background|has-text-align-\w+|wp-block-[\w-]+|is-layout-\w+|is-style-\w+)\b/

/**
 * `id` is kept, and that is load-bearing.
 *
 * The generated table of contents links to `#heading-slug` anchors on the h2s.
 * Dropping the id leaves every one of those links pointing at nothing — and
 * takes with it the fragment URLs that deep links and AI assistants cite.
 * Measured on the live page before this list was written: 6 headings carried
 * ids and the TOC resolved against them.
 */
const KEEP_ATTRS = new Set(["href", "src", "alt", "title", "colspan", "rowspan", "target", "rel", "id"])
const HEADING = /^h[2-6]$/i

export function sanitiseBody(html: string): string {
  if (!html.trim()) return ""

  // Gutenberg block delimiters are HTML comments, so they never render — but
  // they are ~15% of the bytes of every page here and they confuse anything
  // that reads the markup, including the model that optimises it later.
  const withoutBlockComments = html.replace(/<!--\s*\/?wp:[\s\S]*?-->/g, "")

  const root = parse(withoutBlockComments, {
    blockTextElements: { script: false, style: false, noscript: false },
  })

  for (const el of root.querySelectorAll(
    "style, script, noscript, svg, iframe, form, button, input, textarea, select",
  ))
    el.remove()

  for (const el of root.querySelectorAll("[class]")) {
    if (REMOVE_WHOLE.test(el.getAttribute("class") ?? "")) el.remove()
  }

  // The template renders the H1 from the page's title, so a second one in the
  // body is a duplicate heading on every page.
  const h1 = root.querySelector("h1")
  if (h1) h1.remove()

  for (const el of root.querySelectorAll("*")) {
    for (const name of Object.keys(el.attributes)) {
      if (!KEEP_ATTRS.has(name.toLowerCase())) el.removeAttribute(name)
    }
  }

  // Presentation wrappers go, their content stays. Eight passes because these
  // nest: a section inside a div inside a figure is routine in block markup.
  for (let pass = 0; pass < 8; pass++) {
    const wrappers = root.querySelectorAll(
      "div, section, article, span, figure, header, footer, main, aside",
    )
    if (wrappers.length === 0) break
    for (const el of wrappers) el.replaceWith(...el.childNodes)
  }

  // A heading whose section lost all of its content to the pass above is an
  // empty promise to the reader — drop it rather than leave a dangling title.
  const nodes = () =>
    root.childNodes.filter(
      (n) => (n.text ?? "").trim() !== "" || (n as { rawTagName?: string }).rawTagName,
    )
  for (let pass = 0; pass < 3; pass++) {
    const kids = nodes()
    let removed = false
    for (let i = 0; i < kids.length; i++) {
      const tag = (kids[i] as { rawTagName?: string }).rawTagName ?? ""
      if (!HEADING.test(tag)) continue
      let hasBody = false
      for (let j = i + 1; j < kids.length; j++) {
        const next = (kids[j] as { rawTagName?: string }).rawTagName ?? ""
        if (HEADING.test(next)) break
        if ((kids[j].text ?? "").trim()) {
          hasBody = true
          break
        }
      }
      if (!hasBody) {
        kids[i].remove()
        removed = true
      }
    }
    if (!removed) break
  }

  return root.innerHTML
    .replace(/<(p|li|td|h[2-6])>\s*<\/\1>/gi, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim()
}

/** Does this body still carry WordPress presentation that would render raw? */
export function needsSanitising(html: string): boolean {
  return /<!--\s*\/?wp:/.test(html) || WP_PRESENTATION.test(html) || REMOVE_WHOLE.test(html)
}

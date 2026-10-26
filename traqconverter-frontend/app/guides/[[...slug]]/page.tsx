import type { Metadata } from "next"
import Link from "next/link"
import { notFound, redirect } from "next/navigation"
import { getPage, getRedirect, listPages, relatedPages, normaliseSlug } from "@/lib/content/pages"
import { CONTENT_BASE, COLOR, SITE_NAME, TYPE_LABEL, contentHref, contentUrl } from "@/lib/content/config"
import { BrandMark, BrandName } from "@/components/brand/Logo"

export const runtime = "nodejs"
// Revalidate rather than rebuild: the pipeline publishes through the WP shim at
// any hour, and a statically exported section would not show a new page until
// the next deploy.
export const revalidate = 300

type Props = { params: Promise<{ slug?: string[] }> }

function slugFrom(parts: string[] | undefined): string {
  return normaliseSlug((parts ?? []).join("/"))
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params
  const page = await getPage(slugFrom(slug))
  if (!page) return { title: "Not found", robots: { index: false, follow: false } }
  const url = page.canonical || contentUrl(page.slug)
  return {
    title: page.title,
    description: page.meta_description || page.excerpt || undefined,
    alternates: { canonical: url },
    // Only a published page reaches here — getPage filters drafts — so this is
    // always indexable. A blanket noindex on a whole section is the single
    // easiest way to lose one, so it is stated rather than inherited.
    robots: { index: true, follow: true, "max-image-preview": "large", "max-snippet": -1 },
    openGraph: { title: page.title, description: page.meta_description || undefined, url, type: "article" },
  }
}

export default async function GuidePage({ params }: Props) {
  const { slug: parts } = await params
  const slug = slugFrom(parts)
  const page = await getPage(slug)

  if (!page) {
    // A renamed slug must not 404: on a sibling site one renamed page was
    // holding 1,296 impressions.
    const to = await getRedirect(slug)
    if (to) redirect(to.startsWith("/") ? to : contentHref(normaliseSlug(to)))
    notFound()
  }

  const all = await listPages()
  const related = relatedPages(page, all, 6)
  const hub = page.hub_slug ? all.find((p) => p.slug === page.hub_slug) : null
  const label = TYPE_LABEL[page.type] ?? ""

  const jsonLd = {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": page.type === "question" ? "Article" : "WebPage",
        "@id": `${contentUrl(page.slug)}#page`,
        url: contentUrl(page.slug),
        name: page.title,
        description: page.meta_description || undefined,
        dateModified: page.updated_at,
        isPartOf: { "@id": `${contentUrl("home")}#section` },
      },
      {
        "@type": "BreadcrumbList",
        "@id": `${contentUrl(page.slug)}#breadcrumb`,
        itemListElement: [
          { "@type": "ListItem", position: 1, name: SITE_NAME, item: contentUrl("home").replace(`/${CONTENT_BASE}`, "/") },
          { "@type": "ListItem", position: 2, name: "Guides", item: contentUrl("home") },
          ...(hub ? [{ "@type": "ListItem", position: 3, name: hub.title, item: contentUrl(hub.slug) }] : []),
          { "@type": "ListItem", position: hub ? 4 : 3, name: page.title, item: contentUrl(page.slug) },
        ],
      },
      ...(page.faq.length
        ? [
            {
              "@type": "FAQPage",
              "@id": `${contentUrl(page.slug)}#faq`,
              mainEntity: page.faq.map((f) => ({
                "@type": "Question",
                name: f.q,
                acceptedAnswer: { "@type": "Answer", text: f.a },
              })),
            },
          ]
        : []),
    ],
  }

  return (
    <main style={{ background: COLOR.cream, color: COLOR.text, minHeight: "100vh" }}>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }} />

      <header style={{ borderBottom: `1px solid ${COLOR.creamDark}`, background: "#fff" }}>
        <div style={{ margin: "0 auto", maxWidth: 1100, padding: "16px 20px", display: "flex", alignItems: "center", gap: 10 }}>
          <Link href="/" style={{ display: "flex", alignItems: "center", gap: 8, textDecoration: "none", color: COLOR.text }}>
            <BrandMark />
            <BrandName />
          </Link>
          <Link href={contentHref("home")} style={{ marginLeft: "auto", color: COLOR.teal, textDecoration: "none", fontSize: 14 }}>
            Guides
          </Link>
        </div>
      </header>

      <div style={{ margin: "0 auto", maxWidth: 1100, padding: "28px 20px 64px" }}>
        <nav aria-label="Breadcrumb" style={{ fontSize: 13, color: COLOR.subtle, display: "flex", gap: 8, flexWrap: "wrap" }}>
          <Link href={contentHref("home")} style={{ color: COLOR.subtle, textDecoration: "none" }}>
            Guides
          </Link>
          {hub && (
            <>
              <span aria-hidden="true">/</span>
              <Link href={contentHref(hub.slug)} style={{ color: COLOR.subtle, textDecoration: "none" }}>
                {hub.title}
              </Link>
            </>
          )}
          <span aria-hidden="true">/</span>
          <span style={{ color: COLOR.muted }}>{page.title}</span>
        </nav>

        {label && (
          <p style={{ margin: "22px 0 0", fontSize: 12, letterSpacing: "0.08em", textTransform: "uppercase", color: COLOR.teal }}>
            {label}
          </p>
        )}
        <h1 style={{ margin: "8px 0 0", fontSize: "clamp(1.8rem, 3.4vw, 2.6rem)", lineHeight: 1.15, maxWidth: "26ch" }}>
          {page.h1 || page.title}
        </h1>
        {(page.meta_description || page.excerpt) && (
          <p style={{ margin: "16px 0 0", maxWidth: "62ch", fontSize: 17, lineHeight: 1.65, color: COLOR.muted }}>
            {page.meta_description || page.excerpt}
          </p>
        )}

        <div
          className="guide-body"
          style={{ marginTop: 34, maxWidth: "68ch", fontSize: 16.5, lineHeight: 1.75 }}
          dangerouslySetInnerHTML={{ __html: page.body_html }}
        />

        {page.faq.length > 0 && (
          <section style={{ marginTop: 48, maxWidth: "68ch" }}>
            <h2 style={{ fontSize: 22, borderTop: `2px solid ${COLOR.text}`, paddingTop: 12 }}>Questions</h2>
            <dl>
              {page.faq.map((f) => (
                <div key={f.q} style={{ borderBottom: `1px solid ${COLOR.creamDark}`, padding: "14px 0" }}>
                  <dt style={{ fontWeight: 600 }}>{f.q}</dt>
                  <dd style={{ margin: "6px 0 0", color: COLOR.muted }}>{f.a}</dd>
                </div>
              ))}
            </dl>
          </section>
        )}

        {related.length > 0 && (
          <section style={{ marginTop: 52 }}>
            <h2 style={{ fontSize: 18, borderTop: `2px solid ${COLOR.text}`, paddingTop: 12 }}>Related</h2>
            <ul style={{ listStyle: "none", margin: "14px 0 0", padding: 0, display: "grid", gap: 0, gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))" }}>
              {related.map((r) => (
                <li key={r.slug} style={{ borderBottom: `1px solid ${COLOR.creamDark}` }}>
                  <Link href={contentHref(r.slug)} style={{ display: "block", padding: "12px 16px 12px 0", color: COLOR.muted, textDecoration: "none", fontSize: 15 }}>
                    {r.title}
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* The product is the point of the section: every guide ends at it. */}
        <aside style={{ marginTop: 56, background: COLOR.tealSoft, border: `1px solid ${COLOR.teal}`, borderRadius: 12, padding: "22px 24px", maxWidth: "68ch" }}>
          <h2 style={{ margin: 0, fontSize: 19 }}>Produce the certified file in {SITE_NAME}</h2>
          <p style={{ margin: "8px 0 16px", color: COLOR.tealDark, lineHeight: 1.6 }}>
            Translate the document, keep the layout, and generate the certification page your client needs.
          </p>
          <Link
            href="/register"
            style={{ display: "inline-block", background: COLOR.teal, color: "#fff", textDecoration: "none", padding: "11px 20px", borderRadius: 8, fontWeight: 600 }}
          >
            Start free
          </Link>
        </aside>
      </div>
    </main>
  )
}

"use client"

import Image from "next/image"

import { useState } from "react"
import Link from "next/link"
import CompanyLine from "@/components/legal/CompanyLine"
import { VAT_NOTE } from "@/lib/company"
import {
  contactHref,
  euro,
  euroCents,
  packPerPage,
  pagesLabel,
  planBullets,
  usePlans,
  type Plan,
  type PlanCatalog,
} from "@/lib/plans"
import { BrandMark, BrandName } from "@/components/brand/Logo"
import DemoVideo from "@/components/landing/DemoVideo"

const CREAM = "#faf5ee"
const CREAM_DARK = "#f3ecdb"
const TEAL = "#0a7870"
const TEAL_DARK = "#0a5e58"
const TEAL_SOFT = "#cfe6e2"
const TEXT = "#1f2a2e"
const MUTED = "#6b6558"
const SUBTLE = "#8a8270"
const BORDER = "#e7ddc5"
const ACCENT_GOLD = "#c88a1a"
const ACCENT_RUST = "#b14a3a"

const H2_SIZE = "clamp(28px, 5vw, 38px)"
const H3_SIZE = "clamp(24px, 4vw, 30px)"

export default function LandingPage() {
  return (
    <div style={{ background: CREAM, color: TEXT, minHeight: "100vh", overflowX: "clip" }}>
      <TopBar />
      <main>
        <Hero />
        <TrustBar />
        <WhyBuy />
        <SeeItWork />
        <ValueStrip />
        <HowItWorks />
        <FeatureGroups />
        <Workbench />
        <GetPaid />
        <Security />
        <Pricing />
        <RiskReversal />
        <FAQ />
        <FinalCTA />
      </main>
      <Footer />
    </div>
  )
}

function TopBar() {
  return (
    <header
      style={{
        background: CREAM,
        borderBottom: `1px solid ${BORDER}`,
        position: "sticky",
        top: 0,
        zIndex: 50,
        backdropFilter: "blur(8px)",
      }}
    >
      <div
        className="max-w-[1200px] mx-auto flex items-center justify-between"
        style={{ padding: "14px 20px" }}
      >
        <Link href="/" className="flex items-center gap-3" aria-label="OnlineDocTranslator home">
          <BrandMark size={36} />
          <div>
            <div style={{ fontSize: 16, fontWeight: 600, color: TEXT }}>
              <BrandName />
            </div>
            <div
              style={{
                fontSize: 9,
                letterSpacing: "0.2em",
                color: SUBTLE,
                marginTop: -2,
              }}
            >
              <span className="hidden sm:inline">CERTIFIED TRANSLATION WORKSPACE</span>
            </div>
          </div>
        </Link>
        <nav aria-label="Main" className="hidden lg:flex items-center gap-7">
          <a href="#demo" style={navLink}>Demo</a>
          <a href="#features" style={navLink}>Features</a>
          <a href="#get-paid" style={navLink}>Get paid</a>
          <a href="#security" style={navLink}>Security</a>
          <a href="#pricing" style={navLink}>Pricing</a>
          <a href="#faq" style={navLink}>FAQ</a>
        </nav>
        <div className="flex items-center gap-1 sm:gap-3 whitespace-nowrap">
          <Link
            href="/login"
            style={{
              fontSize: 14,
              fontWeight: 500,
              color: TEXT,
              padding: "8px 12px",
            }}
          >
            Sign in
          </Link>
          <Link
            href="/register"
            style={{
              fontSize: 14,
              fontWeight: 600,
              color: "#fff",
              background: TEAL,
              padding: "9px 18px",
              borderRadius: 999,
            }}
          >
            <span className="sm:hidden">Try free</span>
            <span className="hidden sm:inline">Start free trial</span>
          </Link>
        </div>
      </div>
    </header>
  )
}

const navLink = {
  fontSize: 14,
  color: MUTED,
  textDecoration: "none",
  fontWeight: 500,
}

const eyebrowStyle = {
  fontSize: 11,
  letterSpacing: "0.16em",
  color: TEAL,
  fontWeight: 600,
  marginBottom: 10,
}

function Hero() {
  const catalog = usePlans()
  const trialLine = catalog
    ? `${pagesLabel(catalog.trial.credits)} free for ${catalog.trial.days} days`
    : "Free trial"
  return (
    <section style={{ position: "relative", overflow: "hidden" }}>
      <div
        aria-hidden="true"
        style={{
          position: "absolute",
          top: -120,
          right: -80,
          width: 480,
          height: 480,
          borderRadius: "50%",
          background:
            "radial-gradient(closest-side, rgba(10,120,112,0.08), transparent)",
          filter: "blur(20px)",
          pointerEvents: "none",
        }}
      />
      <div
        className="max-w-[1200px] mx-auto"
        style={{ padding: "clamp(48px, 8vw, 80px) 20px 64px" }}
      >
        <div className="grid lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)] gap-10 lg:gap-12 items-center">
          <div className="min-w-0">
            <div
              className="inline-flex items-center gap-2 mb-6"
              style={{
                background: TEAL_SOFT,
                color: TEAL_DARK,
                padding: "6px 14px",
                borderRadius: 999,
                fontSize: 12,
                fontWeight: 600,
                letterSpacing: "0.06em",
              }}
            >
              <span
                aria-hidden="true"
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: "50%",
                  background: TEAL,
                  flexShrink: 0,
                }}
              />
              FOR CERTIFIED TRANSLATORS AND AGENCIES
            </div>
            <h1
              style={{
                fontSize: "clamp(36px, 6.5vw, 56px)",
                lineHeight: 1.05,
                fontWeight: 700,
                letterSpacing: "-0.02em",
                color: TEXT,
                marginBottom: 20,
              }}
            >
              Certified translations, layout and all.{" "}
              <span style={{ color: TEAL }}>Ready for your signature.</span>
            </h1>
            <p
              style={{
                fontSize: 18,
                lineHeight: 1.55,
                color: MUTED,
                marginBottom: 32,
                maxWidth: 580,
              }}
            >
              Upload a scan, PDF, photo or Word file. OnlineDocTranslator translates it,
              rebuilds the page and marks signatures, stamps and unreadable parts.
              You check it next to the original, add your certification page,
              and send it to the client, with payment collected first if you want.
            </p>
            <div className="flex flex-wrap items-center gap-3 mb-8">
              <Link
                href="/register"
                style={{
                  background: TEAL,
                  color: "#fff",
                  padding: "14px 26px",
                  borderRadius: 999,
                  fontWeight: 600,
                  fontSize: 15,
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 8,
                }}
              >
                Start free trial
                <span aria-hidden="true">→</span>
              </Link>
              <a
                href="#pricing"
                style={{
                  background: "#ffffff",
                  color: TEXT,
                  padding: "14px 26px",
                  borderRadius: 999,
                  fontWeight: 600,
                  fontSize: 15,
                  border: `1px solid ${BORDER}`,
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 8,
                }}
              >
                See pricing
              </a>
            </div>
            <ul className="flex flex-wrap items-center gap-x-7 gap-y-2">
              {[
                "No credit card required",
                trialLine,
                "You review and sign every document",
              ].map((t) => (
                <li
                  key={t}
                  className="flex items-center gap-2"
                  style={{ fontSize: 13, color: MUTED }}
                >
                  <Check />
                  {t}
                </li>
              ))}
            </ul>
          </div>

          <HeroVisual />
        </div>
      </div>
    </section>
  )
}

function HeroVisual() {
  return (
    <figure className="min-w-0" style={{ margin: 0 }}>
      <DemoVideo
        eager
        src="/landing/demo-editor.webm"
        poster="/landing/demo-editor.png"
        label="Demo: in the editor, clicking a translated line highlights the same line on the original document"
      />
      <figcaption className="flex items-start gap-2" style={{ fontSize: 13, color: MUTED, marginTop: 12 }}>
        <span style={{ color: TEAL, flexShrink: 0, marginTop: 3 }}>
          <Check />
        </span>
        <span>
          <strong style={{ color: TEXT, fontWeight: 600 }}>Click a line, see its source.</strong> Recorded in the live
          app on a sample certificate.
        </span>
      </figcaption>
    </figure>
  )
}

function Shot({
  src,
  width,
  height,
  alt,
  priority = false,
  maxHeight,
}: {
  src: string
  width: number
  height: number
  alt: string
  priority?: boolean
  maxHeight?: number
}) {
  return (
    <div
      style={{
        background: "#ffffff",
        border: `1px solid ${BORDER}`,
        borderRadius: 20,
        boxShadow: "0 18px 44px rgba(30,30,20,0.10)",
        overflow: "hidden",
      }}
    >
      <div aria-hidden="true" className="flex items-center gap-1.5" style={{ padding: "10px 14px", borderBottom: `1px solid ${CREAM_DARK}` }}>
        <div style={dot("#ffb8a8")} />
        <div style={dot("#ffd98a")} />
        <div style={dot("#a8d9a3")} />
      </div>
      <div style={{ maxHeight, overflow: "hidden" }}>
        <Image src={src} width={width} height={height} alt={alt} priority={priority} sizes="(min-width: 768px) 600px, 100vw" style={{ width: "100%", height: "auto", display: "block" }} />
      </div>
    </div>
  )
}

const dot = (c: string) => ({
  width: 9,
  height: 9,
  borderRadius: "50%",
  background: c,
})

function TrustBar() {
  return (
    <section
      aria-label="At a glance"
      style={{
        background: CREAM_DARK,
        borderTop: `1px solid ${BORDER}`,
        borderBottom: `1px solid ${BORDER}`,
      }}
    >
      <dl
        className="max-w-[1200px] mx-auto grid grid-cols-2 md:grid-cols-4 gap-y-6 gap-x-6"
        style={{ padding: "28px 20px" }}
      >
        {[
          { n: "28", l: "Languages" },
          { n: "PDF · DOCX · JPG · PNG", l: "Input formats, up to 20 MB" },
          { n: "DOCX · PDF", l: "Export formats" },
          { n: "5 AI edits", l: "Included per page" },
        ].map((s) => (
          <div key={s.l} className="min-w-0 flex flex-col-reverse">
            <dt style={{ fontSize: 12, color: MUTED, marginTop: 2 }}>{s.l}</dt>
            <dd
              style={{
                fontSize: "clamp(18px, 2.2vw, 24px)",
                fontWeight: 700,
                color: TEAL,
                letterSpacing: "-0.02em",
                overflowWrap: "anywhere",
              }}
            >
              {s.n}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

const STEPS = [
  {
    n: "01",
    t: "Upload",
    b: "Drop in a PDF, scan, photo or Word file, or a whole client batch. Pick the target language; the source can be detected for you.",
  },
  {
    n: "02",
    t: "Review & edit",
    b: "Correct the translation in place, next to the original. Uncertain readings are flagged, and a check lists anything to look at before you sign.",
  },
  {
    n: "03",
    t: "Certify & deliver",
    b: "Add your own certification page or the standard one, then export one delivery PDF: translation, certification and a copy of the original.",
  },
  {
    n: "04",
    t: "Get paid",
    b: "Send the client a private download link. Make it protected and they see a watermarked preview until they've paid you.",
  },
]

function HowItWorks() {
  return (
    <section
      id="how-it-works"
      style={{
        padding: "80px 20px",
        background: CREAM_DARK,
        borderBottom: `1px solid ${BORDER}`,
      }}
    >
      <div className="max-w-[1200px] mx-auto">
        <SectionHeader
          eyebrow="HOW IT WORKS"
          title="From the client's scan to a paid delivery"
        />
        <ol className="grid sm:grid-cols-2 lg:grid-cols-4 gap-5 mt-12">
          {STEPS.map((s) => (
            <li
              key={s.n}
              style={{
                background: "#ffffff",
                border: `1px solid ${BORDER}`,
                borderRadius: 20,
                padding: 24,
              }}
            >
              <div
                aria-hidden="true"
                style={{
                  fontSize: 34,
                  fontWeight: 700,
                  color: TEAL,
                  letterSpacing: "-0.04em",
                  lineHeight: 1,
                  marginBottom: 14,
                }}
              >
                {s.n}
              </div>
              <h3 style={{ fontSize: 17, fontWeight: 600, color: TEXT, marginBottom: 8 }}>
                {s.t}
              </h3>
              <p style={{ fontSize: 14, lineHeight: 1.55, color: MUTED }}>
                {s.b}
              </p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  )
}

type Group = {
  icon: React.ReactNode
  title: string
  lede: string
  items: string[]
  plan?: string
}

const GROUPS: Group[] = [
  {
    icon: <IconLayout />,
    title: "Translate",
    lede: "Layout-preserving translation of scans, PDFs, photos and Word files.",
    items: [
      "Tables, forms and signature blocks come back where they were, as an editable Word document",
      "Signatures, stamps and seals noted in brackets: [Signature], [Stamp: …]",
      "[illegible] only on the part that can't be read; names, dates and figures are never guessed",
      "Instructions for the AI on each project, plus a library of saved instructions",
      "Editable copy mode: a same-language Word file of the document for your CAT tool",
    ],
  },
  {
    icon: <IconBolt />,
    title: "Edit & check",
    lede: "Work in the translated document, side by side with the original.",
    items: [
      "Type corrections directly; click any line to see it highlighted on the original",
      "Uncertain readings are flagged for you to check",
      "Highlight a passage and ask the AI to change just that part",
      "Insert and move pictures, your logo and your stamp",
      "Undo step by step, or regenerate the document with new instructions",
      "Ready-to-certify check: missing numbers, uncertain readings, possibly untranslated text, a missing certification page",
    ],
  },
  {
    icon: <IconShield />,
    title: "Certify",
    lede: "Your certification page, filled in and exported with the translation.",
    items: [
      "Upload your own Word certification with merge fields, or use the standard page",
      "Choose the template for each project, or when you click Certify & deliver",
      "Edit the date and languages in place",
      "Dates and language names are written in the template's language",
    ],
    plan: "Pro and above",
  },
  {
    icon: <IconSend />,
    title: "Deliver & get paid",
    lede: "One file for the client, and a link to send it.",
    items: [
      "One-click delivery PDF: translation, certification and a copy of the original",
      "Private client download links that expire after 1, 7 or 30 days",
      "Protected links: a watermarked, blurred preview until the client pays",
      "Clients pay through your own Stripe account or your PayPal.me",
      "Batches: several files for one client, one ZIP download",
    ],
  },
  {
    icon: <IconBrain />,
    title: "Learns from your work",
    lede: "Each job you finish makes the next one faster.",
    items: [
      "Recurring documents (same type and country) start from your template automatically",
      "Add from a past job: turn an old original and your translation into a template",
      "Translation memory built from the text you approve and deliver",
      "TMX import and export; every entry editable",
      "A glossary that picks up the terms you correct",
      "Shared names and terms across every document in a batch",
    ],
    plan: "Memory and glossary on Pro and above",
  },
  {
    icon: <IconUsers />,
    title: "Team",
    lede: "For agencies and studios that share the work.",
    items: [
      "Team members with roles: admin, PM, reviewer, member",
      "Assign projects; the assignee gets an email",
      "An Assigned to me filter on the projects list",
      "In-app notifications when a translation is ready",
    ],
  },
]

function FeatureGroups() {
  return (
    <section id="features" style={{ padding: "80px 20px" }}>
      <div className="max-w-[1200px] mx-auto">
        <SectionHeader
          eyebrow="FEATURES"
          title="Everything a certified job needs, in one place"
          subtitle="Translate, check, certify, deliver and get paid, without moving files between tools."
        />
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-5 mt-12">
          {GROUPS.map((g) => (
            <GroupCard key={g.title} group={g} />
          ))}
        </div>
      </div>
    </section>
  )
}

function GroupCard({ group }: { group: Group }) {
  return (
    <article
      className="flex flex-col"
      style={{
        background: "#ffffff",
        border: `1px solid ${BORDER}`,
        borderRadius: 20,
        padding: 24,
      }}
    >
      <div className="flex items-center gap-3" style={{ marginBottom: 12 }}>
        <IconTile>{group.icon}</IconTile>
        <h3 style={{ fontSize: 19, fontWeight: 700, color: TEXT }}>{group.title}</h3>
      </div>
      <p style={{ fontSize: 14, lineHeight: 1.55, color: MUTED, marginBottom: 14 }}>{group.lede}</p>
      <ul className="space-y-2.5" style={{ flex: 1 }}>
        {group.items.map((it) => (
          <li key={it} className="flex items-start gap-2.5" style={{ fontSize: 14, lineHeight: 1.5, color: TEXT }}>
            <span style={{ color: TEAL, flexShrink: 0, marginTop: 3 }}>
              <Check />
            </span>
            <span>{it}</span>
          </li>
        ))}
      </ul>
      {group.plan && (
        <div
          style={{
            alignSelf: "flex-start",
            marginTop: 16,
            fontSize: 11,
            fontWeight: 600,
            letterSpacing: "0.04em",
            color: TEAL_DARK,
            background: CREAM_DARK,
            border: `1px solid ${BORDER}`,
            padding: "4px 10px",
            borderRadius: 999,
          }}
        >
          {group.plan}
        </div>
      )}
    </article>
  )
}

function IconTile({ children }: { children: React.ReactNode }) {
  return (
    <div
      aria-hidden="true"
      style={{
        width: 44,
        height: 44,
        borderRadius: 12,
        background: TEAL_SOFT,
        color: TEAL,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        flexShrink: 0,
      }}
    >
      {children}
    </div>
  )
}

function FeatureCard({
  icon,
  title,
  body,
}: {
  icon: React.ReactNode
  title: string
  body: string
}) {
  return (
    <div
      style={{
        background: "#ffffff",
        border: `1px solid ${BORDER}`,
        borderRadius: 20,
        padding: 24,
      }}
    >
      <div style={{ marginBottom: 16 }}>
        <IconTile>{icon}</IconTile>
      </div>
      <h3 style={{ fontSize: 17, fontWeight: 600, color: TEXT, marginBottom: 8 }}>
        {title}
      </h3>
      <p style={{ fontSize: 14, lineHeight: 1.55, color: MUTED }}>{body}</p>
    </div>
  )
}

function Workbench() {
  return (
    <section
      style={{
        padding: "80px 20px",
        background: CREAM_DARK,
        borderTop: `1px solid ${BORDER}`,
        borderBottom: `1px solid ${BORDER}`,
      }}
    >
      <div className="max-w-[1200px] mx-auto">
        <SectionHeader
          eyebrow="THE EDITOR"
          title="Edit the document, not a list of segments"
          subtitle="The translation is a real Word document next to the original. Type where something's wrong, or highlight it and ask the AI."
        />
        <ShowcaseRow
          image={<Shot maxHeight={560} src="/landing/assistant.webp" width={1400} height={1570} alt="Asking the AI to write a date in full; the edited line is highlighted" />}
          eyebrow="ASK AI"
          title="Fix a passage by asking"
          items={[
            { t: "Point at it", b: "Highlight the passage; the AI sees it, the original and the rest of the document." },
            { t: "Say what's off", b: "“Write the date in full”, “put the stamp beside the signature”, “use Registry Office”." },
            { t: "Only that part changes", b: "The rest of the document stays as it is. Undo is one click." },
          ]}
        />
        <ShowcaseRow
          reverse
          image={<Shot maxHeight={560} src="/landing/checks.webp" width={1100} height={1486} alt="Ready-to-certify checklist listing what to check before signing" />}
          eyebrow="READY TO CERTIFY"
          title="Checked before you sign"
          items={[
            { t: "Numbers, dates, codes and names", b: "Compared with the source. A missing digit is flagged before you sign, not after the client spots it." },
            { t: "Uncertain readings", b: "Faded stamps, handwriting and smudged digits are marked, with the spot highlighted on the original." },
            { t: "Untranslated text and the certification page", b: "Text that may have been left in the source language is listed, and so is a missing certification page." },
          ]}
        />
        <ShowcaseRow
          image={<Shot maxHeight={560} src="/landing/cert.webp" width={1100} height={1486} alt="Certification page fields: date, languages, translator and document" />}
          eyebrow="CERTIFICATION"
          title="Your certification page, built in"
          items={[
            { t: "Your template or ours", b: "Upload your Word certification with merge fields, or use the standard page. Pick it per project or at Certify & deliver." },
            { t: "Edit in place", b: "Change the date or languages without touching the rest of the page." },
            { t: "One file out", b: "The delivery PDF holds the translation, your certification page and a copy of the original." },
          ]}
        />
      </div>
    </section>
  )
}

function ShowcaseRow({
  image,
  eyebrow,
  title,
  items,
  reverse = false,
}: {
  image: React.ReactNode
  eyebrow: string
  title: string
  items: { t: string; b: string }[]
  reverse?: boolean
}) {
  return (
    <div className="grid md:grid-cols-2 gap-10 md:gap-12 items-center mt-16 md:mt-20">
      <div className={`min-w-0 ${reverse ? "md:order-2" : ""}`}>{image}</div>
      <div className="min-w-0">
        <div style={eyebrowStyle}>{eyebrow}</div>
        <h3 style={{ fontSize: H3_SIZE, lineHeight: 1.15, fontWeight: 700, color: TEXT, letterSpacing: "-0.02em", marginBottom: 22 }}>{title}</h3>
        <FeatureList items={items} />
      </div>
    </div>
  )
}

function GetPaid() {
  return (
    <section id="get-paid" style={{ padding: "80px 20px" }}>
      <div
        className="max-w-[1200px] mx-auto"
        style={{
          background: TEAL,
          color: "#ffffff",
          borderRadius: 32,
          padding: "clamp(28px, 5vw, 56px)",
          position: "relative",
          overflow: "hidden",
          boxShadow: "0 20px 50px rgba(10,120,112,0.20)",
        }}
      >
        <div
          aria-hidden="true"
          style={{
            position: "absolute",
            top: -120,
            left: -100,
            width: 340,
            height: 340,
            borderRadius: "50%",
            background: "rgba(255,255,255,0.06)",
            pointerEvents: "none",
          }}
        />
        <div className="relative grid lg:grid-cols-[1.1fr_1fr] gap-10 items-center">
          <div className="min-w-0">
            <div style={{ ...eyebrowStyle, color: "rgba(255,255,255,0.75)" }}>PROTECTED UNTIL PAID</div>
            <h2
              style={{
                fontSize: H2_SIZE,
                lineHeight: 1.12,
                fontWeight: 700,
                letterSpacing: "-0.02em",
                marginBottom: 16,
              }}
            >
              Get paid before you deliver
            </h2>
            <p style={{ fontSize: 16, lineHeight: 1.6, color: "rgba(255,255,255,0.88)", marginBottom: 24, maxWidth: 560 }}>
              No more chasing invoices after the file has gone out. Send a protected link:
              the client sees what they&apos;re paying for, but can&apos;t use it until they pay.
            </p>
            <ul className="space-y-4">
              {[
                {
                  t: "A preview they can't use",
                  b: "Every page is watermarked “PREVIEW – NOT VALID – UNPAID” and partly blurred.",
                },
                {
                  t: "They pay the way they like",
                  b: "Card, Apple Pay, Google Pay or PayPal through your own Stripe account, or by PayPal.me.",
                },
                {
                  t: "The file is released after payment",
                  b: "With Stripe, the download opens as soon as Stripe confirms. With PayPal.me, the client tells you they've paid and you release it.",
                },
                {
                  t: "The money goes to you",
                  b: "Payments land in your own Stripe or PayPal account, not ours. We never see or store card or bank details.",
                },
              ].map((it) => (
                <li key={it.t} className="flex items-start gap-3">
                  <span
                    aria-hidden="true"
                    style={{
                      width: 26,
                      height: 26,
                      borderRadius: 8,
                      background: "rgba(255,255,255,0.16)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      flexShrink: 0,
                    }}
                  >
                    <Check />
                  </span>
                  <div>
                    <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 2 }}>{it.t}</div>
                    <div style={{ fontSize: 14, lineHeight: 1.55, color: "rgba(255,255,255,0.82)" }}>{it.b}</div>
                  </div>
                </li>
              ))}
            </ul>
          </div>
          <ProtectedLinkClip />
        </div>
      </div>
    </section>
  )
}

function ProtectedLinkClip() {
  return (
    <figure className="min-w-0" style={{ margin: 0 }}>
      <DemoVideo
        src="/landing/demo-protected-link.webm"
        poster="/landing/demo-protected-link.png"
        label="Demo: the client's page for a protected link, with a watermarked, partly blurred preview and a Pay button"
      />
      <figcaption style={{ fontSize: 12, color: "rgba(255,255,255,0.8)", marginTop: 10, textAlign: "center" }}>
        The client&apos;s page for a protected link. Sample data; you set the amount on each link.
      </figcaption>
    </figure>
  )
}

const OUTCOMES: { problem: string; outcome: string; detail: string }[] = [
  {
    problem: "Rebuilding the layout by hand takes most of the job",
    outcome: "The layout comes back rebuilt",
    detail: "Tables, forms and signature blocks sit where they were on the original, in an editable Word document.",
  },
  {
    problem: "Stamps and seals you can barely read",
    outcome: "Each one is marked in brackets",
    detail: "[Stamp: …] and [Signature] where they appear; an unreadable word or digit is marked [illegible], never guessed.",
  },
  {
    problem: "One wrong digit can get a document rejected",
    outcome: "Numbers are checked before you sign",
    detail: "Numbers, dates, codes and names are compared with the original, and anything that differs is listed.",
  },
  {
    problem: "Checking means flipping between two files",
    outcome: "Click a line, see its source",
    detail: "Every translated line is linked to its place on the original and highlighted there when you click it.",
  },
  {
    problem: "Chasing clients for payment",
    outcome: "The file is released when they pay",
    detail: "Send a protected link: the client sees a watermarked preview, and with Stripe the download opens once they've paid.",
  },
  {
    problem: "The same documents, again and again",
    outcome: "Your past work is reused",
    detail: "Templates start the next certificate of the same type from your version; memory and glossary carry your terms.",
  },
]

function WhyBuy() {
  return (
    <section
      id="why"
      style={{
        padding: "80px 20px",
        background: CREAM_DARK,
        borderBottom: `1px solid ${BORDER}`,
      }}
    >
      <div className="max-w-[1100px] mx-auto">
        <SectionHeader
          eyebrow="WHY TRANSLATORS BUY"
          title="Less retyping, fewer rejected documents, paid on time"
          subtitle="Certified work has the same slow parts on every job. These are the ones it takes off your hands."
        />
        <ul className="grid md:grid-cols-2 gap-4 mt-12">
          {OUTCOMES.map((o) => (
            <li
              key={o.problem}
              style={{
                background: "#ffffff",
                border: `1px solid ${BORDER}`,
                borderRadius: 18,
                padding: "20px 22px",
              }}
            >
              <div className="flex items-start gap-2" style={{ fontSize: 14, color: MUTED, marginBottom: 8 }}>
                <span aria-hidden="true" style={{ color: ACCENT_RUST, fontWeight: 700, flexShrink: 0 }}>
                  ✕
                </span>
                <span>
                  <span className="sr-only">Problem: </span>
                  {o.problem}
                </span>
              </div>
              <div className="flex items-start gap-2">
                <span style={{ color: TEAL, flexShrink: 0, marginTop: 4 }}>
                  <Check />
                </span>
                <div>
                  <h3 style={{ fontSize: 17, fontWeight: 700, color: TEXT, lineHeight: 1.3 }}>
                    <span className="sr-only">Outcome: </span>
                    {o.outcome}
                  </h3>
                  <p style={{ fontSize: 14, lineHeight: 1.55, color: MUTED, marginTop: 4 }}>{o.detail}</p>
                </div>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}

type Demo = {
  id: string
  step: string
  title: string
  line: string
  note: string
  src: string
  poster: string
  label: string
}

const DEMOS: Demo[] = [
  {
    id: "upload",
    step: "Upload",
    title: "Drop in the client's scan",
    line: "It reads each page, translates the text and rebuilds the layout, with the stage shown as it goes.",
    note: "Sample data; processing sped up",
    src: "/landing/demo-upload.webm",
    poster: "/landing/demo-upload.png",
    label: "Demo: a PDF is dropped on the New project page; the progress shows Reading page 2 of 3, Translating the text and Rebuilding the layout, then the editor opens",
  },
  {
    id: "editor",
    step: "Review",
    title: "Click a line, see its source",
    line: "Click any translated line and the same line lights up on the original.",
    note: "Recorded in the live app",
    src: "/landing/demo-editor.webm",
    poster: "/landing/demo-editor.png",
    label: "Demo: clicking translated lines in the editor highlights each one on the original certificate",
  },
  {
    id: "checks",
    step: "Check",
    title: "Checked before you sign",
    line: "An illegible digit, a reformatted number and a faded stamp are listed, each highlighted on the original.",
    note: "Recorded in the live app",
    src: "/landing/demo-checks.webm",
    poster: "/landing/demo-checks.png",
    label: "Demo: the Ready to certify panel opens with one item to check and two notes; picking each one highlights it on the original",
  },
  {
    id: "certify",
    step: "Certify",
    title: "Your certification page, in the document",
    line: "Open the certification page fields and change the date or languages in place.",
    note: "Recorded in the live app",
    src: "/landing/demo-certification.webm",
    poster: "/landing/demo-certification.png",
    label: "Demo: the Certification panel opens over the certification page and the date is changed",
  },
  {
    id: "paid",
    step: "Get paid",
    title: "Paid before they download",
    line: "The client sees a watermarked, partly blurred preview and a Pay button for the amount you set.",
    note: "Sample data",
    src: "/landing/demo-protected-link.webm",
    poster: "/landing/demo-protected-link.png",
    label: "Demo: a client's protected link page with a Pay €45 button and a watermarked, blurred preview of the translation",
  },
]

function SeeItWork() {
  const [active, setActive] = useState(0)
  const demo = DEMOS[active]
  const onKey = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const step = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0
    if (!step) return
    e.preventDefault()
    const next = (active + step + DEMOS.length) % DEMOS.length
    setActive(next)
    document.getElementById(`demo-tab-${DEMOS[next].id}`)?.focus()
  }
  return (
    <section id="demo" style={{ padding: "80px 20px" }}>
      <div className="max-w-[1200px] mx-auto">
        <SectionHeader
          eyebrow="SEE IT WORK"
          title="From scan to paid delivery, in five short clips"
          subtitle="Recorded in OnlineDocTranslator on a sample residence certificate from a fictional town."
        />
        <div className="grid lg:grid-cols-[300px_minmax(0,1fr)] gap-6 lg:gap-8 mt-12 items-start">
          <div
            role="tablist"
            aria-label="Product demos"
            aria-orientation="vertical"
            onKeyDown={onKey}
            className="flex flex-wrap lg:flex-col gap-2"
          >
            {DEMOS.map((d, i) => {
              const selected = i === active
              return (
                <button
                  key={d.id}
                  id={`demo-tab-${d.id}`}
                  type="button"
                  role="tab"
                  aria-selected={selected}
                  aria-controls="demo-panel"
                  tabIndex={selected ? 0 : -1}
                  onClick={() => setActive(i)}
                  className="text-left flex items-center gap-3"
                  style={{
                    background: selected ? "#ffffff" : "transparent",
                    border: `1px solid ${selected ? TEAL : BORDER}`,
                    borderRadius: 14,
                    padding: "10px 14px",
                    cursor: "pointer",
                    boxShadow: selected ? "0 8px 20px rgba(10,120,112,0.10)" : "none",
                  }}
                >
                  <span
                    aria-hidden="true"
                    style={{
                      width: 26,
                      height: 26,
                      borderRadius: 999,
                      background: selected ? TEAL : CREAM_DARK,
                      color: selected ? "#ffffff" : MUTED,
                      fontSize: 12,
                      fontWeight: 700,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      flexShrink: 0,
                    }}
                  >
                    {i + 1}
                  </span>
                  <span className="min-w-0">
                    <span style={{ display: "block", fontSize: 14, fontWeight: 600, color: TEXT }}>{d.step}</span>
                    <span className="hidden lg:block" style={{ fontSize: 12, color: MUTED, lineHeight: 1.4 }}>
                      {d.title}
                    </span>
                  </span>
                </button>
              )
            })}
          </div>
          <div id="demo-panel" role="tabpanel" aria-labelledby={`demo-tab-${demo.id}`} className="min-w-0">
            <DemoVideo
              key={demo.id}
              src={demo.src}
              poster={demo.poster}
              label={demo.label}
              loop={false}
              onEnded={() => setActive((i) => (i + 1) % DEMOS.length)}
            />
            <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1" style={{ marginTop: 14 }}>
              <h3 style={{ fontSize: 18, fontWeight: 700, color: TEXT }}>{demo.title}</h3>
              <span style={{ fontSize: 12, color: SUBTLE }}>{demo.note}</span>
            </div>
            <p style={{ fontSize: 15, lineHeight: 1.55, color: MUTED, marginTop: 4 }}>{demo.line}</p>
          </div>
        </div>
        <DemoCTA />
      </div>
    </section>
  )
}

function DemoCTA() {
  const catalog = usePlans()
  const trial = catalog ? `${pagesLabel(catalog.trial.credits)} free for ${catalog.trial.days} days, no card required.` : "Free trial, no card required."
  return (
    <div
      className="mt-14 flex flex-wrap items-center justify-between gap-5"
      style={{
        background: TEAL,
        color: "#ffffff",
        borderRadius: 24,
        padding: "clamp(22px, 4vw, 32px) clamp(22px, 4vw, 36px)",
      }}
    >
      <div className="min-w-0">
        <h3 style={{ fontSize: "clamp(20px, 3vw, 24px)", fontWeight: 700, letterSpacing: "-0.01em" }}>
          Try it on one of your own documents
        </h3>
        <p style={{ fontSize: 15, color: "rgba(255,255,255,0.85)", marginTop: 4 }}>{trial}</p>
      </div>
      <div className="flex flex-wrap gap-3">
        <Link
          href="/register"
          style={{ background: "#ffffff", color: TEAL_DARK, padding: "13px 24px", borderRadius: 999, fontWeight: 700, fontSize: 15 }}
        >
          Start free trial <span aria-hidden="true">→</span>
        </Link>
        <a
          href="#pricing"
          style={{ color: "#ffffff", padding: "13px 22px", borderRadius: 999, fontWeight: 600, fontSize: 15, border: "1px solid rgba(255,255,255,0.45)" }}
        >
          See pricing
        </a>
      </div>
    </div>
  )
}

function ValueStrip() {
  const catalog = usePlans()
  const plans = catalog?.plans ?? []
  const byPerPage = [...plans].sort((a, b) => a.price_per_page_eur - b.price_per_page_eur)
  const cheapest = byPerPage[0]
  const dearest = byPerPage[byPerPage.length - 1]
  const items: { n: string; l: string; d: string }[] = [
    {
      n: "~12 min",
      l: "for a 10-page PDF",
      d: "From upload to a rebuilt draft, in a production run on 6 October 2026. Typical, not guaranteed: scans usually take 1–2 minutes a page.",
    },
    {
      n: "1 page = 1 credit",
      l: "with 5 AI edits included",
      d: "Each translated page uses one credit and comes with 5 Ask AI edits on that document.",
    },
  ]
  if (cheapest && dearest) {
    items.push({
      n: `${euro(cheapest.price_per_page_eur)} a page`,
      l: `on ${cheapest.name}`,
      d: `Subscription pages cost ${euro(cheapest.price_per_page_eur)} to ${euro(dearest.price_per_page_eur)} each, depending on the plan. No VAT is added.`,
    })
  }
  if (catalog) {
    items.push({
      n: `${pagesLabel(catalog.trial.credits)} free`,
      l: `for ${catalog.trial.days} days`,
      d: "Try it on a real document before you pay. No card required.",
    })
  }
  return (
    <section
      aria-labelledby="value-title"
      style={{
        padding: "56px 20px",
        background: CREAM_DARK,
        borderTop: `1px solid ${BORDER}`,
        borderBottom: `1px solid ${BORDER}`,
      }}
    >
      <div className="max-w-[1200px] mx-auto">
        <h2 id="value-title" className="text-center" style={{ fontSize: H3_SIZE, fontWeight: 700, letterSpacing: "-0.02em", color: TEXT }}>
          What a document takes, in time and money
        </h2>
        <dl className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4 mt-8">
          {items.map((it) => (
            <div
              key={it.n}
              className="min-w-0 flex flex-col"
              style={{ background: "#ffffff", border: `1px solid ${BORDER}`, borderRadius: 18, padding: 20 }}
            >
              <dt style={{ fontSize: 13, fontWeight: 600, color: TEXT, order: 2 }}>{it.l}</dt>
              <dd style={{ order: 1, fontSize: "clamp(24px, 3vw, 30px)", fontWeight: 700, color: TEAL, letterSpacing: "-0.02em", lineHeight: 1.1 }}>
                {it.n}
              </dd>
              <dd style={{ order: 3, fontSize: 13, lineHeight: 1.5, color: MUTED, marginTop: 6 }}>{it.d}</dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  )
}

// Cheapest set of top-up packs that covers `need` pages; packs can repeat.
function cheapestTopUp(need: number, packs: { credits: number; price_cents: number }[]) {
  if (need <= 0 || !packs.length) return { cents: 0, counts: new Map<number, number>() }
  const limit = need + Math.max(...packs.map((p) => p.credits))
  const cost: number[] = new Array(limit + 1).fill(Infinity)
  const pick: number[] = new Array(limit + 1).fill(-1)
  cost[0] = 0
  for (let c = 1; c <= limit; c++) {
    packs.forEach((p, i) => {
      if (p.credits <= c && cost[c - p.credits] + p.price_cents < cost[c]) {
        cost[c] = cost[c - p.credits] + p.price_cents
        pick[c] = i
      }
    })
  }
  let best = need
  for (let c = need; c <= limit; c++) if (cost[c] < cost[best]) best = c
  const counts = new Map<number, number>()
  for (let c = best; c > 0 && pick[c] >= 0; c -= packs[pick[c]].credits) {
    const credits = packs[pick[c]].credits
    counts.set(credits, (counts.get(credits) ?? 0) + 1)
  }
  return { cents: cost[best], counts }
}

function PlanFinder({ catalog }: { catalog: PlanCatalog }) {
  const [pages, setPages] = useState(30)
  const [needCert, setNeedCert] = useState(true)
  const packs = catalog.credit_packs.filter((p) => p.available)
  const rows = catalog.plans
    .filter((p) => p.available && (!needCert || p.features.certifications))
    .map((plan) => {
      const top = cheapestTopUp(pages - plan.credits, packs)
      const total = plan.price_eur + top.cents / 100
      const extra = [...top.counts.entries()].map(([credits, n]) => `${n} × ${credits}-page pack`).join(" + ")
      return { plan, total, extra }
    })
  const best = rows.reduce<(typeof rows)[number] | null>((b, r) => (!b || r.total < b.total ? r : b), null)
  const money = (n: number) => `€${n.toFixed(2)}`
  return (
    <div
      className="mt-12"
      style={{ background: "#ffffff", border: `1px solid ${BORDER}`, borderRadius: 22, padding: "clamp(20px, 4vw, 30px)" }}
    >
      <h3 style={{ fontSize: 20, fontWeight: 700, color: TEXT }}>Which plan fits your month?</h3>
      <p style={{ fontSize: 14, color: MUTED, marginTop: 4 }}>
        Move the slider to your usual number of pages. Pages beyond a plan&apos;s allowance are priced with extra page packs.
      </p>
      <div className="grid md:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] gap-6 md:gap-10 mt-6 items-start">
        <div className="min-w-0">
          <label htmlFor="pages-per-month" style={{ fontSize: 13, fontWeight: 600, color: TEXT }}>
            Pages a month: <output htmlFor="pages-per-month" style={{ color: TEAL, fontSize: 18 }}>{pages}</output>
          </label>
          <input
            id="pages-per-month"
            type="range"
            min={1}
            max={600}
            step={1}
            value={pages}
            onChange={(e) => setPages(Number(e.target.value))}
            className="w-full mt-3"
            style={{ accentColor: TEAL }}
          />
          <div className="flex justify-between" style={{ fontSize: 11, color: SUBTLE }}>
            <span>1</span>
            <span>600</span>
          </div>
          <label className="flex items-start gap-2 mt-4" style={{ fontSize: 13, color: TEXT, cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={needCert}
              onChange={(e) => setNeedCert(e.target.checked)}
              style={{ accentColor: TEAL, marginTop: 3 }}
            />
            <span>I need the certification page, translation memory and glossary</span>
          </label>
          {best && (
            <div style={{ marginTop: 18, background: TEAL_SOFT, borderRadius: 16, padding: "14px 16px" }} aria-live="polite">
              <div style={{ fontSize: 12, fontWeight: 600, letterSpacing: "0.08em", color: TEAL_DARK }}>BEST FIT</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: TEXT, marginTop: 2 }}>
                {best.plan.name}: {money(best.total)} a month
              </div>
              <div style={{ fontSize: 14, color: TEAL_DARK, marginTop: 2 }}>
                {money(best.total / pages)} a page at {pages} pages
                {best.extra ? `, with ${best.extra}` : ""}
              </div>
            </div>
          )}
        </div>
        <table className="w-full" style={{ fontSize: 14, borderCollapse: "collapse" }}>
          <caption className="sr-only">Monthly cost of each plan at {pages} pages</caption>
          <thead>
            <tr style={{ fontSize: 11, letterSpacing: "0.1em", color: SUBTLE, textAlign: "left" }}>
              <th scope="col" style={{ padding: "6px 0", fontWeight: 600 }}>PLAN</th>
              <th scope="col" style={{ padding: "6px 0", fontWeight: 600, textAlign: "right" }}>A MONTH</th>
              <th scope="col" style={{ padding: "6px 0", fontWeight: 600, textAlign: "right" }}>A PAGE</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const isBest = r === best
              return (
                <tr key={r.plan.code} style={{ borderTop: `1px solid ${CREAM_DARK}`, color: isBest ? TEAL_DARK : TEXT, fontWeight: isBest ? 700 : 400 }}>
                  <th scope="row" style={{ padding: "10px 0", textAlign: "left", fontWeight: isBest ? 700 : 500 }}>
                    {r.plan.name}
                    <span style={{ display: "block", fontSize: 12, fontWeight: 400, color: MUTED }}>
                      {r.plan.credits} pages{r.extra ? ` + ${r.extra}` : ""}
                    </span>
                  </th>
                  <td style={{ padding: "10px 0", textAlign: "right" }}>{money(r.total)}</td>
                  <td style={{ padding: "10px 0", textAlign: "right" }}>{money(r.total / pages)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p style={{ fontSize: 12, color: SUBTLE, marginTop: 14 }}>
        Prices from the current plan list, in EUR. No VAT is added. Extra page packs are sold to subscribers and don&apos;t expire, so
        unused pack pages carry over.
      </p>
    </div>
  )
}

function RiskReversal() {
  const catalog = usePlans()
  const trialTitle = catalog ? `${pagesLabel(catalog.trial.credits)} free, no card` : "Free trial, no card"
  const trialBody = catalog
    ? `Sign up and translate ${pagesLabel(catalog.trial.credits)} within ${catalog.trial.days} days with the full editor. We don't ask for card details.`
    : "Sign up and translate a few pages with the full editor. We don't ask for card details."
  const points: { icon: React.ReactNode; title: string; body: React.ReactNode }[] = [
    { icon: <IconCard />, title: trialTitle, body: trialBody },
    {
      icon: <IconBolt />,
      title: "Cancel anytime",
      body: "Change plan, download invoices or cancel from the billing portal, linked from Billing in your account.",
    },
    {
      icon: <IconLock />,
      title: "Your documents stay private",
      body: (
        <>
          Stored in the EU, encrypted at rest and not used to train AI models.{" "}
          <a href="#security" style={{ color: TEAL, fontWeight: 600 }}>
            How documents are handled
          </a>
        </>
      ),
    },
  ]
  return (
    <section aria-labelledby="risk-title" style={{ padding: "72px 20px 24px" }}>
      <div className="max-w-[1100px] mx-auto">
        <h2 id="risk-title" className="text-center" style={{ fontSize: H2_SIZE, fontWeight: 700, letterSpacing: "-0.02em", color: TEXT, lineHeight: 1.15 }}>
          Try it before you pay anything
        </h2>
        <ul className="grid md:grid-cols-3 gap-5 mt-10">
          {points.map((p) => (
            <li key={p.title} style={{ background: "#ffffff", border: `1px solid ${BORDER}`, borderRadius: 20, padding: 24 }}>
              <IconTile>{p.icon}</IconTile>
              <h3 style={{ fontSize: 17, fontWeight: 700, color: TEXT, marginTop: 14 }}>{p.title}</h3>
              <p style={{ fontSize: 14, lineHeight: 1.55, color: MUTED, marginTop: 6 }}>{p.body}</p>
            </li>
          ))}
        </ul>
        <div className="flex flex-wrap items-center justify-center gap-3 mt-10">
          <Link
            href="/register"
            style={{ background: TEAL, color: "#ffffff", padding: "14px 28px", borderRadius: 999, fontWeight: 700, fontSize: 15 }}
          >
            Start free trial <span aria-hidden="true">→</span>
          </Link>
          <a
            href="#demo"
            style={{ background: "#ffffff", color: TEXT, padding: "14px 26px", borderRadius: 999, fontWeight: 600, fontSize: 15, border: `1px solid ${BORDER}` }}
          >
            Watch the demo
          </a>
        </div>
      </div>
    </section>
  )
}

const SECURITY_POINTS: { icon: React.ReactNode; title: string; body: string }[] = [
  {
    icon: <IconGlobe />,
    title: "Stored in the EU",
    body: "Your documents and data are stored in the EU (Ireland), in the database and file storage behind your account.",
  },
  {
    icon: <IconLock />,
    title: "Encrypted in transit and at rest",
    body: "Every connection runs over HTTPS, and stored files are encrypted at rest.",
  },
  {
    icon: <IconNoTrain />,
    title: "Not used to train AI models",
    body: "Documents are processed only to deliver your translation. They're not used to train AI models.",
  },
  {
    icon: <IconCard />,
    title: "No client data for payments",
    body: "Clients pay on Stripe or PayPal. We never see or store their card or bank details.",
  },
  {
    icon: <IconLink />,
    title: "Private, expiring links",
    body: "Client links expire after 1, 7 or 30 days and can be revoked at any time. Only a hash of each link is stored.",
  },
  {
    icon: <IconUsers />,
    title: "Team access control",
    body: "Projects belong to your team, and roles (admin, PM, reviewer, member) decide who can do what.",
  },
  {
    icon: <IconShield />,
    title: "Tamper-evident certifications",
    body: "Every file in your Certifications library is stored with its SHA-256 hash, so any later change to it shows.",
  },
  {
    icon: <IconTrash />,
    title: "Delete whenever you want",
    body: "Delete a project and its files, text and memory entries go with it. You can delete your whole account from Settings.",
  },
]

function Security() {
  return (
    <section id="security" style={{ padding: "80px 20px" }}>
      <div className="max-w-[1200px] mx-auto">
        <SectionHeader
          eyebrow="SECURITY & PRIVACY"
          title="Your clients' documents stay private"
          subtitle="Certified work means passports, birth certificates and medical records. Here is how they're handled."
        />
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-5 mt-12">
          {SECURITY_POINTS.map((p) => (
            <FeatureCard key={p.title} icon={p.icon} title={p.title} body={p.body} />
          ))}
        </div>
        <p
          className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 mt-8 text-center"
          style={{ fontSize: 14, color: MUTED }}
        >
          <span style={{ color: TEAL, fontWeight: 600 }}>GDPR-ready:</span>
          <span>EU data storage, your data deleted when you delete it, and a data processing agreement (DPA) on request.</span>
        </p>
      </div>
    </section>
  )
}

function FeatureList({
  items,
}: {
  items: { t: string; b: string }[]
}) {
  return (
    <ul className="space-y-5">
      {items.map((it) => (
        <li key={it.t} className="flex items-start gap-4">
          <div
            aria-hidden="true"
            style={{
              width: 28,
              height: 28,
              borderRadius: 8,
              background: TEAL_SOFT,
              color: TEAL,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
            }}
          >
            <Check />
          </div>
          <div className="min-w-0">
            <div style={{ fontSize: 16, fontWeight: 600, color: TEXT, marginBottom: 4 }}>
              {it.t}
            </div>
            <div style={{ fontSize: 14, lineHeight: 1.55, color: MUTED }}>
              {it.b}
            </div>
          </div>
        </li>
      ))}
    </ul>
  )
}

function Pricing() {
  const catalog = usePlans()
  return (
    <section
      id="pricing"
      style={{
        padding: "80px 20px",
        background: CREAM_DARK,
        borderTop: `1px solid ${BORDER}`,
        borderBottom: `1px solid ${BORDER}`,
      }}
    >
      <div className="max-w-[1200px] mx-auto">
        <SectionHeader
          eyebrow="PRICING"
          title="Simple plans. Pay for the pages you translate."
          subtitle="One credit translates one page. Subscriptions refill monthly, extra page packs top you up, and you can cancel anytime. No setup fees."
        />

        {catalog === undefined ? (
          <div
            className="grid sm:grid-cols-2 lg:grid-cols-4 gap-5 mt-12"
            aria-busy="true"
            aria-label="Loading plans"
          >
            {[0, 1, 2, 3].map((i) => (
              <div
                key={i}
                style={{
                  background: "#ffffff",
                  border: `1px solid ${BORDER}`,
                  borderRadius: 22,
                  height: 420,
                  opacity: 0.6,
                }}
              />
            ))}
          </div>
        ) : catalog === null ? (
          <div
            className="mt-12 text-center"
            style={{ fontSize: 15, color: MUTED }}
          >
            Plans couldn&apos;t load right now.{" "}
            <Link href="/register" style={{ color: TEAL, fontWeight: 600 }}>
              Start the free trial
            </Link>{" "}
            and see them in Billing.
          </div>
        ) : (
          <PricingPlans catalog={catalog} />
        )}
      </div>
    </section>
  )
}

function PricingPlans({ catalog }: { catalog: PlanCatalog }) {
  const trial = catalog.trial
  return (
    <>
      <div
        className="mt-12 flex flex-wrap items-center justify-between gap-4"
        style={{
          background: "#ffffff",
          border: `1px solid ${BORDER}`,
          borderRadius: 22,
          padding: "22px clamp(20px, 4vw, 28px)",
        }}
      >
        <div style={{ minWidth: 0 }}>
          <div
            style={{
              fontSize: 13,
              letterSpacing: "0.12em",
              fontWeight: 600,
              color: SUBTLE,
              marginBottom: 6,
            }}
          >
            FREE TRIAL
          </div>
          <div style={{ fontSize: 20, fontWeight: 700, color: TEXT }}>
            {pagesLabel(trial.credits)} free for {trial.days} days
          </div>
          <div style={{ fontSize: 14, color: MUTED, marginTop: 4 }}>
            Layout-preserving translation and the full editor. Preview only:
            downloads and client links need a paid plan. No card required.
          </div>
        </div>
        <Link
          href="/register"
          style={{
            background: TEAL,
            color: "#ffffff",
            padding: "12px 22px",
            borderRadius: 999,
            fontWeight: 600,
            fontSize: 14,
            whiteSpace: "nowrap",
          }}
        >
          Start free
        </Link>
      </div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-5 mt-8">
        {catalog.plans.map((p) => (
          <PlanCard key={p.code} plan={p} catalog={catalog} highlight={p.code === "PRO"} />
        ))}
      </div>

      <PlanFinder catalog={catalog} />

      <div className="mt-12">
        <div
          className="text-center"
          style={{
            fontSize: 11,
            letterSpacing: "0.18em",
            color: SUBTLE,
            fontWeight: 600,
            marginBottom: 6,
          }}
        >
          NEED MORE? TOP UP YOUR PLAN
        </div>
        <h3
          style={{
            fontSize: 22,
            fontWeight: 600,
            textAlign: "center",
            color: TEXT,
            marginBottom: 6,
          }}
        >
          Extra page packs that never expire
        </h3>
        <p className="text-center" style={{ fontSize: 14, color: MUTED, marginBottom: 24 }}>
          For subscribers: add pages to any active plan. Bigger packs cost less per page.
        </p>
        <div className="grid md:grid-cols-3 gap-4 max-w-[860px] mx-auto">
          {catalog.credit_packs.map((pack, i) => {
            const featured = i === 1
            return (
              <div
                key={pack.credits}
                style={{
                  background: "#ffffff",
                  border: `1px solid ${featured ? TEAL : BORDER}`,
                  borderRadius: 16,
                  padding: 22,
                  textAlign: "center",
                  position: "relative",
                  boxShadow: featured
                    ? "0 8px 20px rgba(10,120,112,0.10)"
                    : "0 1px 2px rgba(30,30,20,0.03)",
                }}
              >
                {pack.save_percent > 0 && (
                  <div
                    style={{
                      position: "absolute",
                      top: -11,
                      left: "50%",
                      transform: "translateX(-50%)",
                      background: TEAL,
                      color: "#fff",
                      fontSize: 10,
                      fontWeight: 700,
                      padding: "4px 12px",
                      borderRadius: 999,
                      letterSpacing: "0.1em",
                      whiteSpace: "nowrap",
                    }}
                  >
                    SAVE {pack.save_percent}%
                  </div>
                )}
                <div
                  style={{
                    fontSize: 11,
                    letterSpacing: "0.14em",
                    color: SUBTLE,
                    fontWeight: 600,
                    marginBottom: 10,
                  }}
                >
                  {pack.name.toUpperCase()}
                </div>
                <div className="flex items-baseline justify-center gap-1">
                  <span
                    style={{
                      fontSize: 30,
                      fontWeight: 700,
                      color: TEXT,
                      letterSpacing: "-0.02em",
                    }}
                  >
                    {pack.credits}
                  </span>
                  <span style={{ fontSize: 13, color: MUTED, marginLeft: 4 }}>
                    credits
                  </span>
                </div>
                <div
                  style={{
                    fontSize: 12,
                    color: MUTED,
                    marginTop: 4,
                    marginBottom: 14,
                  }}
                >
                  {pack.note}
                </div>
                <div
                  style={{
                    fontSize: 22,
                    fontWeight: 700,
                    color: featured ? TEAL : TEXT,
                  }}
                >
                  {euroCents(pack.price_cents)}
                </div>
                <div style={{ fontSize: 13, color: MUTED, marginTop: 2 }}>{packPerPage(pack)}</div>              </div>
            )
          })}
        </div>
        <p
          className="max-w-[860px] mx-auto text-center"
          style={{ fontSize: 12, color: SUBTLE, marginTop: 18, lineHeight: 1.5 }}
        >
          {VAT_NOTE}
        </p>
        <p
          className="max-w-[860px] mx-auto text-center"
          style={{ fontSize: 13, color: MUTED, marginTop: 10, lineHeight: 1.5 }}
        >
          Change plan, download invoices or cancel anytime in the billing portal.
        </p>
      </div>
    </>
  )
}

function PlanCard({
  plan,
  catalog,
  highlight,
}: {
  plan: Plan
  catalog: PlanCatalog
  highlight: boolean
}) {
  const features = planBullets(catalog, plan)
  const ctaHref = plan.available
    ? `/register?plan=${plan.code.toLowerCase()}`
    : contactHref(catalog, plan)
  const cta = plan.available ? `Choose ${plan.name}` : "Contact us"
  return (
    <div
      style={{
        background: highlight ? "#0a7870" : "#ffffff",
        color: highlight ? "#ffffff" : TEXT,
        border: `1px solid ${highlight ? TEAL_DARK : BORDER}`,
        borderRadius: 22,
        padding: 28,
        position: "relative",
        boxShadow: highlight ? "0 14px 36px rgba(10,120,112,0.20)" : "0 2px 6px rgba(30,30,20,0.04)",
      }}
    >
      {highlight && (
        <div
          style={{
            position: "absolute",
            top: -12,
            left: "50%",
            transform: "translateX(-50%)",
            background: ACCENT_GOLD,
            color: "#fff",
            fontSize: 10,
            fontWeight: 700,
            padding: "5px 14px",
            borderRadius: 999,
            letterSpacing: "0.1em",
          }}
        >
          MOST POPULAR
        </div>
      )}
      <h3
        style={{
          fontSize: 13,
          letterSpacing: "0.12em",
          fontWeight: 600,
          marginBottom: 14,
          color: highlight ? "rgba(255,255,255,0.7)" : SUBTLE,
        }}
      >
        {plan.name.toUpperCase()}
      </h3>
      <div className="flex items-baseline gap-1">
        <span style={{ fontSize: 16, fontWeight: 500, opacity: 0.7 }}>€</span>
        <span style={{ fontSize: 44, fontWeight: 700, letterSpacing: "-0.02em" }}>
          {plan.price_eur}
        </span>
        <span
          style={{
            fontSize: 13,
            color: highlight ? "rgba(255,255,255,0.7)" : MUTED,
            marginLeft: 4,
          }}
        >
          /month
        </span>
      </div>
      <div
        style={{
          fontSize: 14,
          color: highlight ? "rgba(255,255,255,0.85)" : MUTED,
          marginTop: 4,
          marginBottom: 22,
        }}
      >
        {plan.credits} pages / month · {euro(plan.price_per_page_eur)} a page
      </div>
      <a
        href={ctaHref}
        style={{
          display: "block",
          textAlign: "center",
          background: highlight ? "#ffffff" : TEAL,
          color: highlight ? TEAL_DARK : "#ffffff",
          padding: "12px 18px",
          borderRadius: 999,
          fontWeight: 600,
          fontSize: 14,
          marginBottom: 26,
        }}
      >
        {cta}
      </a>
      <div className="space-y-3">
        {features.map((f) => (
          <div
            key={f}
            className="flex items-start gap-2"
            style={{ fontSize: 13, color: highlight ? "rgba(255,255,255,0.92)" : TEXT }}
          >
            <span style={{ flexShrink: 0, marginTop: 2 }}>
              <Check />
            </span>
            <span>{f}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function FAQ() {
  const [open, setOpen] = useState<number | null>(0)
  const catalog = usePlans()
  const trialAnswer = catalog
    ? `Sign up and you get ${pagesLabel(catalog.trial.credits)} to translate within ${catalog.trial.days} days, with the full editor. No credit card is needed. The trial is for trying the translation and the editor: downloads and client links need a paid plan, and the certification page needs Pro or above.`
    : "Sign up and you get a few free pages with the full editor. No credit card is needed. The trial is for trying the translation and the editor: downloads and client links need a paid plan, and the certification page needs Pro or above."
  const pricingAnswer = catalog
    ? `Each page is one credit. Subscriptions include a monthly allowance (${catalog.plans
        .map((p) => `${p.credits} on ${p.name}`)
        .join(", ")}) that resets each billing period. Subscribers can add credit packs of ${catalog.credit_packs
        .map((c) => c.credits)
        .join(", ")} credits, which don't expire.`
    : "Each page is one credit. Subscriptions include a monthly allowance that resets each billing period, and subscribers can add credit packs that don't expire. The plans are listed above."
  const items = [
    {
      q: "Is the AI translation good enough to certify?",
      a: "It's a strong first draft, not a finished certified translation. You review it next to the original, correct it and sign it: you stay the certifying translator, and OnlineDocTranslator never certifies anything itself. The ready-to-certify check helps you catch what's easy to miss, such as a number that differs from the original, an unreadable stamp or text left untranslated. On Pro and above, your certification page goes into the export. Whether a translation is accepted still depends on your credentials and the receiving authority's rules.",
    },
    {
      q: "How does the free trial work?",
      a: trialAnswer,
    },
    {
      q: "How does pricing work?",
      a: pricingAnswer,
    },
    {
      q: "Do prices include VAT?",
      a: "No VAT is added to our prices. All prices are in EUR, and the price you see is the price you pay.",
    },
    {
      q: "Can I cancel anytime?",
      a: "Yes. Change plan, update your card, download invoices or cancel from the billing portal, linked from Billing in your account.",
    },
    {
      q: "How do my clients pay me?",
      a: "Connect your own Stripe account in Settings → Payments and clients can pay by card, Apple Pay, Google Pay or PayPal (the methods you turn on in Stripe); the download is released as soon as Stripe confirms the payment. You can also add your PayPal.me name: the client pays you there and you release the link. The money goes to your account, and Stripe's usual fees apply.",
    },
    {
      q: "How are signatures, stamps and unreadable parts handled?",
      a: "They are never copied as images. Each is noted where it appears, in the target language: [Signature], [Stamp: Municipality of Rome – Registry Office]. Anything unreadable is marked [illegible] on exactly that word or number; names, dates and figures are never guessed.",
    },
    {
      q: "What files and languages do you support?",
      a: "PDF (single or multi-page, including scans), JPG, PNG and DOCX, up to 20 MB each. 28 languages, including Arabic, Hebrew, Chinese (Simplified and Traditional), Japanese and Korean; auto-detect can pick the source language. Exports are DOCX and PDF.",
    },
    {
      q: "What does a page credit include?",
      a: "Translating one page, plus 5 AI edits per page with Ask AI. After that, 1 credit adds 5 more edits. The first Regenerate of a document is free; a second one costs one credit per page.",
    },
    {
      q: "Does it really learn from my work?",
      a: "Yes. The text you approve and deliver goes into your translation memory, and the terms you correct go into your glossary; you can edit or remove any of them, and import or export the memory as TMX. Finished documents become templates, so the next document of the same type from the same country starts from your version.",
    },
    {
      q: "What happens to my files?",
      a: "They're stored in the EU (Ireland), encrypted at rest, and not used to train AI models. Projects stay in your account until you delete them; deleting a project removes its files, text and translation memory entries. A data processing agreement (DPA) is available on request.",
    },
    {
      q: "Can my team work together?",
      a: "Paid plans include team members with roles (admin, PM, reviewer, member) and project assignment with email notifications; each plan's team size is listed under Pricing. Pro and above add a shared translation memory and glossary.",
    },
  ]
  return (
    <section id="faq" style={{ padding: "80px 20px" }}>
      <div className="max-w-[820px] mx-auto">
        <SectionHeader
          eyebrow="QUESTIONS"
          title="Questions translators ask"
        />
        <div className="space-y-3 mt-12">
          {items.map((it, i) => {
            const isOpen = open === i
            return (
              <div
                key={it.q}
                style={{
                  background: "#ffffff",
                  border: `1px solid ${BORDER}`,
                  borderRadius: 16,
                  overflow: "hidden",
                }}
              >
                <h3>
                  <button
                    type="button"
                    id={`faq-q-${i}`}
                    aria-expanded={isOpen}
                    aria-controls={`faq-a-${i}`}
                    onClick={() => setOpen(isOpen ? null : i)}
                    className="w-full flex items-center justify-between gap-4 text-left"
                    style={{
                      padding: "18px 22px",
                      background: "transparent",
                      border: "none",
                      cursor: "pointer",
                    }}
                  >
                    <span style={{ fontSize: 15, fontWeight: 600, color: TEXT }}>
                      {it.q}
                    </span>
                    <span
                      aria-hidden="true"
                      style={{
                        color: TEAL,
                        fontSize: 20,
                        flexShrink: 0,
                        transform: isOpen ? "rotate(45deg)" : "rotate(0deg)",
                        transition: "transform 0.18s",
                      }}
                    >
                      +
                    </span>
                  </button>
                </h3>
                <div
                  id={`faq-a-${i}`}
                  role="region"
                  aria-labelledby={`faq-q-${i}`}
                  hidden={!isOpen}
                  style={{
                    padding: "0 22px 20px",
                    fontSize: 14,
                    lineHeight: 1.6,
                    color: MUTED,
                  }}
                >
                  {it.a}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}

function FinalCTA() {
  return (
    <section style={{ padding: "0 20px 80px" }}>
      <div
        className="max-w-[1100px] mx-auto"
        style={{
          background: TEAL,
          borderRadius: 32,
          padding: "clamp(36px, 6vw, 60px) clamp(22px, 5vw, 40px)",
          color: "#fff",
          textAlign: "center",
          position: "relative",
          overflow: "hidden",
          boxShadow: "0 20px 50px rgba(10,120,112,0.20)",
        }}
      >
        <div
          aria-hidden="true"
          style={{
            position: "absolute",
            top: -100,
            right: -80,
            width: 300,
            height: 300,
            borderRadius: "50%",
            background: "rgba(255,255,255,0.06)",
            pointerEvents: "none",
          }}
        />
        <h2
          style={{
            fontSize: H2_SIZE,
            fontWeight: 700,
            letterSpacing: "-0.02em",
            marginBottom: 14,
            lineHeight: 1.15,
            position: "relative",
          }}
        >
          Translate, certify and get paid in one place
        </h2>
        <p
          style={{
            fontSize: 17,
            color: "rgba(255,255,255,0.85)",
            maxWidth: 600,
            margin: "0 auto 30px",
            position: "relative",
          }}
        >
          Upload your next client document and see the draft next to the original. No credit card needed for the trial.
        </p>
        <div className="flex items-center justify-center gap-3 flex-wrap" style={{ position: "relative" }}>
          <Link
            href="/register"
            style={{
              background: "#ffffff",
              color: TEAL_DARK,
              padding: "14px 28px",
              borderRadius: 999,
              fontWeight: 700,
              fontSize: 15,
            }}
          >
            Start free trial <span aria-hidden="true">→</span>
          </Link>
          <a
            href="#pricing"
            style={{
              background: "transparent",
              color: "#fff",
              padding: "14px 28px",
              borderRadius: 999,
              fontWeight: 600,
              fontSize: 15,
              border: "1px solid rgba(255,255,255,0.4)",
            }}
          >
            See pricing
          </a>
        </div>
      </div>
    </section>
  )
}

function Footer() {
  return (
    <footer
      style={{
        borderTop: `1px solid ${BORDER}`,
        background: CREAM_DARK,
        padding: "40px 20px 30px",
      }}
    >
      <div className="max-w-[1200px] mx-auto grid sm:grid-cols-2 md:grid-cols-4 gap-8">
        <div>
          <div className="flex items-center gap-2 mb-3">
            <BrandMark size={32} />
            <div style={{ fontSize: 15, fontWeight: 600, color: TEXT }}>
              <BrandName />
            </div>
          </div>
          <p style={{ fontSize: 12, color: MUTED, lineHeight: 1.6 }}>
            Layout-preserving translation, certification and paid delivery for certified translators.
          </p>
        </div>
        <FooterCol
          title="Product"
          links={[
            ["Demo", "#demo"],
            ["Features", "#features"],
            ["How it works", "#how-it-works"],
            ["Get paid", "#get-paid"],
            ["Security", "#security"],
            ["Pricing", "#pricing"],
            ["FAQ", "#faq"],
          ]}
        />
        <FooterCol
          title="Company"
          links={[
            ["About", "#"],
            ["Contact", "mailto:hello@onlinedoctranslator.ai"],
            ["Terms of service", "/terms"],
            ["Privacy policy", "/privacy"],
            ["Cookie policy", "/cookies"],
          ]}
        />
        <FooterCol
          title="Get started"
          links={[
            ["Sign in", "/login"],
            ["Create account", "/register"],
          ]}
        />
      </div>
      <div
        className="max-w-[1200px] mx-auto"
        style={{
          marginTop: 30,
          paddingTop: 20,
          borderTop: `1px solid ${BORDER}`,
          fontSize: 11,
          color: SUBTLE,
          display: "flex",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 8,
        }}
      >
        <CompanyLine />
      </div>
    </footer>
  )
}

function FooterCol({
  title,
  links,
}: {
  title: string
  links: [string, string][]
}) {
  return (
    <div>
      <div
        style={{
          fontSize: 11,
          letterSpacing: "0.14em",
          color: SUBTLE,
          fontWeight: 600,
          marginBottom: 14,
        }}
      >
        {title.toUpperCase()}
      </div>
      <ul className="space-y-2">
        {links.map(([label, href]) => (
          <li key={label}>
            <Link
              href={href}
              style={{ fontSize: 13, color: TEXT, textDecoration: "none" }}
            >
              {label}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}

function SectionHeader({
  eyebrow,
  title,
  subtitle,
}: {
  eyebrow: string
  title: string
  subtitle?: string
}) {
  return (
    <div style={{ textAlign: "center", maxWidth: 720, margin: "0 auto" }}>
      <div
        style={{
          fontSize: 11,
          letterSpacing: "0.18em",
          color: TEAL,
          fontWeight: 600,
          marginBottom: 12,
        }}
      >
        {eyebrow}
      </div>
      <h2
        style={{
          fontSize: H2_SIZE,
          fontWeight: 700,
          letterSpacing: "-0.02em",
          color: TEXT,
          lineHeight: 1.15,
          marginBottom: subtitle ? 14 : 0,
        }}
      >
        {title}
      </h2>
      {subtitle && (
        <p style={{ fontSize: 16, color: MUTED, lineHeight: 1.55 }}>{subtitle}</p>
      )}
    </div>
  )
}

function Check() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
      <path d="m5 12 5 5 10-10" />
    </svg>
  )
}
function IconLayout() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M3 9h18M9 21V9" />
    </svg>
  )
}
function IconShield() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3 4 6v6c0 5 3.4 8.4 8 9 4.6-.6 8-4 8-9V6Z" />
      <path d="m9 12 2 2 4-4" />
    </svg>
  )
}
function IconBrain() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 3a3 3 0 0 0-3 3v0a3 3 0 0 0-3 3v0a3 3 0 0 0 3 3v0a3 3 0 0 0 3 3v0a3 3 0 0 0 3 3v0a3 3 0 0 0 3-3v0a3 3 0 0 0 3-3v0a3 3 0 0 0-3-3v0a3 3 0 0 0-3-3v0a3 3 0 0 0-3-3Z" />
    </svg>
  )
}
function IconLock() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="4" y="10" width="16" height="11" rx="2" />
      <path d="M8 10V7a4 4 0 1 1 8 0v3" />
    </svg>
  )
}
function IconUsers() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="9" cy="8" r="3.5" />
      <path d="M2.5 20c.5-3.5 3.3-5.5 6.5-5.5s6 2 6.5 5.5" />
      <circle cx="17" cy="9" r="2.8" />
      <path d="M15.5 14.5c2.6 0 5 1.6 5.5 4" />
    </svg>
  )
}
function IconGlobe() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
    </svg>
  )
}
function IconNoTrain() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z" />
      <path d="M14 3v5h5" />
      <path d="m4 4 16 16" />
    </svg>
  )
}
function IconTrash() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13" />
    </svg>
  )
}
function IconBolt() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="m13 2-7 12h6l-2 8 8-12h-6Z" />
    </svg>
  )
}
function IconSend() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 3 10 14" />
      <path d="m21 3-7 18-4-7-7-4Z" />
    </svg>
  )
}
function IconCard() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="M3 10h18M7 15h3" />
    </svg>
  )
}
function IconLink() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M10 14a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1" />
      <path d="M14 10a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1" />
    </svg>
  )
}

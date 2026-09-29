"use client"

import Image from "next/image"

import { useState } from "react"
import Link from "next/link"

const CREAM = "#faf5ee"
const CREAM_DARK = "#f3ecdb"
const CREAM_DEEP = "#ede3cc"
const TEAL = "#0a7870"
const TEAL_DARK = "#0a5e58"
const TEAL_SOFT = "#cfe6e2"
const TEXT = "#1f2a2e"
const MUTED = "#6b6558"
const SUBTLE = "#8a8270"
const BORDER = "#e7ddc5"
const ACCENT_GOLD = "#c88a1a"
const ACCENT_RUST = "#b14a3a"

export default function LandingPage() {
  return (
    <div style={{ background: CREAM, color: TEXT, minHeight: "100vh" }}>
      <TopBar />
      <Hero />
      <TrustBar />
      <ValueProps />
      <HowItWorks />
      <DeepFeatures />
      <Pricing />
      <FAQ />
      <FinalCTA />
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
        style={{ padding: "14px 24px" }}
      >
        <Link href="/" className="flex items-center gap-3">
          <div
            className="w-9 h-9 rounded-xl flex items-center justify-center font-bold text-white"
            style={{ background: TEAL, fontSize: 18 }}
          >
            T
          </div>
          <div>
            <div style={{ fontSize: 16, fontWeight: 600, color: TEXT }}>
              TraqConverter
            </div>
            <div
              style={{
                fontSize: 9,
                letterSpacing: "0.2em",
                color: SUBTLE,
                marginTop: -2,
              }}
            >
              <span className="hidden sm:inline">LAYOUT-PRESERVING TRANSLATION</span>
            </div>
          </div>
        </Link>
        <nav className="hidden md:flex items-center gap-8">
          <a href="#features" style={navLink}>Features</a>
          <a href="#how-it-works" style={navLink}>How it works</a>
          <a href="#pricing" style={navLink}>Pricing</a>
          <a href="#faq" style={navLink}>FAQ</a>
        </nav>
        <div className="flex items-center gap-1 sm:gap-3 whitespace-nowrap">
          <Link
            href="/login"
            className="hidden sm:inline-block"
            style={{
              fontSize: 14,
              fontWeight: 500,
              color: TEXT,
              padding: "8px 16px",
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

function Hero() {
  return (
    <section style={{ position: "relative", overflow: "hidden" }}>
      {}
      <div
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
        style={{ padding: "80px 24px 64px" }}
      >
        <div className="grid lg:grid-cols-[1.15fr_1fr] gap-12 items-center">
          <div>
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
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: "50%",
                  background: TEAL,
                }}
              />
              FOR PROFESSIONAL TRANSLATORS · PDF · DOCX · SCANS
            </div>
            <h1
              style={{
                fontSize: 56,
                lineHeight: 1.05,
                fontWeight: 700,
                letterSpacing: "-0.02em",
                color: TEXT,
                marginBottom: 20,
              }}
            >
              The first draft of every certified translation.{" "}
              <span style={{ color: TEAL }}>Layout included.</span>
            </h1>
            <p
              style={{
                fontSize: 18,
                lineHeight: 1.55,
                color: MUTED,
                marginBottom: 32,
                maxWidth: 560,
              }}
            >
              Upload your client&apos;s scan, PDF, or Word file. TraqConverter
              reads it, translates it, and rebuilds the page layout, marking
              signatures, stamps, and unreadable parts the way you would. Correct
              it in place or ask the built-in AI to fix a highlighted passage, then export
              it with your own certification page.
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
                Start free 7-day trial
                <span>→</span>
              </Link>
              <Link
                href="#how-it-works"
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
                Watch how it works
              </Link>
            </div>
            <div className="flex flex-wrap items-center gap-x-7 gap-y-2">
              {[
                "No credit card required",
                "7-day trial with 1 free page",
                "You review and sign every document",
              ].map((t) => (
                <div
                  key={t}
                  className="flex items-center gap-2"
                  style={{ fontSize: 13, color: MUTED }}
                >
                  <Check />
                  {t}
                </div>
              ))}
            </div>
          </div>

          {}
          <HeroVisual />
        </div>
      </div>
    </section>
  )
}

function HeroVisual() {
  return (
    <div className="relative">
      <Shot src="/landing/editor.webp" width={1800} height={1204} alt="Source and translation side by side; clicking a translated line highlights it on the original" priority />
      <div
        className="hidden md:block"
        style={{
          position: "absolute",
          left: -18,
          bottom: 28,
          background: "#ffffff",
          border: `1px solid ${BORDER}`,
          borderRadius: 14,
          padding: "10px 14px",
          boxShadow: "0 12px 28px rgba(30,30,20,0.12)",
          fontSize: 12,
          color: TEXT,
          maxWidth: 230,
        }}
      >
        <div style={{ color: TEAL, fontWeight: 600, marginBottom: 2 }}>Click a line, see its source</div>
        <div style={{ color: MUTED }}>Every translated paragraph is linked to where it sits on the original.</div>
      </div>
    </div>
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
      <div className="flex items-center gap-1.5" style={{ padding: "10px 14px", borderBottom: `1px solid ${CREAM_DARK}` }}>
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
      style={{
        background: CREAM_DARK,
        borderTop: `1px solid ${BORDER}`,
        borderBottom: `1px solid ${BORDER}`,
      }}
    >
      <div
        className="max-w-[1200px] mx-auto grid grid-cols-2 md:grid-cols-4 gap-y-6 gap-x-6"
        style={{ padding: "28px 24px" }}
      >
        {[
          { n: "28", l: "Languages" },
          { n: "PDF · DOCX · JPG · PNG", l: "Input formats" },
          { n: "DOCX · PDF", l: "Export formats" },
          { n: "10 AI edits", l: "Included per page" },
        ].map((s) => (
          <div key={s.l}>
            <div
              style={{
                fontSize: 28,
                fontWeight: 700,
                color: TEAL,
                letterSpacing: "-0.02em",
              }}
            >
              {s.n}
            </div>
            <div style={{ fontSize: 12, color: MUTED, marginTop: 2 }}>
              {s.l}
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

function ValueProps() {
  return (
    <section id="features" style={{ padding: "80px 24px" }}>
      <div className="max-w-[1200px] mx-auto">
        <SectionHeader
          eyebrow="WHY TRAQCONVERTER"
          title="Built for translators who sign what they deliver"
          subtitle="The AI does the first draft and the layout. You stay in control of every line, and the tool gets better at your work each time."
        />
        <div className="grid md:grid-cols-3 gap-5 mt-12">
          <FeatureCard
            icon={<IconLayout />}
            title="Layout rebuilt, page for page"
            body="Tables, two-column forms, and signature blocks come back where they were on the original, as an editable Word document, not a text dump."
          />
          <FeatureCard
            icon={<IconShield />}
            title="Stamps, signatures, and [illegible]"
            body="Noted where they appear, in the target language, the way you would: [Signature], [Round stamp: …], [Revenue stamp: €16.00], and [illegible] only on the part that can't be read."
          />
          <FeatureCard
            icon={<IconBolt />}
            title="Ask AI on any passage"
            body="Highlight a line, a table, or a signature block and say what's off. Wording and formatting fixes take seconds; every change can be undone."
          />
          <FeatureCard
            icon={<IconBrain />}
            title="Learns your templates and terms"
            body="Your corrections become your team's terminology. A finished document becomes a template, so the next one of the same kind starts from your version."
          />
          <FeatureCard
            icon={<IconLock />}
            title="Checked before you sign"
            body="Every number, date, name, and code in the source is compared with your translation, along with untranslated text, missing stamp notes, and your glossary."
          />
          <FeatureCard
            icon={<IconUsers />}
            title="Your certification page and stamp"
            body="Your statement, date, languages, logo, and stamp go at the end of the document and export with it as one file. Drag your stamp wherever it belongs."
          />
        </div>
      </div>
    </section>
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
        padding: 26,
      }}
    >
      <div
        style={{
          width: 44,
          height: 44,
          borderRadius: 12,
          background: TEAL_SOFT,
          color: TEAL,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          marginBottom: 18,
        }}
      >
        {icon}
      </div>
      <div style={{ fontSize: 17, fontWeight: 600, color: TEXT, marginBottom: 8 }}>
        {title}
      </div>
      <div style={{ fontSize: 14, lineHeight: 1.55, color: MUTED }}>{body}</div>
    </div>
  )
}

function HowItWorks() {
  return (
    <section
      id="how-it-works"
      style={{
        padding: "80px 24px",
        background: CREAM_DARK,
        borderTop: `1px solid ${BORDER}`,
        borderBottom: `1px solid ${BORDER}`,
      }}
    >
      <div className="max-w-[1200px] mx-auto">
        <SectionHeader
          eyebrow="HOW IT WORKS"
          title="From the client's scan to a translation you can sign"
        />
        <div className="grid md:grid-cols-3 gap-5 mt-12">
          {[
            {
              n: "01",
              t: "Upload the client's document",
              b: "Drag in a PDF, DOCX, JPG, or PNG. Pick the target language and either pick the source or let auto-detect choose.",
            },
            {
              n: "02",
              t: "Correct the draft",
              b: "The source stays on the left, the translated document on the right. Type corrections directly, or highlight a passage and ask the AI to change it.",
            },
            {
              n: "03",
              t: "Certify & deliver",
              b: "Export DOCX or PDF with the original layout. On Pro, your certification page with your details, logo, and stamp is added for you to sign.",
            },
          ].map((s, i) => (
            <div
              key={s.n}
              style={{
                background: "#ffffff",
                border: `1px solid ${BORDER}`,
                borderRadius: 20,
                padding: 26,
                position: "relative",
              }}
            >
              <div
                style={{
                  fontSize: 38,
                  fontWeight: 700,
                  color: TEAL,
                  letterSpacing: "-0.04em",
                  lineHeight: 1,
                  marginBottom: 16,
                }}
              >
                {s.n}
              </div>
              <div style={{ fontSize: 17, fontWeight: 600, color: TEXT, marginBottom: 8 }}>
                {s.t}
              </div>
              <div style={{ fontSize: 14, lineHeight: 1.55, color: MUTED }}>
                {s.b}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

function DeepFeatures() {
  return (
    <section style={{ padding: "80px 24px" }}>
      <div className="max-w-[1200px] mx-auto">
        <SectionHeader
          eyebrow="THE WORKBENCH"
          title="Edit the document, not a list of segments"
          subtitle="The translation is a real Word document next to the original. Type where something's wrong, or highlight it and ask the AI."
        />
        <ShowcaseRow
          image={<Shot maxHeight={560} src="/landing/assistant.webp" width={1400} height={1570} alt="Asking the AI to write a date in full; the edited line is highlighted" />}
          eyebrow="ASK AI"
          title="Fix anything by asking"
          items={[
            { t: "Point at it", b: "Highlight the passage; the assistant sees it, the original, and the rest of the document." },
            { t: "Say what's off", b: "“Write the date in full”, “put the stamp beside the signature”, “use Registry Office”." },
            { t: "Seconds, not a re-translation", b: "Only what you pointed at changes. Undo is one click." },
          ]}
        />
        <ShowcaseRow
          reverse
          image={<Shot maxHeight={560} src="/landing/checks.webp" width={1100} height={1486} alt="Ready to certify checklist listing what to check before signing" />}
          eyebrow="READY TO CERTIFY"
          title="Nothing slips past your signature"
          items={[
            { t: "Numbers, dates, codes, names", b: "Compared with the source. A missing digit is flagged before you sign, not after the client does." },
            { t: "Uncertain readings", b: "Faded stamps, handwriting, and smudged digits are marked for you to look at, with the spot highlighted on the original." },
            { t: "One click to the problem", b: "Each item jumps to the paragraph and its place on the source." },
          ]}
        />
        <ShowcaseRow
          image={<Shot maxHeight={560} src="/landing/cert.webp" width={1100} height={1486} alt="Certification page fields: date, languages, translator, document" />}
          eyebrow="CERTIFICATION"
          title="Your certification page, built in"
          items={[
            { t: "Filled in for you", b: "Translator, date, source and target language, document, and pages, in the target language." },
            { t: "Edit in place", b: "Change the date or languages without touching the rest of the page." },
            { t: "One file out", b: "Export DOCX or PDF with the source copy, the translation, and your certification page together." },
          ]}
        />
        <div className="grid md:grid-cols-2 gap-6 mt-20">
          <HighlightCard
            eyebrow="LEARNS AS YOU WORK"
            title="The second driving licence is faster than the first"
            body="Finished documents become your team's templates. The next document of the same kind is built from your version, changing only names, dates, and numbers, in seconds instead of minutes. The terms you correct are remembered and used next time."
          />
          <HighlightCard
            eyebrow="BATCHES"
            title="One client, many documents, one spelling"
            body="Upload a client's birth certificate, diploma, and transcripts together. Names, institutions, and places are rendered the same way in every document, and you download the whole batch as one ZIP."
          />
        </div>
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
    <div className="grid md:grid-cols-2 gap-12 items-center mt-20">
      <div className={reverse ? "md:order-2" : ""}>{image}</div>
      <div>
        <div style={{ fontSize: 11, letterSpacing: "0.16em", color: TEAL, fontWeight: 600, marginBottom: 10 }}>{eyebrow}</div>
        <h3 style={{ fontSize: 30, lineHeight: 1.15, fontWeight: 700, color: TEXT, letterSpacing: "-0.02em", marginBottom: 22 }}>{title}</h3>
        <FeatureList items={items} />
      </div>
    </div>
  )
}

function HighlightCard({ eyebrow, title, body }: { eyebrow: string; title: string; body: string }) {
  return (
    <div style={{ background: "#ffffff", border: `1px solid ${BORDER}`, borderRadius: 20, padding: 30 }}>
      <div style={{ fontSize: 11, letterSpacing: "0.16em", color: TEAL, fontWeight: 600, marginBottom: 10 }}>{eyebrow}</div>
      <div style={{ fontSize: 22, lineHeight: 1.25, fontWeight: 700, color: TEXT, marginBottom: 12 }}>{title}</div>
      <div style={{ fontSize: 15, lineHeight: 1.6, color: MUTED }}>{body}</div>
    </div>
  )
}

function FeatureList({
  items,
}: {
  items: { t: string; b: string }[]
}) {
  return (
    <div className="space-y-5">
      {items.map((it) => (
        <div key={it.t} className="flex items-start gap-4">
          <div
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
          <div>
            <div style={{ fontSize: 16, fontWeight: 600, color: TEXT, marginBottom: 4 }}>
              {it.t}
            </div>
            <div style={{ fontSize: 14, lineHeight: 1.55, color: MUTED }}>
              {it.b}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

function Pricing() {
  return (
    <section
      id="pricing"
      style={{
        padding: "80px 24px",
        background: CREAM_DARK,
        borderTop: `1px solid ${BORDER}`,
        borderBottom: `1px solid ${BORDER}`,
      }}
    >
      <div className="max-w-[1200px] mx-auto">
        <SectionHeader
          eyebrow="PRICING"
          title="Simple plans. Pay only for the pages you translate."
          subtitle="One credit translates one page. Subscriptions refill monthly; credit packs top you up. No setup fees."
        />

        <div className="grid md:grid-cols-3 gap-5 mt-12">
          <PlanCard
            name="Free trial"
            price="0"
            period="7 days"
            credits="1 page"
            highlight={false}
            cta="Start free"
            ctaHref="/register"
            features={[
              "1 page translated",
              "Layout-preserving rebuild",
              "Review in the editor",
              "Preview only: downloads need a paid plan",
            ]}
          />
          <PlanCard
            name="Basic"
            price="19"
            period="/month"
            credits="19 pages / month"
            highlight={false}
            cta="Choose Basic"
            ctaHref="/register?plan=basic"
            features={[
              "19 pages translated / month",
              "Layout-preserving rebuild",
              "DOCX & PDF export",
              "Team members & roles",
              "Top up with credit packs",
            ]}
          />
          <PlanCard
            name="Pro"
            price="29"
            period="/month"
            credits="29 pages / month"
            highlight={true}
            cta="Choose Pro"
            ctaHref="/register?plan=pro"
            features={[
              "29 pages translated / month",
              "Everything in Basic",
              "Translation memory",
              "Glossary",
              "Certification statement page",
              "Certifications library",
            ]}
          />
        </div>

        {}
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
            NEED MORE? ADD CREDIT PACKS ANYTIME
          </div>
          <h3
            style={{
              fontSize: 22,
              fontWeight: 600,
              textAlign: "center",
              color: TEXT,
              marginBottom: 24,
            }}
          >
            One-off credit packs — never expire
          </h3>
          <div className="grid md:grid-cols-3 gap-4 max-w-[860px] mx-auto">
            {[
              {
                name: "Starter pack",
                credits: 10,
                price: "€10",
                note: "Top up a small project",
                featured: false,
              },
              {
                name: "Studio pack",
                credits: 25,
                price: "€25",
                note: "For a few documents",
                featured: true,
              },
              {
                name: "Scale pack",
                credits: 50,
                price: "€50",
                note: "Best for high-volume work",
                featured: false,
              },
            ].map((pack) => (
              <div
                key={pack.name}
                style={{
                  background: "#ffffff",
                  border: `1px solid ${pack.featured ? TEAL : BORDER}`,
                  borderRadius: 16,
                  padding: 22,
                  textAlign: "center",
                  position: "relative",
                  boxShadow: pack.featured
                    ? "0 8px 20px rgba(10,120,112,0.10)"
                    : "0 1px 2px rgba(30,30,20,0.03)",
                }}
              >
                {pack.featured && (
                  <div
                    style={{
                      position: "absolute",
                      top: -10,
                      left: "50%",
                      transform: "translateX(-50%)",
                      background: ACCENT_GOLD,
                      color: "#fff",
                      fontSize: 9,
                      fontWeight: 700,
                      padding: "3px 10px",
                      borderRadius: 999,
                      letterSpacing: "0.1em",
                    }}
                  >
                    POPULAR
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
                    color: pack.featured ? TEAL : TEXT,
                  }}
                >
                  {pack.price}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}

function PlanCard({
  name,
  price,
  period,
  credits,
  features,
  highlight,
  cta,
  ctaHref,
}: {
  name: string
  price: string
  period: string
  credits: string
  features: string[]
  highlight: boolean
  cta: string
  ctaHref: string
}) {
  return (
    <div
      style={{
        background: highlight ? "#0a7870" : "#ffffff",
        color: highlight ? "#ffffff" : TEXT,
        border: `1px solid ${highlight ? TEAL_DARK : BORDER}`,
        borderRadius: 22,
        padding: 32,
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
      <div
        style={{
          fontSize: 13,
          letterSpacing: "0.12em",
          fontWeight: 600,
          marginBottom: 14,
          color: highlight ? "rgba(255,255,255,0.7)" : SUBTLE,
        }}
      >
        {name.toUpperCase()}
      </div>
      <div className="flex items-baseline gap-1">
        <span style={{ fontSize: 16, fontWeight: 500, opacity: 0.7 }}>€</span>
        <span style={{ fontSize: 44, fontWeight: 700, letterSpacing: "-0.02em" }}>
          {price}
        </span>
        <span
          style={{
            fontSize: 13,
            color: highlight ? "rgba(255,255,255,0.7)" : MUTED,
            marginLeft: 4,
          }}
        >
          {period}
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
        {credits}
      </div>
      <Link
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
      </Link>
      <div className="space-y-3">
        {features.map((f) => (
          <div
            key={f}
            className="flex items-start gap-2"
            style={{ fontSize: 13, color: highlight ? "rgba(255,255,255,0.92)" : TEXT }}
          >
            <Check />
            <span>{f}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function FAQ() {
  const [open, setOpen] = useState<number | null>(0)
  const items = [
    {
      q: "Is the output ready to certify?",
      a: "It's a draft for you to review, not a certified translation. You check it, correct it, and sign your statement; TraqConverter never certifies anything itself. On Pro, your certification page with your details, logo, and stamp is added to the export. Acceptance still depends on your credentials and the receiving authority's rules.",
    },
    {
      q: "How are signatures, stamps, and unreadable parts handled?",
      a: "They are never copied as images. Each is noted where it appears, in the target language: [Signature], [Round stamp: Municipality of Rome – Registry Office], [Revenue stamp: €16.00]. Anything unreadable is marked [illegible] on exactly that word or number; names, dates, and figures are never guessed.",
    },
    {
      q: "What file formats do you support?",
      a: "PDF (single or multi-page, including scans), JPG, PNG, and DOCX. Exports are DOCX and PDF with the layout rebuilt.",
    },
    {
      q: "Will the layout look like the original?",
      a: "That's the goal of the rebuild: text blocks, tables, and signature blocks are placed where they were in the original. Complex pages can need touch-ups, which you make in the editor by typing or by asking the AI.",
    },
    {
      q: "Which languages do you handle?",
      a: "28 languages, including Arabic, Hebrew, Chinese (Simplified and Traditional), Japanese, and Korean. Auto-detect can pick the source language for you.",
    },
    {
      q: "How does pricing work?",
      a: "Each page is one credit. Subscriptions include a monthly allowance (19 on Basic, 29 on Pro) that resets each billing period. Credit packs of 10, 25, or 50 don't expire. The 7-day trial includes 1 page.",
    },
    {
      q: "What does a page credit include?",
      a: "Translating one page, plus 10 AI edits on that document with Ask AI. After that, 1 credit adds 10 more edits. Each document can be regenerated from scratch twice.",
    },
    {
      q: "Does it really learn from my corrections?",
      a: "Yes. The terms you correct are added to your team's terminology and used in future translations; you can remove any of them. Finished documents become templates, so the next document of the same kind starts from your approved version.",
    },
    {
      q: "What happens to my files?",
      a: "Projects stay in your account until you delete them, which you can do at any time. Deleting a project removes its files, text, and translation memory entries. We don't train models on your documents.",
    },
    {
      q: "Can my team work together?",
      a: "Paid plans include team members with roles (admin, PM, reviewer, member), and project assignment. Pro adds a shared translation memory and glossary.",
    },
  ]
  return (
    <section id="faq" style={{ padding: "80px 24px" }}>
      <div className="max-w-[820px] mx-auto">
        <SectionHeader
          eyebrow="QUESTIONS"
          title="Questions translators ask"
        />
        <div className="space-y-3 mt-12">
          {items.map((it, i) => (
            <div
              key={it.q}
              style={{
                background: "#ffffff",
                border: `1px solid ${BORDER}`,
                borderRadius: 16,
                overflow: "hidden",
              }}
            >
              <button
                type="button"
                onClick={() => setOpen(open === i ? null : i)}
                className="w-full flex items-center justify-between text-left"
                style={{
                  padding: "18px 22px",
                  background: "transparent",
                  border: "none",
                  cursor: "pointer",
                }}
              >
                <span
                  style={{ fontSize: 15, fontWeight: 600, color: TEXT }}
                >
                  {it.q}
                </span>
                <span
                  style={{
                    color: TEAL,
                    fontSize: 20,
                    transform: open === i ? "rotate(45deg)" : "rotate(0deg)",
                    transition: "transform 0.18s",
                  }}
                >
                  +
                </span>
              </button>
              {open === i && (
                <div
                  style={{
                    padding: "0 22px 20px",
                    fontSize: 14,
                    lineHeight: 1.6,
                    color: MUTED,
                  }}
                >
                  {it.a}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

function FinalCTA() {
  return (
    <section style={{ padding: "0 24px 80px" }}>
      <div
        className="max-w-[1100px] mx-auto"
        style={{
          background: TEAL,
          borderRadius: 32,
          padding: "60px 40px",
          color: "#fff",
          textAlign: "center",
          position: "relative",
          overflow: "hidden",
          boxShadow: "0 20px 50px rgba(10,120,112,0.20)",
        }}
      >
        <div
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
            fontSize: 38,
            fontWeight: 700,
            letterSpacing: "-0.02em",
            marginBottom: 14,
            lineHeight: 1.15,
          }}
        >
          Draft your next certified translation
        </h2>
        <p
          style={{
            fontSize: 17,
            color: "rgba(255,255,255,0.85)",
            marginBottom: 30,
            maxWidth: 600,
            margin: "0 auto 30px",
          }}
        >
          Upload one page, correct it next to the original, and export it with your certification page. No credit card needed for the trial.
        </p>
        <div className="flex items-center justify-center gap-3 flex-wrap">
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
            Start free trial →
          </Link>
          <Link
            href="/login"
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
            Sign in
          </Link>
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
        padding: "40px 24px 30px",
      }}
    >
      <div className="max-w-[1200px] mx-auto grid md:grid-cols-4 gap-8">
        <div>
          <div className="flex items-center gap-2 mb-3">
            <div
              className="w-8 h-8 rounded-lg flex items-center justify-center font-bold text-white"
              style={{ background: TEAL, fontSize: 14 }}
            >
              T
            </div>
            <div style={{ fontSize: 15, fontWeight: 600, color: TEXT }}>
              TraqConverter
            </div>
          </div>
          <div style={{ fontSize: 12, color: MUTED, lineHeight: 1.6 }}>
            AI document translation that keeps the original layout.
          </div>
        </div>
        <FooterCol
          title="Product"
          links={[
            ["Features", "#features"],
            ["How it works", "#how-it-works"],
            ["Pricing", "#pricing"],
            ["FAQ", "#faq"],
          ]}
        />
        <FooterCol
          title="Company"
          links={[
            ["About", "#"],
            ["Contact", "mailto:hello@onlinedoctranslator.ai"],
            ["Privacy policy", "#"],
            ["Terms of service", "#"],
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
        <div>© {new Date().getFullYear()} TraqConverter. All rights reserved.</div>
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
          fontSize: 38,
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
function IconBolt() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="m13 2-7 12h6l-2 8 8-12h-6Z" />
    </svg>
  )
}

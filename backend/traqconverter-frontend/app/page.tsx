"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { getToken } from "@/lib/auth"

// ============================================================
// PUBLIC LANDING PAGE
// Cream + teal aesthetic, no AppShell. Logged-in visitors get
// bounced to /dashboard by AppShell so this surface is for
// unauthenticated visitors who need to be convinced to register.
// ============================================================

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
  const router = useRouter()
  const [yearly, setYearly] = useState(false)

  // Logged-in visitors don't need the marketing page.
  useEffect(() => {
    if (getToken()) router.replace("/dashboard")
  }, [router])

  return (
    <div style={{ background: CREAM, color: TEXT, minHeight: "100vh" }}>
      <TopBar />
      <Hero />
      <TrustBar />
      <ValueProps />
      <HowItWorks />
      <DeepFeatures />
      <Pricing yearly={yearly} setYearly={setYearly} />
      <FAQ />
      <FinalCTA />
      <Footer />
    </div>
  )
}

// ============================================================
// TOP BAR
// ============================================================
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
              CERTIFIED · ACCURATE · FAST
            </div>
          </div>
        </Link>
        <nav className="hidden md:flex items-center gap-8">
          <a href="#features" style={navLink}>Features</a>
          <a href="#how-it-works" style={navLink}>How it works</a>
          <a href="#pricing" style={navLink}>Pricing</a>
          <a href="#faq" style={navLink}>FAQ</a>
        </nav>
        <div className="flex items-center gap-3">
          <Link
            href="/login"
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
            Start free trial
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

// ============================================================
// HERO
// ============================================================
function Hero() {
  return (
    <section style={{ position: "relative", overflow: "hidden" }}>
      {/* Decorative blob */}
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
              CERTIFIED TRANSLATIONS · ISO 17100 · GDPR
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
              Translate any document.{" "}
              <span style={{ color: TEAL }}>Keep the layout.</span>
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
              Upload a PDF, scan, or image. We extract the text with AI vision,
              translate it into 90+ languages, rebuild the document exactly
              as it was — with stamps, signatures, and certifications
              preserved — and return a sworn-translator-ready file in minutes.
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
                "GDPR compliant",
                "Used by certified translators",
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

          {/* HERO VISUAL */}
          <HeroVisual />
        </div>
      </div>
    </section>
  )
}

function HeroVisual() {
  return (
    <div
      style={{
        background: "#ffffff",
        border: `1px solid ${BORDER}`,
        borderRadius: 24,
        boxShadow: "0 16px 40px rgba(30,30,20,0.08)",
        padding: 18,
        position: "relative",
      }}
    >
      {/* Browser chrome */}
      <div className="flex items-center gap-1.5 mb-3">
        <div style={dot("#ffb8a8")} />
        <div style={dot("#ffd98a")} />
        <div style={dot("#a8d9a3")} />
      </div>
      <div className="grid grid-cols-2 gap-3">
        {/* SOURCE — Italian */}
        <div
          style={{
            background: CREAM,
            borderRadius: 14,
            padding: 16,
            border: `1px solid ${BORDER}`,
            minHeight: 260,
          }}
        >
          <div
            style={{
              fontSize: 9,
              letterSpacing: "0.16em",
              color: SUBTLE,
              fontWeight: 600,
              marginBottom: 10,
            }}
          >
            ORIGINAL · ITALIAN
          </div>
          <div style={{ fontSize: 9, color: TEXT, fontWeight: 700 }}>
            MINISTERO DELL'INTERNO
          </div>
          <div
            style={{
              fontSize: 13,
              fontWeight: 700,
              textAlign: "center",
              margin: "18px 0 8px",
              color: TEXT,
            }}
          >
            Ricevuta della richiesta CIE
          </div>
          <div style={{ fontSize: 9, color: MUTED, marginBottom: 14 }}>
            Conserva questo documento, potrai utilizzarlo in Italia…
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4, fontSize: 8 }}>
            {[
              ["Comune", "S. BENEDETTO"],
              ["Cognome", "PIERGALLINI"],
              ["Nome", "LILIA"],
              ["Codice Fiscale", "PRGLLI21E70…"],
            ].map(([k, v]) => (
              <div key={k} style={{ display: "contents" }}>
                <div style={{ color: MUTED }}>{k}</div>
                <div style={{ fontWeight: 600, color: TEXT }}>{v}</div>
              </div>
            ))}
          </div>
        </div>

        {/* TARGET — English */}
        <div
          style={{
            background: "#ffffff",
            borderRadius: 14,
            padding: 16,
            border: `1px solid ${TEAL_SOFT}`,
            position: "relative",
            minHeight: 260,
          }}
        >
          <div
            style={{
              fontSize: 9,
              letterSpacing: "0.16em",
              color: TEAL,
              fontWeight: 600,
              marginBottom: 10,
            }}
          >
            TRANSLATION · ENGLISH
          </div>
          <div style={{ fontSize: 9, color: TEXT, fontWeight: 700 }}>
            MINISTRY OF THE INTERIOR
          </div>
          <div
            style={{
              fontSize: 13,
              fontWeight: 700,
              textAlign: "center",
              margin: "18px 0 8px",
              color: TEXT,
            }}
          >
            Receipt of the CIE Request
          </div>
          <div style={{ fontSize: 9, color: MUTED, marginBottom: 14 }}>
            Keep this document; you can use it in Italy until you receive…
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4, fontSize: 8 }}>
            {[
              ["Municipality", "S. BENEDETTO"],
              ["Surname", "PIERGALLINI"],
              ["Name", "LILIA"],
              ["Tax Code", "PRGLLI21E70…"],
            ].map(([k, v]) => (
              <div key={k} style={{ display: "contents" }}>
                <div style={{ color: MUTED }}>{k}</div>
                <div style={{ fontWeight: 600, color: TEXT }}>{v}</div>
              </div>
            ))}
          </div>
          {/* Sparkle */}
          <div
            style={{
              position: "absolute",
              top: -10,
              right: -10,
              background: TEAL,
              color: "#fff",
              fontSize: 10,
              fontWeight: 600,
              padding: "5px 10px",
              borderRadius: 999,
              boxShadow: "0 6px 14px rgba(10,120,112,0.25)",
            }}
          >
            ✓ certified
          </div>
        </div>
      </div>
      <div
        style={{
          marginTop: 14,
          padding: "10px 14px",
          background: CREAM_DARK,
          borderRadius: 12,
          fontSize: 11,
          color: MUTED,
          textAlign: "center",
        }}
      >
        Original layout · 2 minutes · 1 credit
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

// ============================================================
// TRUST BAR
// ============================================================
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
          { n: "50k+", l: "Pages translated" },
          { n: "90+", l: "Languages supported" },
          { n: "2 min", l: "Average turnaround" },
          { n: "99.4%", l: "Layout fidelity" },
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

// ============================================================
// VALUE PROPS
// ============================================================
function ValueProps() {
  return (
    <section id="features" style={{ padding: "80px 24px" }}>
      <div className="max-w-[1200px] mx-auto">
        <SectionHeader
          eyebrow="WHY TRAQCONVERTER"
          title="Built for professionals who can't afford a mistake"
          subtitle="Sworn translators, immigration lawyers, HR teams, and notaries trust TraqConverter to handle the documents that matter."
        />
        <div className="grid md:grid-cols-3 gap-5 mt-12">
          <FeatureCard
            icon={<IconLayout />}
            title="Layout-perfect rebuilds"
            body="Tables, two-column forms, stamps and signatures all reappear in the same place. No more retyping a translation into a Word template."
          />
          <FeatureCard
            icon={<IconShield />}
            title="ISO 17100 certified output"
            body="Every translation can be exported with a signed translator statement, your branding, and a sworn-affidavit page ready for embassies and courts."
          />
          <FeatureCard
            icon={<IconBrain />}
            title="Claude + OpenAI under the hood"
            body="Claude Vision OCR reads stylised IDs and stamps. GPT-4 translates with full context. You review and approve in our CAT-style editor."
          />
          <FeatureCard
            icon={<IconLock />}
            title="GDPR · Bank-grade security"
            body="Documents are encrypted in transit and at rest. Auto-deleted after 30 days unless you keep them. Your data is never used to train models."
          />
          <FeatureCard
            icon={<IconUsers />}
            title="Team workflows built in"
            body="Invite collaborators, assign projects to teammates, leave segment-level comments, and certify together. Translation memory + glossary stay in sync."
          />
          <FeatureCard
            icon={<IconBolt />}
            title="Under 5 minutes per page"
            body="Drop a PDF, get a draft back in two minutes. Most certified documents are reviewed and signed within the same coffee break."
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

// ============================================================
// HOW IT WORKS
// ============================================================
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
          title="From scanned PDF to certified translation in three steps"
        />
        <div className="grid md:grid-cols-3 gap-5 mt-12">
          {[
            {
              n: "01",
              t: "Upload your document",
              b: "Drag in a PDF, JPG, or PNG. Tell us the source and target language — or let auto-detect figure it out.",
            },
            {
              n: "02",
              t: "Review the AI draft",
              b: "Claude Vision extracts every block. GPT-4 translates with context. You review side-by-side in the editor and tweak anything you want.",
            },
            {
              n: "03",
              t: "Export & deliver",
              b: "Download DOCX or PDF with the original layout, your logo, and a sworn translator certification page. Ready to send.",
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

// ============================================================
// DEEP FEATURES — alternating image / text
// ============================================================
function DeepFeatures() {
  return (
    <section style={{ padding: "80px 24px" }}>
      <div className="max-w-[1200px] mx-auto">
        <SectionHeader
          eyebrow="THE EDITOR"
          title="A CAT-style workbench, not a black box"
          subtitle="Every segment is yours to review, edit, comment on, and approve. No translations leave the system until you say so."
        />
        <div className="grid md:grid-cols-2 gap-12 items-center mt-14">
          <FeatureList
            items={[
              { t: "Side-by-side compare", b: "See the original document and the rebuilt translation in the same view." },
              { t: "Segment-level comments", b: "Loop in a reviewer for tricky lines. Comments live with the segment, not in email." },
              { t: "Translation memory", b: "Reuse approved translations across projects. Identical sentences cost zero credits." },
              { t: "Glossary enforcement", b: "Lock product names, legal terms, and proper nouns to your house style." },
            ]}
          />
          <EditorMock />
        </div>

        <div className="grid md:grid-cols-2 gap-12 items-center mt-20">
          <CertMock />
          <FeatureList
            items={[
              { t: "Your branding on every export", b: "Upload your company logo once. It appears at the top of every certification page." },
              { t: "Sworn translator statement", b: "Auto-generated certification page with your name, date, languages, and signature line." },
              { t: "PDF & DOCX exports", b: "Send a PDF to a court or a DOCX to a client for further edits — same layout-perfect output." },
              { t: "ISO 17100 compliant", b: "Audit trail of every segment edit, approval, and certification action." },
            ]}
          />
        </div>
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

function EditorMock() {
  return (
    <div
      style={{
        background: "#ffffff",
        border: `1px solid ${BORDER}`,
        borderRadius: 20,
        overflow: "hidden",
        boxShadow: "0 12px 32px rgba(30,30,20,0.06)",
      }}
    >
      <div
        style={{
          padding: "10px 16px",
          background: CREAM,
          borderBottom: `1px solid ${BORDER}`,
          fontSize: 11,
          color: SUBTLE,
          fontWeight: 600,
          letterSpacing: "0.1em",
        }}
      >
        EDITOR · 42 / 42 SEGMENTS APPROVED
      </div>
      <div style={{ padding: 14 }}>
        {[
          ["Comune", "Municipality"],
          ["Cognome", "Surname"],
          ["Nome", "Name"],
          ["Codice Fiscale", "Tax Code"],
          ["Cittadinanza", "Citizenship"],
        ].map(([src, tgt], i) => (
          <div
            key={i}
            className="grid grid-cols-[24px_1fr_1fr_24px] items-center gap-3"
            style={{
              padding: "10px 8px",
              borderBottom:
                i < 4 ? `1px solid ${CREAM_DARK}` : "none",
              fontSize: 12,
            }}
          >
            <div style={{ color: SUBTLE, fontFamily: "monospace", fontSize: 10 }}>
              {String(i).padStart(2, "0")}
            </div>
            <div style={{ color: TEXT }}>{src}</div>
            <div style={{ color: TEAL, fontWeight: 500 }}>{tgt}</div>
            <div
              style={{
                width: 18,
                height: 18,
                borderRadius: "50%",
                background: TEAL,
                color: "#fff",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 10,
              }}
            >
              ✓
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function CertMock() {
  return (
    <div
      style={{
        background: "#ffffff",
        border: `1px solid ${BORDER}`,
        borderRadius: 20,
        padding: 26,
        boxShadow: "0 12px 32px rgba(30,30,20,0.06)",
      }}
    >
      <div
        style={{
          width: 64,
          height: 28,
          background: CREAM_DARK,
          borderRadius: 6,
          marginBottom: 22,
        }}
      />
      <div
        style={{
          fontSize: 14,
          fontWeight: 700,
          textAlign: "center",
          marginBottom: 16,
          color: TEXT,
          letterSpacing: "0.04em",
        }}
      >
        CERTIFIED TRANSLATION STATEMENT
      </div>
      <div style={{ fontSize: 11, lineHeight: 1.6, color: MUTED }}>
        I hereby certify that the foregoing is a true and complete translation of the attached document.
      </div>
      <div style={{ marginTop: 18, fontSize: 11, color: MUTED, lineHeight: 1.8 }}>
        Translator: jane@espressotranslations.com
        <br />
        Date: 2026-05-26
        <br />
        Source language: Italian
        <br />
        Target language: English
      </div>
      <div
        style={{
          marginTop: 22,
          paddingTop: 18,
          borderTop: `1px solid ${BORDER}`,
          fontStyle: "italic",
          color: SUBTLE,
          fontSize: 11,
        }}
      >
        [Signature: Jane Doe]
      </div>
    </div>
  )
}

// ============================================================
// PRICING
// ============================================================
function Pricing({
  yearly,
  setYearly,
}: {
  yearly: boolean
  setYearly: (b: boolean) => void
}) {
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
          subtitle="Every plan includes the editor, translation memory, glossary, ISO 17100 certification, and your branding. No setup fees."
        />

        {/* Yearly toggle */}
        <div className="flex items-center justify-center gap-3 mt-8">
          <span style={{ color: yearly ? SUBTLE : TEXT, fontSize: 14, fontWeight: 500 }}>
            Monthly
          </span>
          <button
            type="button"
            onClick={() => setYearly(!yearly)}
            style={{
              width: 48,
              height: 26,
              borderRadius: 999,
              background: yearly ? TEAL : "#d8cfba",
              position: "relative",
              transition: "background 0.18s",
              cursor: "pointer",
              border: "none",
            }}
            aria-label="Toggle yearly billing"
          >
            <span
              style={{
                position: "absolute",
                top: 3,
                left: yearly ? 25 : 3,
                width: 20,
                height: 20,
                borderRadius: "50%",
                background: "#fff",
                transition: "left 0.18s",
                boxShadow: "0 1px 3px rgba(0,0,0,0.15)",
              }}
            />
          </button>
          <span style={{ color: yearly ? TEXT : SUBTLE, fontSize: 14, fontWeight: 500 }}>
            Yearly
          </span>
          <span
            style={{
              background: ACCENT_GOLD,
              color: "#fff",
              fontSize: 10,
              fontWeight: 700,
              padding: "3px 8px",
              borderRadius: 999,
              letterSpacing: "0.06em",
            }}
          >
            SAVE 20%
          </span>
        </div>

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
              "Layout-perfect rebuild",
              "DOCX & PDF export",
              "ISO 17100 certification",
              "Editor with comments + glossary",
            ]}
          />
          <PlanCard
            name="Basic"
            price={yearly ? "23" : "29"}
            period={yearly ? "/mo, billed yearly" : "/month"}
            credits="19 pages / month"
            highlight={false}
            cta="Choose Basic"
            ctaHref="/register?plan=basic"
            features={[
              "19 pages translated / month",
              "Layout-perfect rebuild",
              "DOCX & PDF export",
              "ISO 17100 certification",
              "Translation memory + glossary",
              "Email support",
            ]}
          />
          <PlanCard
            name="Pro"
            price={yearly ? "47" : "59"}
            period={yearly ? "/mo, billed yearly" : "/month"}
            credits="29 pages / month"
            highlight={true}
            cta="Choose Pro"
            ctaHref="/register?plan=pro"
            features={[
              "29 pages / month + top-up packs",
              "Layout-perfect rebuild",
              "DOCX & PDF export",
              "ISO 17100 certification",
              "Translation memory + glossary",
              "Team members & roles",
              "Side-by-side compare view",
              "Priority support",
            ]}
          />
        </div>

        {/* Credit packs */}
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
            One-off page packs — never expire
          </h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 max-w-[860px] mx-auto">
            {[
              { p: "5 pages", c: "€19" },
              { p: "20 pages", c: "€69" },
              { p: "50 pages", c: "€149" },
              { p: "100 pages", c: "€279" },
            ].map((pack) => (
              <div
                key={pack.p}
                style={{
                  background: "#ffffff",
                  border: `1px solid ${BORDER}`,
                  borderRadius: 14,
                  padding: 18,
                  textAlign: "center",
                }}
              >
                <div style={{ fontSize: 13, color: MUTED, marginBottom: 6 }}>
                  {pack.p}
                </div>
                <div style={{ fontSize: 22, fontWeight: 700, color: TEXT }}>
                  {pack.c}
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

// ============================================================
// FAQ
// ============================================================
function FAQ() {
  const [open, setOpen] = useState<number | null>(0)
  const items = [
    {
      q: "Are TraqConverter translations legally valid?",
      a: "Yes — every export ships with an ISO 17100 sworn translator certification page bearing your name, date, languages, and signature line. Accepted by embassies, courts, immigration offices, and notaries.",
    },
    {
      q: "What file formats do you support?",
      a: "PDFs (single or multi-page), scans, photos (JPG, PNG, WEBP), and Word documents. We export to DOCX and PDF with the original layout preserved.",
    },
    {
      q: "Will the layout look like the original?",
      a: "Yes — our Claude Vision OCR captures every text block, photo, stamp, signature, and table. The rebuild reproduces them in place. ID cards, certificates, and government forms come through with their structure intact.",
    },
    {
      q: "Which languages do you handle?",
      a: "90+ languages, including RTL (Arabic, Hebrew, Farsi, Urdu) and CJK (Chinese, Japanese, Korean). Auto-detect figures out the source language so you only have to pick the target.",
    },
    {
      q: "How does pricing work?",
      a: "Each page is one credit. Subscriptions include a monthly allowance (19 on Basic, 29 on Pro). Need more? Top up with credit packs that never expire. Free trial gets 1 page.",
    },
    {
      q: "Is my data safe?",
      a: "Documents are encrypted in transit and at rest, stored on EU servers, GDPR-compliant, and auto-deleted after 30 days unless you keep them. We never train models on your data.",
    },
    {
      q: "Can my team work together?",
      a: "Pro plans include team members, project assignment, segment comments, shared translation memory, and shared glossary. Roles let you keep reviewers separate from drafters.",
    },
  ]
  return (
    <section id="faq" style={{ padding: "80px 24px" }}>
      <div className="max-w-[820px] mx-auto">
        <SectionHeader
          eyebrow="QUESTIONS"
          title="Things people ask before signing up"
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

// ============================================================
// FINAL CTA
// ============================================================
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
          Start your first certified translation today
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
          Sign up free, upload a document, and download a layout-perfect translation in under five minutes.
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

// ============================================================
// FOOTER
// ============================================================
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
            AI-powered certified translations that preserve your document's layout.
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
        <div>ISO 17100 · GDPR · SOC 2 Type II in progress</div>
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

// ============================================================
// SECTION HEADER
// ============================================================
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

// ============================================================
// ICONS
// ============================================================
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

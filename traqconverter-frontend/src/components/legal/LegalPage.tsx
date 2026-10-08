import Link from "next/link"
import type { ReactNode } from "react"

import CompanyLine from "@/components/legal/CompanyLine"
import { LEGAL_LINKS } from "@/lib/company"
import { BrandMark, BrandName } from "@/components/brand/Logo"

const CREAM = "#faf5ee"
const CREAM_DARK = "#f3ecdb"
const TEAL = "#0a7870"
const TEXT = "#1f2a2e"
const MUTED = "#6b6558"
const SUBTLE = "#8a8270"
const BORDER = "#e7ddc5"

export const LAST_UPDATED = "7 October 2026"

const PROSE = [
  "[&_h2]:text-[21px] [&_h2]:font-bold [&_h2]:tracking-tight [&_h2]:mt-10 [&_h2]:mb-3 [&_h2]:scroll-mt-24",
  "[&_h3]:text-[16px] [&_h3]:font-semibold [&_h3]:mt-6 [&_h3]:mb-2",
  "[&_p]:mb-4 [&_ul]:mb-4 [&_ul]:pl-5 [&_ul]:list-disc [&_li]:mb-1.5",
  "[&_a]:underline [&_a]:underline-offset-2",
  "[&_table]:w-full [&_table]:text-[14px] [&_th]:text-left [&_th]:font-semibold [&_th]:py-2 [&_th]:pr-4",
  "[&_td]:py-2 [&_td]:pr-4 [&_td]:align-top [&_tr]:border-b [&_tr]:border-[#e7ddc5]",
].join(" ")

export default function LegalPage({
  title,
  intro,
  updated = LAST_UPDATED,
  children,
}: {
  title: string
  intro?: ReactNode
  updated?: string
  children: ReactNode
}) {
  return (
    <div style={{ background: CREAM, color: TEXT, minHeight: "100vh" }} className="flex flex-col">
      <header style={{ background: CREAM, borderBottom: `1px solid ${BORDER}` }}>
        <div className="max-w-[1200px] mx-auto flex items-center justify-between gap-3" style={{ padding: "14px 24px" }}>
          <Link href="/" className="flex items-center gap-3" aria-label="OnlineDocTranslator home">
            <BrandMark size={36} />
            <div style={{ fontSize: 16, fontWeight: 600, color: TEXT }}><BrandName /></div>
          </Link>
          <div className="flex items-center gap-1 sm:gap-3 whitespace-nowrap">
            <Link
              href="/login"
              className="hidden sm:inline-block"
              style={{ fontSize: 14, fontWeight: 500, color: TEXT, padding: "8px 16px" }}
            >
              Sign in
            </Link>
            <Link
              href="/register"
              style={{ fontSize: 14, fontWeight: 600, color: "#fff", background: TEAL, padding: "9px 18px", borderRadius: 999 }}
            >
              <span className="sm:hidden">Try free</span>
              <span className="hidden sm:inline">Start free trial</span>
            </Link>
          </div>
        </div>
      </header>

      <main className="flex-1" style={{ padding: "48px 20px 72px" }}>
        <article className="max-w-[760px] mx-auto">
          <nav className="flex flex-wrap gap-2 mb-8" aria-label="Legal documents">
            {LEGAL_LINKS.map(([label, href]) => (
              <Link
                key={href}
                href={href}
                style={{
                  fontSize: 13,
                  fontWeight: 600,
                  padding: "6px 14px",
                  borderRadius: 999,
                  border: `1px solid ${BORDER}`,
                  background: "#ffffff",
                  color: MUTED,
                }}
              >
                {label}
              </Link>
            ))}
          </nav>

          <div style={{ fontSize: 11, letterSpacing: "0.18em", color: TEAL, fontWeight: 600, marginBottom: 10 }}>
            LEGAL
          </div>
          <h1
            className="text-[34px] sm:text-[42px]"
            style={{ fontWeight: 700, letterSpacing: "-0.02em", lineHeight: 1.1, marginBottom: 10 }}
          >
            {title}
          </h1>
          <div style={{ fontSize: 13, color: SUBTLE, marginBottom: 28 }}>Last updated: {updated}</div>
          {intro && (
            <div style={{ fontSize: 17, lineHeight: 1.6, color: MUTED, marginBottom: 12 }}>{intro}</div>
          )}
          <div className={PROSE} style={{ fontSize: 15, lineHeight: 1.65, color: "#33393a" }}>
            {children}
          </div>
        </article>
      </main>

      <footer style={{ borderTop: `1px solid ${BORDER}`, background: CREAM_DARK, padding: "22px 20px" }}>
        <div className="max-w-[1200px] mx-auto">
          <CompanyLine />
        </div>
      </footer>
    </div>
  )
}

// Wide tables scroll inside their own box so the page never scrolls sideways.
export function TableScroll({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-x-auto mb-5" style={{ border: `1px solid ${BORDER}`, borderRadius: 12, background: "#ffffff", padding: "4px 14px" }}>
      {children}
    </div>
  )
}

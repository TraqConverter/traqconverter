import Link from "next/link"

import { COMPANY, LEGAL_LINKS } from "@/lib/company"

const SUBTLE = "#8a8270"
const TEXT = "#4a4638"

const DOT = (
  <span aria-hidden="true" style={{ margin: "0 0.45em" }}>
    ·
  </span>
)

// The legal identity line every public page and the app shell carry.
export default function CompanyLine({ compact = false }: { compact?: boolean }) {
  const parts = [`© 2026 ${COMPANY.name}`, `P.IVA ${COMPANY.vat}`, COMPANY.address]
  return (
    <div className="flex flex-wrap items-center gap-y-1" style={{ fontSize: compact ? 10.5 : 12, color: SUBTLE, lineHeight: 1.5 }}>
      {parts.map((p) => (
        // Each item keeps its separator, so a wrapped line never starts with a dot.
        <span key={p} className={p === COMPANY.address ? undefined : "whitespace-nowrap"}>
          {p}
          {DOT}
        </span>
      ))}
      {LEGAL_LINKS.map(([label, href], i) => (
        <span key={href} className="whitespace-nowrap">
          <Link href={href} className="hover:underline" style={{ color: TEXT }}>
            {label}
          </Link>
          {i < LEGAL_LINKS.length - 1 && DOT}
        </span>
      ))}
    </div>
  )
}

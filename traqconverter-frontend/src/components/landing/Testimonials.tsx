export type Testimonial = {
  quote: string
  name: string
  role: string
}

// Real quotes only, used with the person's permission. While this is empty the section isn't shown.
export const TESTIMONIALS: Testimonial[] = []

const TEXT = "#1f2a2e"
const MUTED = "#6b6558"
const TEAL = "#0a7870"
const BORDER = "#e7ddc5"

export default function Testimonials({ items = TESTIMONIALS }: { items?: Testimonial[] }) {
  if (items.length === 0) return null
  return (
    <section aria-labelledby="testimonials-title" style={{ padding: "72px 20px" }}>
      <div className="max-w-[1100px] mx-auto">
        <div className="text-center" style={{ fontSize: 11, letterSpacing: "0.18em", color: TEAL, fontWeight: 600 }}>
          FROM TRANSLATORS
        </div>
        <h2
          id="testimonials-title"
          className="text-center text-[28px] sm:text-[36px]"
          style={{ fontWeight: 700, letterSpacing: "-0.02em", color: TEXT, lineHeight: 1.15, marginTop: 10 }}
        >
          What translators say
        </h2>
        <ul className="grid md:grid-cols-3 gap-5 mt-10">
          {items.map((t) => (
            <li key={`${t.name}-${t.quote.slice(0, 24)}`}>
              <figure style={{ background: "#ffffff", border: `1px solid ${BORDER}`, borderRadius: 20, padding: 24, height: "100%" }}>
                <blockquote style={{ fontSize: 15, lineHeight: 1.6, color: TEXT }}>&ldquo;{t.quote}&rdquo;</blockquote>
                <figcaption style={{ marginTop: 14, fontSize: 13, color: MUTED }}>
                  <span style={{ fontWeight: 700, color: TEXT }}>{t.name}</span>
                  {t.role && <>, {t.role}</>}
                </figcaption>
              </figure>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}

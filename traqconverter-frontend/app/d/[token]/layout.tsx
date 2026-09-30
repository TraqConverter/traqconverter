import type { Metadata } from "next"

export const metadata: Metadata = {
  title: "Your translation",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
}

export default function DeliveryLayout({ children }: { children: React.ReactNode }) {
  return children
}

import type { Metadata } from "next"
import { Geist, Geist_Mono } from "next/font/google"
import "./globals.css"

import AppShell from "@/components/AppShell"
import AuthGuard from "@/components/auth/AuthGuard"

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
})

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
})

const DESCRIPTION =
  "AI first drafts of certified translations for professional translators: layout rebuilt, signatures and stamps noted, your certification page added."
const OG_IMAGE = {
  url: "/brand/og-image-1200x630.png",
  width: 1200,
  height: 630,
  alt: "OnlineDocTranslator: certified translations, layout and all. Ready for your signature.",
}

export const metadata: Metadata = {
  metadataBase: new URL("https://www.onlinedoctranslator.ai"),
  title: "OnlineDocTranslator",
  description: DESCRIPTION,
  applicationName: "OnlineDocTranslator",
  openGraph: {
    type: "website",
    siteName: "OnlineDocTranslator",
    title: "OnlineDocTranslator",
    description: DESCRIPTION,
    url: "/",
    images: [OG_IMAGE],
  },
  twitter: {
    card: "summary_large_image",
    title: "OnlineDocTranslator",
    description: DESCRIPTION,
    images: [OG_IMAGE],
  },
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable}`}
    >
      <body>
        <AuthGuard>
          <AppShell>{children}</AppShell>
        </AuthGuard>
      </body>
    </html>
  )
}
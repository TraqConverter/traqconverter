"use client"

import { useEffect } from "react"
import { useRouter } from "next/navigation"

// ============================================================
// Audit HIGH-9: a duplicate jobs page used to live here. It had
// no auth on its WS subscription and made raw fetch() calls that
// 401'd. The canonical Projects page is /jobs — this file just
// redirects so any old link still lands somewhere useful.
// ============================================================

export default function DashboardJobsRedirect() {
  const router = useRouter()
  useEffect(() => {
    router.replace("/jobs")
  }, [router])
  return null
}

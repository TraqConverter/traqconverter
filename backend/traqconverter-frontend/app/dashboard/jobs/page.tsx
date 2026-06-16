"use client"

import { useEffect } from "react"
import { useRouter } from "next/navigation"

export default function DashboardJobsRedirect() {
  const router = useRouter()
  useEffect(() => {
    router.replace("/jobs")
  }, [router])
  return null
}

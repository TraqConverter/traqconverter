"use client"

import { useEffect } from "react"
import { useRouter } from "next/navigation"

// Projects are opened from /jobs; this legacy index only forwards there.
export default function EditorIndexRedirect() {
  const router = useRouter()
  useEffect(() => {
    router.replace("/jobs")
  }, [router])
  return null
}

"use client"

import { useEffect } from "react"
import { useRouter } from "next/navigation"
import { getToken } from "@/lib/auth"

export default function Home() {
  const router = useRouter()

  useEffect(() => {
    const token = getToken()

    if (!token) {
      router.push("/login")
    } else {
      router.push("/dashboard")
    }
  }, [router])

  return (
    <div className="flex items-center justify-center h-screen" style={{ background: "#faf5ee", color: "#6b6558" }}>
      Loading...
    </div>
  )
}

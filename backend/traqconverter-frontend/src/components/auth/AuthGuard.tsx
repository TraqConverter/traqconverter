"use client"

import { ReactNode, useEffect, useState } from "react"
import { useRouter, usePathname } from "next/navigation"
import { getToken } from "@/lib/auth"

export default function AuthGuard({ children }: { children: ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()

  const [loading, setLoading] = useState(true)

  useEffect(() => {
    // Use the same helper as AppShell — checks BOTH localStorage (Remember me)
    // and sessionStorage (session-only login). Reading raw localStorage here
    // caused a /login ↔ /dashboard bounce loop for session-only logins because
    // AuthGuard saw no token while AppShell saw one.
    const token = getToken()

    const isAuthPage =
      pathname === "/login" ||
      pathname === "/register" ||
      pathname.startsWith("/auth")

    // NOT LOGGED IN → redirect
    if (!token && !isAuthPage) {
      router.replace("/login")
      return
    }

    // LOGGED IN → block login/register
    if (token && isAuthPage) {
      router.replace("/dashboard")
      return
    }

    setLoading(false)
  }, [pathname, router])

  // Prevent flicker
  if (loading) {
    return (
      <div
        className="h-screen flex items-center justify-center"
        style={{ background: "#faf5ee", color: "#6b6558" }}
      >
        Loading...
      </div>
    )
  }

  return <>{children}</>
}
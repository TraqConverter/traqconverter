"use client"

import { ReactNode, useEffect, useState } from "react"
import { useRouter, usePathname } from "next/navigation"

export default function AuthGuard({ children }: { children: ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()

  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const token = localStorage.getItem("token")

    const isAuthPage =
      pathname === "/login" ||
      pathname === "/register" ||
      pathname.startsWith("/auth")

    // ❌ NOT LOGGED IN → redirect
    if (!token && !isAuthPage) {
      router.replace("/login")
      return
    }

    // ❌ LOGGED IN → block login/register
    if (token && isAuthPage) {
      router.replace("/dashboard")
      return
    }

    setLoading(false)
  }, [pathname])

  // 🔥 Prevent flicker
  if (loading) {
    return (
      <div className="h-screen flex items-center justify-center">
        Loading...
      </div>
    )
  }

  return <>{children}</>
}
"use client"

import { ReactNode, useEffect, useSyncExternalStore } from "react"
import { usePathname, useRouter } from "next/navigation"
import { getToken } from "@/lib/auth"
import { isPublicRoute, loginUrl, safeNextPath } from "@/lib/routes"

function subscribeToStorage(onChange: () => void) {
  window.addEventListener("storage", onChange)
  return () => window.removeEventListener("storage", onChange)
}

const noopSubscribe = () => () => {}

// Client-only: the token lives in localStorage/sessionStorage, which middleware can't read.
// The server snapshot is "no token", so public pages render on the server and
// protected pages render the loading state until the client knows better.
export default function AuthGuard({ children }: { children: ReactNode }) {
  const router = useRouter()
  const pathname = usePathname() || "/"
  const token = useSyncExternalStore(subscribeToStorage, getToken, () => null)
  const hydrated = useSyncExternalStore(noopSubscribe, () => true, () => false)
  const isPublic = isPublicRoute(pathname)
  const allowed = isPublic ? !token : Boolean(token)

  useEffect(() => {
    // The hydration pass sees the server snapshot (no token); wait for the client one.
    if (allowed || !hydrated) return
    if (!token) {
      router.replace(loginUrl(pathname + window.location.search))
    } else {
      const params = new URLSearchParams(window.location.search)
      const invite = params.get("invite")
      // A signed-in user opening an invite email link accepts it instead of registering.
      router.replace(
        invite
          ? `/accept-invite?token=${encodeURIComponent(invite)}`
          : safeNextPath(params.get("next")),
      )
    }
  }, [allowed, hydrated, token, pathname, router])

  if (!allowed) {
    return (
      <div className="h-screen flex items-center justify-center" style={{ background: "#faf5ee" }}>
        <div style={{ color: "#6b6558" }}>Loading...</div>
      </div>
    )
  }

  return <>{children}</>
}

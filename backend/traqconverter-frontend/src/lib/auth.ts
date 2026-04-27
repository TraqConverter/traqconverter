// ============================================================
// AUTH TOKEN STORAGE
// - Remember me  → localStorage (survives browser restart)
// - Otherwise    → sessionStorage (cleared when tab closes)
// All reads check both stores so existing tokens keep working.
// ============================================================

const KEY = "token"
const REMEMBER_KEY = "remember"

export function setToken(token: string, remember: boolean) {
  if (typeof window === "undefined") return

  // Always clear the other store so we don't leave stale tokens
  try {
    localStorage.removeItem(KEY)
    sessionStorage.removeItem(KEY)
  } catch {}

  try {
    if (remember) {
      localStorage.setItem(KEY, token)
      localStorage.setItem(REMEMBER_KEY, "1")
    } else {
      sessionStorage.setItem(KEY, token)
      localStorage.removeItem(REMEMBER_KEY)
    }
  } catch (err) {
    console.error("AUTH STORAGE ERROR:", err)
  }
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null
  try {
    return localStorage.getItem(KEY) || sessionStorage.getItem(KEY)
  } catch {
    return null
  }
}

export function clearToken() {
  if (typeof window === "undefined") return
  try {
    localStorage.removeItem(KEY)
    sessionStorage.removeItem(KEY)
    localStorage.removeItem(REMEMBER_KEY)
  } catch {}
}

export function getRemembered(): boolean {
  if (typeof window === "undefined") return true
  try {
    return localStorage.getItem(REMEMBER_KEY) === "1"
  } catch {
    return true
  }
}



const KEY = "token"
const REMEMBER_KEY = "remember"

export function setToken(token: string, remember: boolean) {
  if (typeof window === "undefined") return

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

function isExpired(token: string): boolean {
  try {
    const payload = JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")))
    return typeof payload.exp === "number" && payload.exp * 1000 <= Date.now()
  } catch {
    return false
  }
}

// An expired session reads as signed out, so protected pages go straight to the login page.
export function getToken(): string | null {
  if (typeof window === "undefined") return null
  try {
    const token = localStorage.getItem(KEY) || sessionStorage.getItem(KEY)
    return token && !isExpired(token) ? token : null
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

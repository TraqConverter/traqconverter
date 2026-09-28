import axios from "axios"
import { getToken, clearToken } from "./auth"
import { loginUrl } from "./routes"

const DEV_FALLBACK_API_URL = "http://127.0.0.1:8000"

function resolveApiBaseUrl(): string {
  const configured = process.env.NEXT_PUBLIC_API_URL
  if (configured) return configured.replace(/\/+$/, "")
  if (process.env.NODE_ENV !== "production") return DEV_FALLBACK_API_URL
  throw new Error(
    "NEXT_PUBLIC_API_URL is not set. It is inlined at build time, so set it before `next build`.",
  )
}

let cachedBaseUrl: string | null = null

export function apiBaseUrl(): string {
  if (cachedBaseUrl === null) cachedBaseUrl = resolveApiBaseUrl()
  return cachedBaseUrl
}

export const api = axios.create()

api.interceptors.request.use((config) => {
  config.baseURL = apiBaseUrl()

  if (typeof window !== "undefined") {
    const token = getToken()

    if (token && token !== "undefined" && token !== "null") {
      if (!config.headers) config.headers = {} as typeof config.headers
      ;(config.headers as Record<string, string>).Authorization = `Bearer ${token}`
    }
  }

  return config
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (!error.response) {
      console.error("NETWORK ERROR:", error.message)
      return Promise.reject(error)
    }

    const status = error.response.status
    const url = error.config?.url || ""

    if (status === 401) {
      const isAuthRequest =
        url.includes("/login") ||
        url.includes("/register")

      if (typeof window !== "undefined") {
        const currentPath = window.location.pathname

        if (!isAuthRequest && currentPath !== "/login") {
          clearToken()
          window.location.href = loginUrl(currentPath + window.location.search)
        }
      }

      return Promise.reject(error)
    }

    console.error("API ERROR:", status, url, error.response.data)

    return Promise.reject(error)
  }
)

export const uploadDocument = async (file: File) => {
  const formData = new FormData()
  formData.append("file", file)

  const res = await api.post("/projects/upload", formData)
  return res.data
}

// For iframes, <img>, and downloads: fetch with the Authorization header and hand back
// a blob: URL. Callers must URL.revokeObjectURL() it when done.
export async function fetchObjectUrl(path: string): Promise<{ url: string; type: string }> {
  const res = await api.get<Blob>(path, { responseType: "blob" })
  const blob = res.data
  return { url: URL.createObjectURL(blob), type: blob.type }
}

export function apiErrorDetail(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return typeof detail === "string" && detail ? detail : fallback
}

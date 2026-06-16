import axios from "axios"
import { getToken, clearToken } from "./auth"

const BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000"

export const api = axios.create({
  baseURL: BASE_URL,
})

api.interceptors.request.use((config) => {
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
          window.location.href = "/login"
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

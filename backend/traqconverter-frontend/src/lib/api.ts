import axios from "axios"

// ✅ Use ENV (prevents hardcoding issues)
const BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000"

export const api = axios.create({
  baseURL: BASE_URL,
  withCredentials: false,
})

// 🔐 Attach token automatically
api.interceptors.request.use((config) => {
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("token")

    if (token) {
      config.headers = config.headers || {}
      config.headers.Authorization = `Bearer ${token}`
    }
  }

  return config
})

// 🔥 Handle errors globally
api.interceptors.response.use(
  (response) => response,
  (error) => {
    // ✅ Proper network error handling
    if (!error.response) {
      console.error("🚨 NETWORK ERROR:", error.message)

      // Optional: show UI alert
      // alert("Cannot reach backend. Is server running?")

      return Promise.reject(error)
    }

    // 🔐 Handle auth failure
    if (error.response.status === 401) {
      localStorage.removeItem("token")

      if (typeof window !== "undefined") {
        window.location.href = "/login"
      }
    }

    // 🔥 Log backend error clearly
    console.error("API ERROR:", error.response.data)

    return Promise.reject(error)
  }
)

// 📄 Upload document (FIXED)
export const uploadDocument = async (file: File) => {
  const formData = new FormData()
  formData.append("file", file)

  const res = await api.post("/projects/upload", formData, {
    headers: {
      // ✅ Let axios set boundary automatically
      // DO NOT manually set multipart boundary
      "Content-Type": "multipart/form-data",
    },
  })

  return res.data
}
import axios from "axios"

// 🔥 ALWAYS use 127.0.0.1 (more reliable than localhost)
export const api = axios.create({
  baseURL: "http://localhost:8000",
  withCredentials: false,
})

// 🔐 Attach token automatically
api.interceptors.request.use((config) => {
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("token")

    if (token) {
      // 🔥 ensure headers object exists
      config.headers = config.headers || {}
      config.headers.Authorization = `Bearer ${token}`
    }
  }

  return config
})

// 🔥 Handle auth errors globally
api.interceptors.response.use(
  (response) => response,
  (error) => {
    // 🔥 Handle network errors (important for your issue)
    if (!error.response) {
      console.error("NETWORK ERROR:", error)
      return Promise.reject(error)
    }

    if (error.response.status === 401) {
      localStorage.removeItem("token")

      if (typeof window !== "undefined") {
        window.location.href = "/login"
      }
    }

    return Promise.reject(error)
  }
)

// 📄 Upload document
export const uploadDocument = async (file: File) => {
  const formData = new FormData()
  formData.append("file", file)

  const res = await api.post("/projects/upload", formData, {
    headers: {
      "Content-Type": "multipart/form-data",
    },
  })

  return res.data
}
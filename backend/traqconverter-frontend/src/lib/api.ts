import axios from "axios"

export const api = axios.create({
  baseURL: "http://localhost:8000",
})

// 🔐 Attach token automatically
api.interceptors.request.use((config) => {
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("token")

    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
  }

  return config
})

// 🔥 Auto-handle invalid token
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
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
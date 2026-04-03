"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { api } from "@/lib/api"

export default function RegisterPage() {
  const router = useRouter()

  const [fullName, setFullName] = useState("")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [loading, setLoading] = useState(false)

  const handleRegister = async () => {
    if (!fullName || !email || !password) {
      alert("Please fill all fields")
      return
    }

    try {
      setLoading(true)

      const res = await api.post("/auth/register", {
        full_name: fullName,
        email,
        password,
      })

      const { access_token } = res.data

      localStorage.setItem("token", access_token)

      router.push("/dashboard")

    } catch (err: any) {
      console.error("REGISTER ERROR:", err)

      const message =
        err?.response?.data?.detail || "Registration failed"

      alert(message)

    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="h-screen flex items-center justify-center bg-gray-50">
      <div className="bg-white p-8 rounded-xl shadow w-96 space-y-4">

        <h1 className="text-xl font-bold">Register</h1>

        <input
          className="w-full border p-2 rounded"
          placeholder="Full Name"
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
        />

        <input
          className="w-full border p-2 rounded"
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />

        <input
          type="password"
          className="w-full border p-2 rounded"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />

        <button
          onClick={handleRegister}
          disabled={loading}
          className="w-full bg-green-600 text-white p-2 rounded disabled:opacity-50"
        >
          {loading ? "Creating..." : "Register"}
        </button>

        <p className="text-sm text-center">
          Already have an account?{" "}
          <span
            className="text-blue-600 cursor-pointer"
            onClick={() => router.push("/login")}
          >
            Login
          </span>
        </p>

      </div>
    </div>
  )
}
"use client"

import { useEffect } from "react"
import { useRouter } from "next/navigation"

export default function Home() {
  const router = useRouter()

  useEffect(() => {
    const token = localStorage.getItem("token")

    if (!token) {
      router.push("/login")
    } else {
      router.push("/dashboard")
    }
  }, [])

  return (
    <div className="flex items-center justify-center h-screen">
      Loading...
    </div>
  )
}
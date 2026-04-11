"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import DashboardLayout from "@/components/layout/DashboardLayout"
import { api } from "@/lib/api"

export default function DashboardPage() {
  const router = useRouter()

  const [loading, setLoading] = useState(true)
  const [projects, setProjects] = useState<any[]>([])
  const [stats, setStats] = useState({
    credits: 120,
    active: 0,
    completed: 0,
  })

  useEffect(() => {
    const token = localStorage.getItem("token")

    if (!token) {
      router.push("/login")
      return
    }

    fetchData()
  }, [])

  const fetchData = async () => {
    try {
      const res = await api.get("/projects")
      const data = res.data || []

      setProjects(data)

      const active = data.filter((p: any) => p.status !== "COMPLETED").length
      const completed = data.filter((p: any) => p.status === "COMPLETED").length

      setStats({
        credits: 120,
        active,
        completed,
      })

    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return <div className="p-10">Loading...</div>
  }

  return (
    <DashboardLayout>

      <div className="space-y-8">

        {/* HEADER */}
        <div className="flex justify-between items-center">
          <div>
            <h1 className="text-3xl font-bold">Dashboard</h1>
            <p className="text-gray-500">
              Welcome back. Here’s your translation overview.
            </p>
          </div>

          <button
            onClick={() => router.push("/new-translation")}
            className="bg-blue-600 text-white px-5 py-2 rounded-lg hover:scale-105 transition"
          >
            + New Translation
          </button>
        </div>

        {/* STATS */}
        <div className="grid grid-cols-3 gap-6">

          <div className="bg-white p-6 rounded-xl shadow">
            <p className="text-gray-500 text-sm">Total Credits</p>
            <p className="text-3xl font-bold mt-2">{stats.credits}</p>
          </div>

          <div className="bg-white p-6 rounded-xl shadow">
            <p className="text-gray-500 text-sm">Active Jobs</p>
            <p className="text-3xl font-bold mt-2">{stats.active}</p>
          </div>

          <div className="bg-white p-6 rounded-xl shadow">
            <p className="text-gray-500 text-sm">Completed</p>
            <p className="text-3xl font-bold mt-2">{stats.completed}</p>
          </div>

        </div>

        {/* 🔥 NEW: QUICK ACTIONS */}
        <div className="grid grid-cols-2 gap-6">

          <div
            onClick={() => router.push("/settings/glossary")}
            className="bg-white p-6 rounded-xl shadow cursor-pointer hover:shadow-md transition"
          >
            <h2 className="font-semibold text-lg mb-1">Glossary</h2>
            <p className="text-sm text-gray-500">
              Manage translation terms and enforce consistency
            </p>
          </div>

          <div
            onClick={() => router.push("/editor")}
            className="bg-white p-6 rounded-xl shadow cursor-pointer hover:shadow-md transition"
          >
            <h2 className="font-semibold text-lg mb-1">Editor Studio</h2>
            <p className="text-sm text-gray-500">
              Open and edit your translation projects
            </p>
          </div>

        </div>

        {/* ACTIVE JOBS */}
        <div className="bg-white rounded-xl shadow p-6">

          <h2 className="text-lg font-semibold mb-4">
            Active Translation Jobs
          </h2>

          <div className="space-y-4">

            {projects.length === 0 && (
              <p className="text-gray-500">No projects yet</p>
            )}

            {projects.map((p: any) => (

              <div
                key={p.id}
                onClick={() => router.push(`/editor/${p.id}`)}
                className="border p-4 rounded-lg hover:bg-gray-50 cursor-pointer transition"
              >

                <div className="flex justify-between items-center mb-2">

                  <div>
                    <p className="font-medium">
                      {p.filename || "Document"}
                    </p>
                    <p className="text-sm text-gray-500">
                      {p.source_lang || "EN"} → {p.target_lang || "EN"}
                    </p>
                  </div>

                  <span className="text-xs bg-blue-100 text-blue-600 px-2 py-1 rounded">
                    {p.status}
                  </span>

                </div>

                {/* PROGRESS BAR */}
                <div className="w-full bg-gray-200 h-2 rounded">
                  <div
                    className="bg-blue-600 h-2 rounded"
                    style={{ width: `${p.progress || 10}%` }}
                  />
                </div>

              </div>

            ))}

          </div>

        </div>

      </div>

    </DashboardLayout>
  )
}
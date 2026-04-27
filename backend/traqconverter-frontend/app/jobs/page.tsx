"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { api } from "@/lib/api"

export default function JobsPage() {
  const router = useRouter()

  const [projects, setProjects] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchJobs()
  }, [])

  const fetchJobs = async () => {
    try {
      // ✅ IMPORTANT: trailing slash to avoid 307 redirect
      const res = await api.get("/projects/")
      setProjects(res.data || [])
    } catch (err) {
      console.error("JOBS ERROR:", err)
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return <div className="p-6">Loading jobs...</div>
  }

  return (
    <div className="space-y-6">

      {/* HEADER */}
      <div>
        <h1 className="text-2xl font-semibold">Jobs</h1>
        <p className="text-gray-500 text-sm">
          All your translation jobs
        </p>
      </div>

      {/* LIST */}
      <div className="bg-white rounded-xl border shadow-sm overflow-hidden">

        {projects.length === 0 && (
          <div className="p-6 text-gray-500">
            No jobs found
          </div>
        )}

        {projects.map((p: any) => (
          <div
            key={p.id}
            onClick={() => router.push(`/editor/${p.id}`)}
            className="p-5 border-b last:border-none hover:bg-gray-50 cursor-pointer transition"
          >
            <div className="flex justify-between items-center">

              {/* LEFT */}
              <div>
                <p className="font-medium text-gray-800">
                  {p.filename || "Untitled Document"}
                </p>

                <p className="text-sm text-gray-500">
                  {p.source_lang} → {p.target_lang}
                </p>
              </div>

              {/* RIGHT */}
              <div className="text-right">

                <span className={`text-xs px-2 py-1 rounded ${
                  p.status === "COMPLETED"
                    ? "bg-green-100 text-green-600"
                    : p.status === "PROCESSING"
                    ? "bg-yellow-100 text-yellow-600"
                    : "bg-gray-100 text-gray-600"
                }`}>
                  {p.status}
                </span>

                <p className="text-xs text-gray-400 mt-1">
                  {p.progress}%
                </p>
              </div>

            </div>

            {/* PROGRESS BAR */}
            <div className="w-full bg-gray-200 h-2 rounded mt-3">
              <div
                className="bg-blue-600 h-2 rounded transition-all"
                style={{ width: `${p.progress || 0}%` }}
              />
            </div>
          </div>
        ))}

      </div>

    </div>
  )
}
"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { api } from "@/lib/api"

export default function JobsPage() {
  const router = useRouter()

  const [jobs, setJobs] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchJobs()
  }, [])

  const fetchJobs = async () => {
    try {
      const res = await api.get("/projects")
      const data = res.data || []

      // 🔥 limit results for cleaner UI
      setJobs(data.slice(0, 20))

    } catch (err) {
      console.error("JOBS ERROR:", err)
    } finally {
      setLoading(false)
    }
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case "COMPLETED":
        return "bg-green-100 text-green-600"
      case "PROCESSING":
        return "bg-blue-100 text-blue-600"
      case "FAILED":
        return "bg-red-100 text-red-600"
      case "PENDING":
        return "bg-yellow-100 text-yellow-600"
      default:
        return "bg-gray-100 text-gray-600"
    }
  }

  const getProgress = (p: any) => {
    if (p.progress !== undefined && p.progress !== null) {
      return p.progress
    }

    // fallback logic
    if (p.status === "COMPLETED") return 100
    if (p.status === "PROCESSING") return 50
    return 10
  }

  if (loading) {
    return <div className="p-6">Loading jobs...</div>
  }

  return (
    <div className="space-y-6">

      {/* HEADER */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-semibold">Translation Jobs</h1>
          <p className="text-gray-500 text-sm">
            Manage and track all translation projects
          </p>
        </div>

        <button
          onClick={() => router.push("/new-translation")}
          className="bg-blue-600 text-white px-4 py-2 rounded-lg"
        >
          New Job
        </button>
      </div>

      {/* TABLE */}
      <div className="bg-white rounded-xl shadow overflow-hidden">

        <table className="w-full text-sm">

          <thead className="bg-gray-50 text-left">
            <tr>
              <th className="p-4">File Name</th>
              <th>Status</th>
              <th>Progress</th>
              <th>Language Pair</th>
              <th>Actions</th>
            </tr>
          </thead>

          <tbody>

            {jobs.length === 0 && (
              <tr>
                <td colSpan={5} className="p-6 text-center text-gray-500">
                  No jobs found
                </td>
              </tr>
            )}

            {jobs.map((job) => {

              const progress = getProgress(job)

              return (
                <tr key={job.id} className="border-t">

                  {/* FILE */}
                  <td className="p-4 font-medium">
                    {job.filename ||
                     job.original_filename ||
                     `Project ${job.id.slice(0, 6)}`}
                  </td>

                  {/* STATUS */}
                  <td>
                    <span
                      className={`px-2 py-1 text-xs rounded ${getStatusColor(job.status)}`}
                    >
                      {job.status}
                    </span>
                  </td>

                  {/* PROGRESS */}
                  <td className="w-48">
                    <div className="flex items-center gap-2">
                      <div className="w-full bg-gray-200 h-2 rounded">
                        <div
                          className="bg-blue-600 h-2 rounded"
                          style={{ width: `${progress}%` }}
                        />
                      </div>
                      <span className="text-xs">{progress}%</span>
                    </div>
                  </td>

                  {/* LANG */}
                  <td>
                    {job.source_lang || "EN"} → {job.target_lang || "EN"}
                  </td>

                  {/* ACTIONS */}
                  <td>
                    <div className="flex gap-3 text-sm font-medium">

                      <button
                        onClick={() => router.push(`/editor/${job.id}`)}
                        className="text-blue-600 hover:underline"
                      >
                        Open
                      </button>

                      <button
                        onClick={() =>
                          window.open(
                            `http://localhost:8000/projects/${job.id}/export/pdf`,
                            "_blank"
                          )
                        }
                        className="text-green-600 hover:underline"
                      >
                        PDF
                      </button>

                      <button
                        onClick={() =>
                          window.open(
                            `http://localhost:8000/projects/${job.id}/export`,
                            "_blank"
                          )
                        }
                        className="text-purple-600 hover:underline"
                      >
                        DOCX
                      </button>

                    </div>
                  </td>

                </tr>
              )
            })}

          </tbody>

        </table>

      </div>

    </div>
  )
}
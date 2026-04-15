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

    let socket: WebSocket | null = null
    let reconnectTimeout: any = null

    const connect = () => {
      socket = new WebSocket(
        `${process.env.NEXT_PUBLIC_WS_URL}/ws/projects`
      )

      socket.onopen = () => {
        console.log("WS connected")
      }

      socket.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)

          setJobs((prev) =>
            prev.map((job) =>
              job.id === data.project_id
                ? {
                    ...job,
                    progress: data.progress ?? job.progress ?? 0,
                    status: data.status ?? job.status,
                  }
                : job
            )
          )
        } catch (err) {
          console.error("WS PARSE ERROR:", err)
        }
      }

      socket.onclose = () => {
        console.log("WS disconnected — retrying...")
        reconnectTimeout = setTimeout(connect, 2000)
      }

      socket.onerror = (err) => {
        console.error("WS ERROR:", err)
        socket?.close()
      }
    }

    connect()

    return () => {
      if (socket) socket.close()
      if (reconnectTimeout) clearTimeout(reconnectTimeout)
    }
  }, [])

  const fetchJobs = async () => {
    try {
      const res = await api.get("/projects")
      const data = res.data || []

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

  const getProgress = (job: any) => {
    if (job.progress !== undefined) return job.progress
    if (job.status === "COMPLETED") return 100
    if (job.status === "PROCESSING") return 50
    return 0
  }

  if (loading) {
    return <div className="p-6">Loading jobs...</div>
  }

  return (
    <div className="space-y-6">

      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-semibold">Translation Jobs</h1>
          <p className="text-gray-500 text-sm">
            Live progress updates enabled
          </p>
        </div>

        <button
          onClick={() => router.push("/new-translation")}
          className="bg-blue-600 text-white px-4 py-2 rounded-lg"
        >
          New Job
        </button>
      </div>

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
              const isReady = progress === 100

              return (
                <tr key={job.id} className="border-t">

                  <td className="p-4 font-medium">
                    {job.file_name || job.filename || `Project ${job.id.slice(0, 6)}`}
                  </td>

                  <td>
                    <span
                      className={`px-2 py-1 text-xs rounded ${getStatusColor(job.status)}`}
                    >
                      {job.status}
                    </span>
                  </td>

                  <td className="w-48">
                    <div className="flex items-center gap-2">
                      <div className="w-full bg-gray-200 h-2 rounded overflow-hidden">
                        <div
                          className={`h-2 rounded transition-all duration-500 ${
                            isReady ? "bg-green-600" : "bg-blue-600"
                          }`}
                          style={{ width: `${progress}%` }}
                        />
                      </div>
                      <span className="text-xs font-medium">
                        {progress}%
                      </span>
                    </div>
                  </td>

                  <td>
                    {job.source_language || job.source_lang || "EN"} →{" "}
                    {job.target_language || job.target_lang || "EN"}
                  </td>

                  <td>
                    <div className="flex gap-3 text-sm font-medium">

                      <button
                        disabled={!isReady}
                        onClick={() => router.push(`/editor/${job.id}`)}
                        className={`${
                          isReady
                            ? "text-blue-600 hover:underline"
                            : "text-gray-400 cursor-not-allowed"
                        }`}
                      >
                        Open
                      </button>

                      <button
                        disabled={!isReady}
                        onClick={() =>
                          window.open(
                            `${process.env.NEXT_PUBLIC_API_URL}/projects/${job.id}/export/pdf`,
                            "_blank"
                          )
                        }
                        className={`${
                          isReady
                            ? "text-green-600 hover:underline"
                            : "text-gray-400"
                        }`}
                      >
                        PDF
                      </button>

                      <button
                        disabled={!isReady}
                        onClick={() =>
                          window.open(
                            `${process.env.NEXT_PUBLIC_API_URL}/projects/${job.id}/export`,
                            "_blank"
                          )
                        }
                        className={`${
                          isReady
                            ? "text-purple-600 hover:underline"
                            : "text-gray-400"
                        }`}
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
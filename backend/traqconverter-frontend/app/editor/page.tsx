"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { api } from "@/lib/api"

export default function EditorSelectorPage() {
  const [projects, setProjects] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchProjects()
  }, [])

  const fetchProjects = async () => {
    try {
      const res = await api.get("/projects")
      setProjects(res.data || [])
    } catch (err) {
      console.error("PROJECT FETCH ERROR:", err)
    } finally {
      setLoading(false)
    }
  }

  // 🔄 Auto refresh
  useEffect(() => {
    const interval = setInterval(fetchProjects, 5000)
    return () => clearInterval(interval)
  }, [])

  if (loading) {
    return <div className="p-6">Loading projects...</div>
  }

  return (
    <div className="space-y-6">

      {/* HEADER */}
      <div>
        <h1 className="text-2xl font-semibold">Editor Studio</h1>
        <p className="text-gray-500 text-sm">
          Select a project to start editing
        </p>
      </div>

      {/* EMPTY STATE */}
      {projects.length === 0 && (
        <div className="bg-white rounded-xl p-10 text-center shadow">
          <p className="text-gray-500">No projects yet</p>
        </div>
      )}

      {/* GRID */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">

        {projects.map((project: any) => {
          const isProcessing = project.status === "PROCESSING"
          const isCompleted = project.status === "COMPLETED"

          return (
            <Link
              key={project.id}
              href={isCompleted ? `/editor/${project.id}` : "#"}
              className={`
                group bg-white border rounded-2xl p-5 shadow-sm transition-all
                ${isCompleted
                  ? "hover:shadow-lg hover:-translate-y-1 cursor-pointer"
                  : "opacity-70 cursor-not-allowed"}
              `}
            >

              {/* TOP ROW */}
              <div className="flex justify-between items-start mb-4">

                <div>
                  <h2 className="font-semibold text-gray-800 group-hover:text-blue-600 transition">
                    {project.file_name || "Untitled Project"}
                  </h2>

                  <p className="text-sm text-gray-500 mt-1">
                    {project.source_language} → {project.target_language}
                  </p>
                </div>

                {/* STATUS BADGE */}
                <div>
                  {isProcessing && (
                    <span className="text-xs px-2 py-1 rounded bg-yellow-100 text-yellow-700">
                      Processing
                    </span>
                  )}

                  {isCompleted && (
                    <span className="text-xs px-2 py-1 rounded bg-green-100 text-green-700">
                      Ready
                    </span>
                  )}
                </div>

              </div>

              {/* PROGRESS BAR */}
              <div className="mb-4">
                <div className="w-full bg-gray-200 h-2 rounded">
                  <div
                    className="bg-blue-600 h-2 rounded transition-all"
                    style={{
                      width: `${project.progress_percent || (isCompleted ? 100 : 20)}%`
                    }}
                  />
                </div>
              </div>

              {/* FOOTER */}
              <div className="flex justify-between items-center text-sm">

                <span className="text-gray-400">
                  {isCompleted ? "Click to open" : "Processing..."}
                </span>

                <span className="text-blue-600 font-medium">
                  {isCompleted ? "Open →" : "..."}
                </span>

              </div>

            </Link>
          )
        })}

      </div>

      {/* REFRESH */}
      <button
        onClick={fetchProjects}
        className="text-sm text-blue-600 hover:underline"
      >
        Refresh
      </button>

    </div>
  )
}
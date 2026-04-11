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
      setProjects(res.data)
    } catch (err) {
      console.error("PROJECT FETCH ERROR:", err)
    } finally {
      setLoading(false)
    }
  }

  // 🔄 Optional auto-refresh (for async jobs)
  useEffect(() => {
    const interval = setInterval(() => {
      fetchProjects()
    }, 5000) // every 5 sec

    return () => clearInterval(interval)
  }, [])

  if (loading) {
    return <div className="p-6">Loading projects...</div>
  }

  if (!projects || projects.length === 0) {
    return (
      <div className="p-6">
        <p>No projects found</p>
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6">

      {/* HEADER */}
      <div>
        <h1 className="text-2xl font-semibold">Editor Studio</h1>
        <p className="text-gray-500 text-sm">
          Select a project to start editing
        </p>
      </div>

      {/* PROJECT LIST */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {projects.map((project: any) => {

          const isProcessing = project.status === "processing"
          const isCompleted = project.status === "completed"

          return (
            <Link
              key={project.id}
              href={isCompleted ? `/editor/${project.id}` : "#"}
              className={`border rounded-xl p-4 bg-white shadow-sm transition 
                ${isCompleted ? "hover:shadow-md cursor-pointer" : "opacity-60 cursor-not-allowed"}
              `}
            >
              <div className="flex justify-between items-center">

                <div>
                  <h2 className="font-medium text-gray-800">
                    {project.name || "Untitled Project"}
                  </h2>

                  <p className="text-sm text-gray-500">
                    {project.source_language} → {project.target_language}
                  </p>

                  {/* 🔥 STATUS */}
                  <p className="text-xs mt-1">
                    {isProcessing && <span className="text-yellow-600">Processing...</span>}
                    {isCompleted && <span className="text-green-600">Ready</span>}
                  </p>
                </div>

                <div className="text-xs text-gray-400">
                  {isCompleted ? "Open →" : "..."}
                </div>

              </div>
            </Link>
          )
        })}
      </div>

      {/* 🔄 Manual refresh */}
      <button
        onClick={fetchProjects}
        className="text-sm text-blue-600 hover:underline"
      >
        Refresh
      </button>

    </div>
  )
}
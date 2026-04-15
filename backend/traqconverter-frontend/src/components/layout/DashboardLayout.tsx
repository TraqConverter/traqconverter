"use client"

import { ReactNode } from "react"
import { useRouter, usePathname } from "next/navigation"

export default function DashboardLayout({
  children,
}: {
  children: ReactNode
}) {
  const router = useRouter()
  const pathname = usePathname()

  const navItems = [
    { name: "Dashboard", path: "/dashboard" },
    { name: "New Translation", path: "/new-translation" },

    // 🔥 ADDED JOBS
    { name: "Jobs", path: "/dashboard/jobs" },

    { name: "Editor Studio", path: "/editor" },

    { name: "Billing", path: "/billing" },
  ]

  const handleLogout = () => {
    localStorage.removeItem("token")
    router.push("/login")
  }

  return (
    <div className="flex h-screen bg-gray-100">

      {/* SIDEBAR */}
      <div className="w-64 bg-white border-r p-6 flex flex-col justify-between">

        <div>
          <h1 className="text-xl font-bold mb-8">
            TraqConverter
          </h1>

          <nav className="space-y-2">
            {navItems.map((item) => (
              <button
                key={item.path}
                onClick={() => router.push(item.path)}
                className={`w-full text-left px-4 py-2 rounded-lg transition ${
                  pathname === item.path || pathname.startsWith(item.path + "/")
                    ? "bg-blue-600 text-white"
                    : "hover:bg-gray-100"
                }`}
              >
                {item.name}
              </button>
            ))}
          </nav>
        </div>

        {/* LOGOUT */}
        <button
          onClick={handleLogout}
          className="text-sm text-red-500 hover:underline"
        >
          Logout
        </button>

      </div>

      {/* MAIN AREA */}
      <div className="flex-1 flex flex-col">

        {/* HEADER */}
        <div className="bg-white border-b px-6 py-4 flex justify-between items-center">

          <input
            placeholder="Search documents, translations..."
            className="border rounded-lg px-4 py-2 w-96 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />

          <div className="flex items-center gap-4">

            {/* Credits */}
            <div className="bg-green-100 text-green-700 px-4 py-1 rounded-full text-sm font-medium">
              120 Credits
            </div>

            {/* Avatar */}
            <div className="w-9 h-9 bg-gray-300 rounded-full flex items-center justify-center text-sm font-semibold">
              U
            </div>

          </div>

        </div>

        {/* CONTENT */}
        <div className="flex-1 overflow-y-auto p-6">
          {children}
        </div>

      </div>

    </div>
  )
}
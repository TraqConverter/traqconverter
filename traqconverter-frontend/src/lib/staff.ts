// Mirrors STAFF_ROLES in backend/app/services/ai_actions.py.
const STAFF_ROLES = ["SUPERUSER", "SUPER_ADMIN", "ADMIN"]

export function isStaffRole(role: string | null | undefined): boolean {
  return STAFF_ROLES.includes((role || "").toUpperCase())
}

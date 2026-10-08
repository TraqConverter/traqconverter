"""Platform staff roles (User.role). Not team roles, which live on TeamMember.role."""

STAFF_ROLES = frozenset({"SUPERUSER", "SUPER_ADMIN", "ADMIN"})

# Team roles that may manage the team's billing, payments and stamp, besides the owner.
TEAM_MANAGER_ROLES = frozenset({"ADMIN"})

# Team roles that, besides the owner, may certify, rerun, regenerate, unlock client links and bulk-delete.
TEAM_LEAD_ROLES = frozenset({"ADMIN", "PM"})


def is_staff(user) -> bool:
    return (getattr(user, "role", None) or "").upper() in STAFF_ROLES

"""Platform staff roles (User.role). Not team roles, which live on TeamMember.role."""

STAFF_ROLES = frozenset({"SUPERUSER", "SUPER_ADMIN", "ADMIN"})

# Team roles that may manage the team's billing, payments and stamp, besides the owner.
TEAM_MANAGER_ROLES = frozenset({"ADMIN"})


def is_staff(user) -> bool:
    return (getattr(user, "role", None) or "").upper() in STAFF_ROLES

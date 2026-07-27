from pydantic import BaseModel

# =========================
# GRANT / REVOKE A SINGLE EDGE
# (one role <-> permission connection on the graph)
# =========================


class PermissionGrant(BaseModel):
    role_id: str
    permission_id: str


# =========================
# BULK REPLACE — "set this role's permissions to exactly this list"
# Used when the UI saves a role node after the user has connected /
# disconnected several permission nodes to it in one editing session.
# =========================


class RolePermissionsBulkUpdate(BaseModel):
    permission_ids: list[str]

"""
Backward-compatible shim. The real implementation now lives in
app.core.audit (single, unified audit logger used across the whole
backend). Kept so existing `from app.core.helpers.audit_helper import
create_audit_log` imports keep working.
"""

from app.core.audit import create_audit_log, record_audit_log  # noqa: F401

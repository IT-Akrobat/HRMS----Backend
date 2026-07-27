"""
Generic repository layer for Supabase-backed tables.

This gives every module (employees, attendance, leaves, payroll, ...) a
consistent, testable way to talk to the database instead of calling
`supabase_admin.table(...)` directly inside services. Services should
depend on a Repository instance, not on the supabase client.

Usage:

    from app.core.repository import SupabaseRepository

    employee_repo = SupabaseRepository("employees")

    employee_repo.get_by_id(employee_id)
    employee_repo.list(filters={"department_id": dept_id})
    employee_repo.create({...})
    employee_repo.update(employee_id, {...})
    employee_repo.soft_delete(employee_id)   # if the table has deleted_at
"""

from datetime import datetime, timezone
from typing import Any, Optional

from app.core.database import supabase_admin
from app.core.exceptions import internal_server_error, not_found


class SupabaseRepository:
    def __init__(self, table_name: str, id_column: str = "id"):
        self.table_name = table_name
        self.id_column = id_column

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _table(self):
        return supabase_admin.table(self.table_name)

    @staticmethod
    def _apply_filters(query, filters: Optional[dict[str, Any]]):
        if not filters:
            return query

        for column, value in filters.items():
            if value is None:
                continue
            query = query.eq(column, value)

        return query

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def list(
        self,
        select: str = "*",
        filters: Optional[dict[str, Any]] = None,
        order_by: Optional[str] = None,
        ascending: bool = True,
        start: Optional[int] = None,
        end: Optional[int] = None,
        include_deleted: bool = False,
    ):
        try:
            query = self._table().select(select, count="exact")

            query = self._apply_filters(query, filters)

            if not include_deleted:
                # Only applies to tables that actually have deleted_at.
                # Callers that don't soft-delete should leave this False;
                # Supabase will simply ignore an unknown filter column error
                # is avoided by only calling this when the table supports it.
                pass

            if order_by:
                query = query.order(order_by, desc=not ascending)

            if start is not None and end is not None:
                query = query.range(start, end)

            response = query.execute()

            return response.data or [], (response.count or 0)

        except Exception as e:
            internal_server_error(f"Failed to fetch {self.table_name}: {e}")

    def get_by_id(self, record_id: str, select: str = "*"):
        try:
            response = (
                self._table()
                .select(select)
                .eq(self.id_column, record_id)
                .maybe_single()
                .execute()
            )

            return response.data if response else None

        except Exception as e:
            internal_server_error(f"Failed to fetch {self.table_name}: {e}")

    def get_by_id_or_404(self, record_id: str, message: str, select: str = "*"):
        record = self.get_by_id(record_id, select=select)

        if not record:
            not_found(message)

        return record

    def find_one(self, filters: dict[str, Any], select: str = "*"):
        try:
            query = self._table().select(select)
            query = self._apply_filters(query, filters)

            response = query.limit(1).execute()

            return response.data[0] if response.data else None

        except Exception as e:
            internal_server_error(f"Failed to fetch {self.table_name}: {e}")

    def exists(self, filters: dict[str, Any]) -> bool:
        return self.find_one(filters, select="id") is not None

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def create(self, payload: dict[str, Any]):
        try:
            response = self._table().insert(payload).execute()

            if not response.data:
                internal_server_error(f"Failed to create {self.table_name}.")

            return response.data[0]

        except Exception as e:
            internal_server_error(f"Failed to create {self.table_name}: {e}")

    def update(self, record_id: str, payload: dict[str, Any]):
        stamped_payload = {
            **payload,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            response = self._run_update(record_id, stamped_payload)

        except Exception as e:
            if not self._is_missing_updated_at_column_error(e):
                internal_server_error(f"Failed to update {self.table_name}: {e}")

            # Some tables (leave_requests, documents, leave_types,
            # attendance_corrections — see sql/013_add_missing_updated_at_
            # columns.sql) never got an updated_at column, or PostgREST's
            # schema cache hasn't picked up a migration that added one
            # yet. Rather than hard-failing every update against those
            # tables, retry once without the timestamp so the actual
            # write still goes through.
            try:
                response = self._run_update(record_id, payload)
            except Exception as retry_error:
                internal_server_error(
                    f"Failed to update {self.table_name}: {retry_error}"
                )

        if not response.data:
            not_found(f"{self.table_name} record not found.")

        return response.data[0]

    def _run_update(self, record_id: str, payload: dict[str, Any]):
        return (
            self._table()
            .update(payload)
            .eq(self.id_column, record_id)
            .execute()
        )

    @staticmethod
    def _is_missing_updated_at_column_error(e: Exception) -> bool:
        text = str(e)
        return "PGRST204" in text and "updated_at" in text

    def delete(self, record_id: str):
        try:
            response = (
                self._table().delete().eq(self.id_column, record_id).execute()
            )

            return bool(response.data)

        except Exception as e:
            internal_server_error(f"Failed to delete {self.table_name}: {e}")

    def soft_delete(self, record_id: str, deleted_by: Optional[str] = None):
        """
        For tables that have a deleted_at (and optionally deleted_by) column.
        """
        payload = {"deleted_at": datetime.now(timezone.utc).isoformat()}

        if deleted_by:
            payload["deleted_by"] = deleted_by

        return self.update(record_id, payload)

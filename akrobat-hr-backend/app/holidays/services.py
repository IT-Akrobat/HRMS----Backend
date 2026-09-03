from datetime import date, datetime, time, timedelta
from io import BytesIO
from typing import Optional

import openpyxl
from fastapi import HTTPException, UploadFile

from app.core.database import supabase_admin
from app.core.responses import success_response
from app.core.logger import logger
from app.core.helpers.employee_helper import get_employee_id_for_auth_user
from app.notifications.services import notify_employee
from app.notification_preferences.services import get_preference


def _apply_sunday_shift(raw_date: date) -> tuple[date, bool]:
    """
    MOM's rule: a public holiday that falls on a Sunday is observed the
    following Monday. Returns (observed_date, was_shifted).
    """

    if raw_date.weekday() == 6:  # Monday=0 ... Sunday=6
        return raw_date + timedelta(days=1), True

    return raw_date, False


# Column headers this accepts, matched case-insensitively with spaces/
# underscores collapsed -- so "Holiday Name", "holiday_name" and "Name"
# all land on the same key. Keeps the uploaded sheet forgiving instead
# of demanding one exact header row.
_COLUMN_ALIASES = {
    "name": {"holidayname", "name", "holiday", "title"},
    "date": {
        "date",
        "holidaydate",
        "rawdate",
        "rawholidaydate",
        "calendardate",
    },
    "description": {"description", "desc", "notes", "remarks"},
    "country": {"country", "calendar", "countrycode"},
}

_DATE_FORMATS = (
    "%Y-%m-%d",  # 2026-01-01 (ISO)
    "%d/%m/%Y",  # 01/01/2026 (day-first -- SG/IN convention)
    "%d-%m-%Y",
    "%d %b %Y",  # 01 Jan 2026
    "%d %B %Y",  # 01 January 2026
    "%m/%d/%Y",  # tried last -- US month-first, only if the above miss
)


def _normalize_header(value) -> str:
    return "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum())


def _parse_cell_date(value) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def import_holidays_from_excel(file: UploadFile, default_country: str = "SG"):
    """
    HR Admin/Super Admin: upload an .xlsx sheet of public holidays
    instead of typing them in one by one or hand-building the JSON for
    bulk_import_holidays() above. Expected columns (any order, any of
    the header spellings in _COLUMN_ALIASES): Holiday Name, Date,
    Description (optional), Country (optional, defaults to
    `default_country`). Reuses the same Sunday-shift + raw-date-keeping
    logic as the JSON bulk-import path, then does ONE insert for every
    valid row so this is atomic per-upload rather than partially landing
    in Supabase row-by-row.

    Rows that are missing a name/date, or whose date cell couldn't be
    parsed, are skipped and reported back in `data.errors` (1-indexed
    against the spreadsheet, header row counted as row 1) instead of
    failing the whole upload -- so one typo doesn't block every other
    correct row in the same file.
    """

    filename = (file.filename or "").lower()
    if not filename.endswith((".xlsx", ".xlsm")):
        raise HTTPException(
            status_code=400,
            detail="Please upload an .xlsx file (Excel 97-2003 .xls is not supported).",
        )

    try:
        contents = file.file.read()
        workbook = openpyxl.load_workbook(BytesIO(contents), data_only=True)
    except Exception:
        raise HTTPException(
            status_code=400, detail="Could not read that file as an Excel workbook."
        )

    sheet = workbook.active
    rows_iter = sheet.iter_rows(values_only=True)

    try:
        header_row = next(rows_iter)
    except StopIteration:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    col_index: dict[str, int] = {}
    for idx, raw_header in enumerate(header_row):
        key = _normalize_header(raw_header)
        for field, aliases in _COLUMN_ALIASES.items():
            if key in aliases and field not in col_index:
                col_index[field] = idx

    if "name" not in col_index or "date" not in col_index:
        raise HTTPException(
            status_code=400,
            detail=(
                "Couldn't find a 'Holiday Name' and 'Date' column in the first "
                "row. Expected headers: Holiday Name, Date, Description "
                "(optional), Country (optional)."
            ),
        )

    def cell(row, field):
        idx = col_index.get(field)
        if idx is None or idx >= len(row):
            return None
        return row[idx]

    rows_to_insert = []
    errors = []

    for sheet_row_num, row in enumerate(rows_iter, start=2):
        if row is None or all(v is None or str(v).strip() == "" for v in row):
            continue  # blank row -- skip silently, not an error

        name = cell(row, "name")
        name = str(name).strip() if name is not None else ""
        raw_date = _parse_cell_date(cell(row, "date"))

        if not name:
            errors.append(f"Row {sheet_row_num}: missing holiday name.")
            continue
        if raw_date is None:
            errors.append(
                f"Row {sheet_row_num}: missing or unreadable date "
                "(expected YYYY-MM-DD or DD/MM/YYYY)."
            )
            continue

        description = cell(row, "description")
        description = str(description).strip() if description else None
        country = cell(row, "country")
        country = str(country).strip().upper() if country else default_country

        observed_date, was_shifted = _apply_sunday_shift(raw_date)
        rows_to_insert.append(
            {
                "holiday_name": name,
                "holiday_date": str(observed_date),
                "raw_holiday_date": str(raw_date),
                "is_sunday_shifted": was_shifted,
                "description": description,
                "country": country,
            }
        )

    if not rows_to_insert:
        return success_response(
            message="No valid holiday rows found in that file.",
            data={"imported": [], "errors": errors},
        )

    try:
        response = supabase_admin.table("holidays").insert(rows_to_insert).execute()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    imported = response.data or []
    message = f"{len(imported)} holiday(s) imported."
    if errors:
        message += f" {len(errors)} row(s) skipped -- see details."

    return success_response(
        message=message,
        data={"imported": imported, "errors": errors},
    )


def create_holiday(data):

    try:

        response = (
            supabase_admin.table("holidays")
            .insert(
                {
                    "holiday_name": data.holiday_name,
                    "holiday_date": data.holiday_date,
                    "description": data.description,
                    "country": data.country,
                }
            )
            .execute()
        )

        return success_response(
            message="Holiday created successfully.", data=response.data[0]
        )

    except Exception as e:

        raise HTTPException(status_code=400, detail=str(e))


def bulk_import_holidays(items):
    """
    Populate `holidays` from a yearly source list (e.g. MOM's public
    holiday list). Each item's raw calendar date is Sunday-shifted here
    if needed -- holiday_date always ends up holding the actually
    OBSERVED date (what attendance/leave logic should treat as the day
    off), never the raw calendar date, per policy. raw_holiday_date is
    kept alongside it so Replacement Leave crediting can still detect a
    holiday that really fell on a Saturday.
    """

    try:
        rows = []

        for item in items:
            observed_date, was_shifted = _apply_sunday_shift(item.raw_holiday_date)

            rows.append(
                {
                    "holiday_name": item.holiday_name,
                    "holiday_date": str(observed_date),
                    "raw_holiday_date": str(item.raw_holiday_date),
                    "is_sunday_shifted": was_shifted,
                    "description": item.description,
                    "country": item.country,
                }
            )

        response = supabase_admin.table("holidays").insert(rows).execute()

        return success_response(
            message=f"{len(response.data or [])} holiday(s) imported.",
            data=response.data or [],
        )

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


def get_saturday_holidays(country: str = "SG", year: int | None = None):
    """
    Public holidays whose REAL calendar date (raw_holiday_date, or
    holiday_date if raw wasn't recorded) fell on a Saturday -- the
    candidates HR credits Replacement Leave for. See
    app/leaves/policy_services.py credit_replacement_leave().
    """

    query = supabase_admin.table("holidays").select("*").eq("country", country)

    if year:
        query = query.gte("holiday_date", f"{year}-01-01").lte(
            "holiday_date", f"{year}-12-31"
        )

    response = query.order("holiday_date").execute()

    saturday_holidays = [
        row
        for row in (response.data or [])
        if date.fromisoformat(
            row.get("raw_holiday_date") or row["holiday_date"]
        ).weekday()
        == 5  # Saturday
    ]

    return success_response(
        message="Saturday public holidays fetched successfully.",
        data=saturday_holidays,
    )


def get_holidays(country=None):

    query = supabase_admin.table("holidays").select("*")

    if country:
        query = query.eq("country", country)

    response = query.order("holiday_date").execute()

    return {"success": True, "data": response.data}


def get_holiday(holiday_id: str):

    response = (
        supabase_admin.table("holidays")
        .select("*")
        .eq("id", holiday_id)
        .single()
        .execute()
    )

    return success_response(message="Holiday fetched successfully.", data=response.data)


def update_holiday(holiday_id: str, data: dict):

    response = (
        supabase_admin.table("holidays").update(data).eq("id", holiday_id).execute()
    )

    return success_response(
        message="Holiday updated successfully.", data=response.data[0]
    )


def delete_holiday(holiday_id: str):

    (supabase_admin.table("holidays").delete().eq("id", holiday_id).execute())

    return {"message": "Holiday deleted successfully"}


# =========================
# HOLIDAY REMINDER
# =========================
#
# Self-service "is a holiday coming up?" check -- same "no background
# scheduler exists in this backend" constraint as
# attendance.get_attendance_reminder_status() / notifications.
# get_celebrations_status() (see those docstrings), so this is polled by
# the frontend (Header.jsx, alongside the other reminder polls) instead
# of running on a cron.
#
# Deliberately checks BOTH tomorrow's date and today's:
#   - tomorrow's holiday(s) fire an ADVANCE notice ("tomorrow is a
#     holiday") the day before, so people aren't finding out the morning
#     of -- this is the main point of the feature.
#   - today's holiday(s) also fire a same-day notice, as a fallback for
#     anyone who didn't get the advance one (holiday added same-day,
#     employee joined after the advance notice already went out, etc.)
#     so the information is never simply missed.
#
# Gated by the requesting employee's own "Holiday reminders" preference
# (defaults to ON -- see notification_preferences DEFAULTS -- since this
# is informational, not a nag). No country filter: employees aren't
# tagged with a country in this schema, so every holiday row is treated
# as relevant to everyone rather than silently hiding one calendar's
# holidays from staff who happen to be on the other.


def get_holiday_reminder_status(auth_user_id: str):
    try:
        employee_id = get_employee_id_for_auth_user(auth_user_id)
        if not employee_id:
            return success_response(
                message="No holiday reminder due.", data={"holidays": []}
            )

        if not get_preference(employee_id, "holiday_reminders"):
            return success_response(
                message="No holiday reminder due.", data={"holidays": []}
            )

        today = date.today()
        tomorrow = today + timedelta(days=1)

        try:
            response = (
                supabase_admin.table("holidays")
                .select("holiday_name, holiday_date")
                .in_("holiday_date", [today.isoformat(), tomorrow.isoformat()])
                .execute()
            )
            rows = response.data or []
        except Exception as e:
            logger.error(f"Unable to check upcoming holidays: {e}")
            return success_response(
                message="No holiday reminder due.", data={"holidays": []}
            )

        if not rows:
            return success_response(
                message="No holiday reminder due.", data={"holidays": []}
            )

        due = []
        for row in rows:
            name = row.get("holiday_name") or "a company holiday"
            holiday_date = row.get("holiday_date")
            if holiday_date == tomorrow.isoformat():
                due.append(
                    {
                        "title": "Holiday Tomorrow",
                        "message": (
                            f"Due to {name}, tomorrow "
                            f"({tomorrow.strftime('%d %b %Y')}) is a holiday."
                        ),
                    }
                )
            elif holiday_date == today.isoformat():
                due.append(
                    {
                        "title": "Holiday Today",
                        "message": f"Due to {name}, today is a holiday.",
                    }
                )

        if not due:
            return success_response(
                message="No holiday reminder due.", data={"holidays": []}
            )

        # Dedup per requesting employee per day, same idea as the
        # attendance reminder's / celebrations' notification-row dedup.
        day_start = datetime.combine(today, time(0, 0)).isoformat()
        already_sent = (
            supabase_admin.table("notifications")
            .select("message")
            .eq("user_id", employee_id)
            .eq("notification_type", "HOLIDAY_REMINDER")
            .gte("created_at", day_start)
            .execute()
        )
        already_sent_messages = {
            row.get("message") for row in (already_sent.data or [])
        }

        sent = []
        for item in due:
            if item["message"] in already_sent_messages:
                continue
            notify_employee(
                employee_id,
                title=item["title"],
                message=item["message"],
                notification_type="HOLIDAY_REMINDER",
            )
            sent.append(item["message"])

        return success_response(
            message="Holiday reminders checked.",
            data={"holidays": sent},
        )

    except HTTPException:
        raise

    except Exception as e:
        # Best-effort background check -- never let this bubble up as a
        # 500 to a page that's just polling.
        logger.error(f"Holiday reminder check failed for {auth_user_id}: {e}")
        return success_response(
            message="No holiday reminder due.", data={"holidays": []}
        )

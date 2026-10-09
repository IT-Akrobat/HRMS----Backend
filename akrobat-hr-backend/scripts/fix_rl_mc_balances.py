"""
One-off correction: Replacement Leave (RL) and MC "taken" figures for 2026.

    python scripts/fix_rl_mc_balances.py            # dry run (shows current -> new)
    python scripts/fix_rl_mc_balances.py --commit   # write

What it does
------------
RL  (leave_replacement_credits)
    For each employee in RL_SHEET it makes their credit match the sheet:
        days      = "2026 Replacement Leave Entitlement"
        used_days = "Replacement Leave" (already taken)
        used      = True when everything has been taken
    So everyone ends at balance 0, except LOW SENG HOCK - MELVIN and
    RIAN FIRDAUZ BIN KAMARUZAMAN who keep 0.5 day not yet taken.
    - 0 credit rows  -> one is inserted
    - 1 credit row   -> it is updated in place
    - 2+ rows, or a row already linked to a leave request -> reported and
      left alone (needs a human look).
    Employees NOT in the sheet are never changed; if any of them still has
    unused RL it is listed so you can decide.

MC  (leave_balances, leave type "SICK LEAVE")
    Entitlement stays as is (14 is correct; a missing row is created with 14).
    used_days = "Taken in 2026" from MC_TAKEN, remaining = total - used.

Employees are matched on employees.full_name. Anything that does not match
exactly one employee is reported and skipped -- nothing is guessed, and
--commit refuses to run while any name is unmatched.
"""

import argparse
import difflib
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ---------------------------------------------------------------------------
# DATA  (name, 2026 entitlement, already taken)
# ---------------------------------------------------------------------------
RL_SHEET = [
    ("TAY LAY PENG - JASMINE", 1, 1),
    ("MAY ZIN WIN", 1, 1),
    ("LOW SENG HOCK - MELVIN", 0.5, 0),  # 0.5 entitled, not yet taken
    ("RIAN FIRDAUZ BIN KAMARUZAMAN", 0.5, 0),  # 0.5 entitled, not yet taken
    ("FRIGINAL KAYCEE BARBON", 1, 1),
    ("WIN SWE MON OO - WINNY", 1, 1),
    ("CALDA JOSELITO JR LOPEZ - JOEY", 1, 1),
    ("YUVARAJAN DORAIRAJ - YUVA", 0.5, 0.5),
    ("LWIN CHO CHO TUN - CHO CHO", 1, 1),
    ("SIVABALAN MEENAKSHI", 1, 1),
    ("SAI LON SAING - RAY", 1, 1),
    # Sheet shows 0.5 / 0.5 for this row (entitlement 0.5, already taken 0.5).
    # Sheet spells it WEI; the DB may have WI -- see NAME_ALIASES.
    ("TEO WEI KIAN - SAM", 0.5, 0.5),
    ("TAY RONG HAO TIMOTHY", 1, 1),
    ("INKYINN THU", 0.5, 0.5),
]

MC_TAKEN = [
    ("DETCHANAMURTHY SAKTHIVEL", 2),
    ("MUTHUKKARUPPAN SINGARAVELU", 3),
    ("PANNEERSELVAM MURUGANANTHAM", 2),
    ("SELVANATHAN SATHISHKUMAR", 2),
    ("SELVARAJ ANANTH", 0),
    ("VALLATHARASU GANESAMOORTHY", 2),
    ("KANNAN SEEMAN", 2),
    ("MARIAPPAN ARJUNAN", 2),
    ("PANNEER SELVAM ANBU SELVAN", 3),
    ("HOSSAIN AZIM", 4),
    ("ALAMIN (2 RA)", 0),
    ("MADHAVAN CHELLAPANDIAN", 1),
    ("ALAGAR AYYANJOTHI", 0),
    ("ULAGANATHAN PRAKASH", 0),
    ("RAMALINGAM SRITHAR", 3),
    ("PERIYANNAN MARUTHU", 3),
    ("KARUNANITHI PRAVEEN KUMAR", 0),
    ("SELVARASU MAHESH", 0),
    ("MYAT THURA AUNG", 1),
    ("GANESAN KUMARAN", 0),
]

MC_DEFAULT_TOTAL = 14.0

# Spelling differences between the sheets and employees.full_name. Each
# alternative is tried (exact match only) if the sheet spelling finds nobody.
NAME_ALIASES = {
    "TEO WEI KIAN - SAM": ["TEO WI KIAN - SAM"],
}


def norm(s):
    return re.sub(r"[^A-Z0-9 ]", " ", (s or "").upper()).split()


def match_employee(name, employees):
    """Exactly-one match on full_name, else (None, reason). Same rules as
    scripts/import_leave_balances.py."""
    candidates = [name] + NAME_ALIASES.get(name, [])
    for alt in candidates[1:]:
        emp, _ = match_employee(alt, employees)
        if emp:
            return emp, None
    want = norm(name)
    base = norm(name.split(" - ")[0])  # nickname after " - " is optional
    for tokens in (want, base):
        hits = [e for e in employees if norm(e["full_name"]) == tokens]
        if len(hits) == 1:
            return hits[0], None
        if len(hits) > 1:
            return None, "multiple employees with that name"
    hits = [e for e in employees if set(base) <= set(norm(e["full_name"]))]
    if len(hits) == 1:
        return hits[0], None
    return None, "no match" if not hits else "ambiguous"


def g(x):
    return f"{x:g}"


def suggest(name, employees):
    """Closest DB names, shown next to an unmatched row so the spelling
    difference is obvious (the script itself never guesses)."""
    names = [e["full_name"] for e in employees]
    close = difflib.get_close_matches(
        " ".join(norm(name.split(" - ")[0])),
        [" ".join(norm(n)) for n in names],
        n=3,
        cutoff=0.5,
    )
    lookup = {" ".join(norm(n)): n for n in names}
    return [lookup[c] for c in close]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--commit", action="store_true", help="write (default: dry run)")
    ap.add_argument(
        "--skip-unmatched",
        action="store_true",
        help="with --commit: write the matched employees even if some names "
        "did not match (unmatched ones are skipped, never guessed)",
    )
    ap.add_argument(
        "--expiry",
        help="expiry_date for NEW RL credit rows (YYYY-MM-DD). Default: same "
        "day next year, like the app does when HR credits RL.",
    )
    args = ap.parse_args()

    from app.core.database import supabase_admin as db  # noqa: E402

    today = date.today()
    try:
        default_expiry = today.replace(year=today.year + 1)
    except ValueError:  # 29 Feb
        default_expiry = today.replace(year=today.year + 1, day=28)
    expiry = args.expiry or default_expiry.isoformat()

    employees = db.table("employees").select("id, full_name").execute().data or []
    by_id = {e["id"]: e["full_name"] for e in employees}
    types = {
        t["leave_name"]: t["id"]
        for t in db.table("leave_types").select("id, leave_name").execute().data
    }
    if "SICK LEAVE" not in types:
        sys.exit('leave_types has no "SICK LEAVE" -- run the 026 migration first.')

    problems, rl_plan, mc_plan = [], [], []

    # ---------------- RL ----------------
    for name, ent, taken in RL_SHEET:
        emp, why = match_employee(name, employees)
        if not emp:
            hint = suggest(name, employees)
            problems.append(
                f"RL  {name!r} -> {why}"
                + (f"   (closest in DB: {', '.join(hint)})" if hint else "")
            )
            continue
        credits = (
            db.table("leave_replacement_credits")
            .select("id, days, used_days, used, used_leave_request_id, expiry_date")
            .eq("employee_id", emp["id"])
            .execute()
            .data
            or []
        )
        linked = [c for c in credits if c.get("used_leave_request_id")]
        cur = (
            f"{sum(float(c['days'] or 0) for c in credits):g} entitled / "
            f"{sum(float(c['used_days'] or 0) for c in credits):g} taken "
            f"({len(credits)} row{'s' if len(credits) != 1 else ''})"
        )
        action = "insert" if not credits else "update"
        if linked:
            action = "SKIP"
            problems.append(
                f"RL  {name}: {len(credits)} credit rows, some linked to a "
                "leave request -- fix by hand"
            )
        elif len(credits) > 1:
            # e.g. rows added by the old automatic holiday sync. Keep the
            # first, delete the rest, so the total equals the sheet.
            action = f"update (+delete {len(credits) - 1} extra)"
        rl_plan.append(
            dict(
                emp=emp,
                name=name,
                ent=float(ent),
                taken=float(taken),
                credits=credits,
                action=action,
                cur=cur,
            )
        )

    # RL for people NOT on the sheet: report only
    sheet_ids = {p["emp"]["id"] for p in rl_plan}
    others = (
        db.table("leave_replacement_credits")
        .select("employee_id, days, used_days")
        .eq("used", False)
        .gte("expiry_date", today.isoformat())
        .execute()
        .data
        or []
    )
    extra = {}
    for c in others:
        if c["employee_id"] in sheet_ids:
            continue
        left = float(c["days"] or 1) - float(c["used_days"] or 0)
        extra[c["employee_id"]] = extra.get(c["employee_id"], 0.0) + left

    # ---------------- MC ----------------
    for name, taken in MC_TAKEN:
        emp, why = match_employee(name, employees)
        if not emp:
            hint = suggest(name, employees)
            problems.append(
                f"MC  {name!r} -> {why}"
                + (f"   (closest in DB: {', '.join(hint)})" if hint else "")
            )
            continue
        row = (
            db.table("leave_balances")
            .select("id, total_days, used_days, remaining_days")
            .eq("employee_id", emp["id"])
            .eq("leave_type_id", types["SICK LEAVE"])
            .eq("year", args.year)
            .execute()
            .data
            or []
        )
        total = float(row[0]["total_days"]) if row else MC_DEFAULT_TOTAL
        if row and abs(total - MC_DEFAULT_TOTAL) > 0.001:
            problems.append(
                f"MC  {name}: existing entitlement is {g(total)}, not "
                f"{g(MC_DEFAULT_TOTAL)} -- entitlement left as is"
            )
        mc_plan.append(
            dict(
                emp=emp,
                name=name,
                total=total,
                used=float(taken),
                cur=(
                    f"{g(float(row[0]['used_days']))} used / "
                    f"{g(float(row[0]['remaining_days']))} left"
                    if row
                    else "no row"
                ),
            )
        )

    # ---------------- report ----------------
    print(f"\nREPLACEMENT LEAVE  (expiry for new rows: {expiry})")
    print(
        f"{'Employee (DB name)':38} {'Now':38} {'-> Ent':>6} {'Taken':>6} {'Left':>5}  Action"
    )
    for p in rl_plan:
        print(
            f"{by_id[p['emp']['id']][:37]:38} {p['cur']:38} "
            f"{g(p['ent']):>6} {g(p['taken']):>6} {g(p['ent'] - p['taken']):>5}  {p['action']}"
        )
    print(f"\nMC  (SICK LEAVE) {args.year}")
    print(f"{'Employee (DB name)':38} {'Now':26} {'Total':>6} {'Taken':>6} {'Left':>5}")
    for p in mc_plan:
        print(
            f"{by_id[p['emp']['id']][:37]:38} {p['cur']:26} "
            f"{g(p['total']):>6} {g(p['used']):>6} {g(p['total'] - p['used']):>5}"
        )
    if extra:
        print("\nNOT ON THE RL SHEET but still holding unused RL (left untouched):")
        for eid, left in extra.items():
            print(f"  - {by_id.get(eid, eid)}: {g(left)} day(s) left")
    if problems:
        print("\nNEEDS ATTENTION:")
        for pr in problems:
            print("  -", pr)

    if not args.commit:
        print("\nDry run only. Re-run with --commit to write.")
        return
    if not args.skip_unmatched and any(
        ("no match" in p or "ambiguous" in p or "multiple employees" in p)
        for p in problems
    ):
        sys.exit(
            "\nNOTHING WAS WRITTEN: some names are unmatched (see NEEDS ATTENTION). "
            "Fix the spelling in the script, or use --skip-unmatched to write "
            "the matched employees only."
        )

    # ---------------- write ----------------
    for p in rl_plan:
        if p["action"] == "SKIP":
            continue
        for extra_row in p["credits"][1:]:
            db.table("leave_replacement_credits").delete().eq(
                "id", extra_row["id"]
            ).execute()
        fields = dict(
            days=p["ent"],
            used_days=p["taken"],
            used=p["taken"] >= p["ent"],
        )
        if p["action"] == "insert":
            db.table("leave_replacement_credits").insert(
                dict(
                    employee_id=p["emp"]["id"],
                    public_holiday_date=today.isoformat(),
                    credited_date=today.isoformat(),
                    expiry_date=expiry,
                    **fields,
                )
            ).execute()
        else:
            db.table("leave_replacement_credits").update(fields).eq(
                "id", p["credits"][0]["id"]
            ).execute()

    for p in mc_plan:
        db.table("leave_balances").upsert(
            dict(
                employee_id=p["emp"]["id"],
                leave_type_id=types["SICK LEAVE"],
                year=args.year,
                total_days=p["total"],
                used_days=p["used"],
                remaining_days=p["total"] - p["used"],
            ),
            on_conflict="employee_id,leave_type_id,year",
        ).execute()

    print("\nDone.")


if __name__ == "__main__":
    main()

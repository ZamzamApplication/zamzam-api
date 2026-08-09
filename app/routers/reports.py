from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.media import signed_media_url
from app.models import (
    Attendance,
    AttendanceStatus,
    QuranProgressEntry,
    Session,
    Sheikh,
    Student,
    StudentStatus,
    StudentSubscription,
    StudentWarning,
    UserRole,
    attendance_status_color_options,
    attendance_status_options,
    excel_export_template_options,
    present_status_option,
)
from app.routers.auth import TenantContext, get_tenant_context, student_scope_clause
from app.routers.subscriptions import monthly_period

router = APIRouter(prefix="/reports", tags=["reports"])


def confirmed_session_records(
    sessions: list[Session],
    student_id: int,
    attendance_lookup: dict[tuple[int, int], str],
) -> dict[str, str | None]:
    """Return null when a student was not in a confirmed session snapshot."""
    return {
        str(session.id): attendance_lookup.get((student_id, session.id))
        for session in sessions
    }


def attendance_report_metrics(counts, tahfiz) -> dict:
    configured_statuses = attendance_status_options(tahfiz)
    configured_colors = attendance_status_color_options(tahfiz)
    ordered_statuses = list(configured_statuses)
    ordered_statuses.extend(status for status in counts if status not in ordered_statuses)
    status_counts = {status: counts.get(status, 0) for status in ordered_statuses}

    def status_with_role(default_label: str, color: str) -> str | None:
        if default_label in ordered_statuses:
            return default_label
        return next(
            (status for status in ordered_statuses if configured_colors.get(status) == color),
            None,
        )

    present_status = present_status_option(tahfiz)
    excused_status = status_with_role(AttendanceStatus.excused.value, "amber")
    absent_status = status_with_role(AttendanceStatus.absent.value, "slate")
    excluded_status = status_with_role(AttendanceStatus.not_applicable.value, "sky")
    applicable_statuses = [status for status in ordered_statuses if status != excluded_status]
    attended_statuses = {status for status in (present_status, excused_status) if status and status in ordered_statuses}
    applicable = sum(status_counts[status] for status in applicable_statuses)
    attended = sum(status_counts[status] for status in attended_statuses)
    return {
        "status_counts": status_counts,
        "total_records": sum(status_counts.values()),
        "total_applicable": applicable,
        "attendance_rate": round(attended / applicable * 100, 1) if applicable else 0,
        "present": status_counts.get(present_status, 0),
        "excused": status_counts.get(excused_status, 0) if excused_status else 0,
        "absent": status_counts.get(absent_status, 0) if absent_status else 0,
        "not_applicable": status_counts.get(excluded_status, 0) if excluded_status else 0,
    }


@router.get("/dashboard-summary")
async def dashboard_summary(
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    tahfiz_id = context.tahfiz_id
    sheikh_count_query = select(func.count(Sheikh.id)).where(Sheikh.tahfiz_id == tahfiz_id)
    if context.restricts_sheikh_students:
        sheikh_count_query = sheikh_count_query.where(Sheikh.id == context.sheikh_id)
    result = await db.execute(
        select(
            sheikh_count_query.scalar_subquery(),
            select(func.count(Student.id)).where(
                student_scope_clause(context),
                Student.status == StudentStatus.enrolled,
            ).scalar_subquery(),
            select(func.count(Session.id)).where(Session.tahfiz_id == tahfiz_id).scalar_subquery(),
            select(func.count(Session.id)).where(
                Session.tahfiz_id == tahfiz_id,
                Session.is_confirmed == True,
            ).scalar_subquery(),
        )
    )
    sheikhs, students, sessions, confirmed = result.one()
    return {
        "tahfiz_name": context.tahfiz.name,
        "sheikhs": sheikhs,
        "students": students,
        "sessions": sessions,
        "confirmed_sessions": confirmed,
        "pending_sessions": sessions - confirmed,
    }


@router.get("/circles")
async def list_circles(
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    return [
        {
            "id": context.tahfiz.id,
            "name": context.tahfiz.name,
            "description": context.tahfiz.description,
            "max_warnings": context.tahfiz.max_warnings,
            "week_start_day": context.tahfiz.week_start_day,
            "month_start_day": context.tahfiz.month_start_day,
            "progress_tracking_enabled": context.tahfiz.progress_tracking_enabled,
            "restrict_sheikh_student_access": context.tahfiz.restrict_sheikh_student_access is not False,
            "attendance_statuses": attendance_status_options(context.tahfiz),
            "attendance_status_colors": attendance_status_color_options(context.tahfiz),
            "excel_export_templates": excel_export_template_options(context.tahfiz),
        }
    ]


@router.get("/circle/{circle_id}/rate")
async def circle_attendance_rate(
    circle_id: int,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    from collections import Counter

    if circle_id != context.tahfiz_id:
        raise HTTPException(status_code=404, detail="Tahfiz not found")
    tahfiz_id = context.tahfiz_id
    result = await db.execute(
        select(Student.id)
        .where(student_scope_clause(context), Student.status == StudentStatus.enrolled)
    )
    student_ids = [row[0] for row in result.all()]

    if not student_ids:
        empty_metrics = attendance_report_metrics({}, context.tahfiz)
        return {
            "circle_id": circle_id,
            "scope": "assigned_students" if context.restricts_sheikh_students else "tenant",
            "total_attendance_records": 0,
            "total_applicable_records": 0,
            **{key: empty_metrics[key] for key in (
                "status_counts", "present", "absent", "excused", "not_applicable", "attendance_rate"
            )},
        }

    att_query = (
        select(Attendance.student_id, Attendance.status)
        .where(Attendance.student_id.in_(student_ids))
        .join(Session)
        .where(Session.tahfiz_id == tahfiz_id, Session.is_confirmed == True)
    )
    if date_from:
        att_query = att_query.where(Session.date >= date_from)
    if date_to:
        att_query = att_query.where(Session.date <= date_to)

    result = await db.execute(att_query)
    att_rows = result.all()

    student_attendance = {sid: Counter() for sid in student_ids}
    for att in att_rows:
        student_attendance[att.student_id][att.status] += 1

    total_counts = Counter()
    for counts in student_attendance.values():
        total_counts.update(counts)
    metrics = attendance_report_metrics(total_counts, context.tahfiz)

    return {
        "circle_id": circle_id,
        "scope": "assigned_students" if context.restricts_sheikh_students else "tenant",
        "total_attendance_records": metrics["total_records"],
        "total_applicable_records": metrics["total_applicable"],
        **{key: metrics[key] for key in (
            "status_counts", "present", "absent", "excused", "not_applicable", "attendance_rate"
        )},
    }


@router.get("/circle/{circle_id}/student-stats")
async def circle_student_stats(
    circle_id: int,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    if circle_id != context.tahfiz_id:
        raise HTTPException(status_code=404, detail="Tahfiz not found")
    tahfiz_id = context.tahfiz_id
    result = await db.execute(
        select(Student.id, Student.name, Student.profile_pic, Sheikh.name.label("sheikh_name"))
        .join(Sheikh)
        .where(student_scope_clause(context), Student.status == StudentStatus.enrolled)
        .order_by(Student.name)
    )
    rows = result.all()
    student_ids = [r.id for r in rows]

    att_query = (
        select(Attendance.student_id, Attendance.status)
        .where(Attendance.student_id.in_(student_ids))
        .join(Session)
        .where(Session.tahfiz_id == tahfiz_id, Session.is_confirmed == True)
    )
    if date_from:
        att_query = att_query.where(Session.date >= date_from)
    if date_to:
        att_query = att_query.where(Session.date <= date_to)

    result = await db.execute(att_query)
    att_rows = result.all()

    from collections import Counter
    student_attendance = {sid: Counter() for sid in student_ids}
    for att in att_rows:
        student_attendance[att.student_id][att.status] += 1

    students_data = []
    for row in rows:
        counts = student_attendance[row.id]
        metrics = attendance_report_metrics(counts, context.tahfiz)

        students_data.append({
            "student_id": row.id,
            "student_name": row.name,
            "profile_pic": signed_media_url(row.profile_pic, context.tahfiz_id),
            "sheikh_name": row.sheikh_name,
            "total_sessions": metrics["total_records"],
            "total_applicable_sessions": metrics["total_applicable"],
            **{key: metrics[key] for key in (
                "status_counts", "present", "excused", "absent", "not_applicable", "attendance_rate"
            )},
        })

    return {
        "circle_id": circle_id,
        "scope": "assigned_students" if context.restricts_sheikh_students else "tenant",
        "students": students_data,
    }


@router.get("/student/{student_id}/streak")
async def student_streak(
    student_id: int,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    student = await db.scalar(select(Student.id).where(
        Student.id == student_id,
        student_scope_clause(context),
    ))
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    result = await db.execute(
        select(func.count(Attendance.id))
        .where(
            Attendance.student_id == student_id,
            Attendance.status == AttendanceStatus.absent,
        )
        .join(Session)
        .where(Session.is_confirmed == True, Session.tahfiz_id == context.tahfiz_id)
    )
    total_absent = result.scalar() or 0

    result = await db.execute(
        select(func.count(Attendance.id))
        .where(
            Attendance.student_id == student_id,
            Attendance.status != AttendanceStatus.not_applicable,
        )
        .join(Session)
        .where(Session.is_confirmed == True, Session.tahfiz_id == context.tahfiz_id)
    )
    total = result.scalar() or 0

    present_status = present_status_option(context.tahfiz)
    present_count = await db.execute(
        select(func.count(Attendance.id))
        .where(
            Attendance.student_id == student_id,
            Attendance.status == present_status,
        )
        .join(Session)
        .where(Session.is_confirmed == True, Session.tahfiz_id == context.tahfiz_id)
    )
    present = present_count.scalar() or 0

    result = await db.execute(
        select(func.count(Attendance.id))
        .where(
            Attendance.student_id == student_id,
            Attendance.status == AttendanceStatus.excused,
        )
        .join(Session)
        .where(Session.is_confirmed == True, Session.tahfiz_id == context.tahfiz_id)
    )
    excused = result.scalar() or 0

    attended = present + excused

    return {
        "student_id": student_id,
        "total_attended": present,
        "total_excused": excused,
        "total_absent": total_absent,
        "total_sessions": total,
        "attendance_rate": round((attended / total * 100), 1) if total > 0 else 0,
    }


@router.get("/attendance-grid")
async def attendance_grid(
    sheikh_id: int | None = Query(default=None),
    circle_id: int | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=1000),
    session_ids: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    if context.restricts_sheikh_students:
        if sheikh_id is not None and sheikh_id != context.sheikh_id:
            raise HTTPException(status_code=404, detail="Sheikh not found")
        sheikh_id = context.sheikh_id
    # Get confirmed sessions ordered by date
    query = select(Session).where(Session.is_confirmed == True)
    query = query.where(Session.tahfiz_id == context.tahfiz_id)
    if circle_id and circle_id != context.tahfiz_id:
        raise HTTPException(status_code=404, detail="Tahfiz not found")
    if date_from:
        query = query.where(Session.date >= date_from)
    if date_to:
        query = query.where(Session.date <= date_to)
    if session_ids:
        try:
            parsed_ids = [int(s) for s in session_ids.split(",") if s.strip()]
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid session_ids")
        if parsed_ids:
            query = query.where(Session.id.in_(parsed_ids))
    query = query.order_by(Session.date.desc())
    if limit:
        query = query.limit(limit)
    result = await db.execute(query)
    sessions = list(reversed(result.scalars().all()))

    # Get students
    if sheikh_id is not None:
        result = await db.execute(
            select(Student)
            .options(selectinload(Student.sheikh))
            .where(
                Student.sheikh_id == sheikh_id,
                student_scope_clause(context),
                Student.status == StudentStatus.enrolled,
            )
            .order_by(Student.name)
        )
        students = result.scalars().all()
        student_ids = [s.id for s in students]
        student_map = {s.id: s for s in students}
    else:
        result = await db.execute(
            select(Student)
            .outerjoin(Sheikh)
            .options(selectinload(Student.sheikh))
            .where(Student.status == StudentStatus.enrolled, student_scope_clause(context))
            .order_by(Student.name)
        )
        students = result.scalars().all()
        student_ids = [s.id for s in students]
        student_map = {s.id: s for s in students}

    if not student_ids or not sessions:
        return {
            "scope": "assigned_students" if context.restricts_sheikh_students else "tenant",
            "sessions": [],
            "students": [],
        }

    # Get all attendance records for these students in these sessions
    session_ids = [s.id for s in sessions]
    result = await db.execute(
        select(Attendance).where(
            Attendance.student_id.in_(student_ids),
            Attendance.session_id.in_(session_ids),
            Attendance.tahfiz_id == context.tahfiz_id,
        )
    )
    attendance_records = result.scalars().all()

    progress_entries = (await db.execute(
        select(QuranProgressEntry)
        .join(Session, Session.id == QuranProgressEntry.session_id)
        .where(
            QuranProgressEntry.student_id.in_(student_ids),
            QuranProgressEntry.session_id.in_(session_ids),
            QuranProgressEntry.tahfiz_id == context.tahfiz_id,
            QuranProgressEntry.category.in_(["new_memorization", "recent_revision", "old_revision"]),
        )
        .order_by(Session.date, Session.id, QuranProgressEntry.updated_at, QuranProgressEntry.id)
    )).scalars().all() if context.tahfiz.progress_tracking_enabled else []
    quran_progress_ranges: dict[int, dict[str, dict]] = {}
    for entry in progress_entries:
        category_range = quran_progress_ranges.setdefault(entry.student_id, {}).setdefault(entry.category.value, {})
        snapshot = {
            "range_type": entry.range_type.value,
            "from_surah": entry.from_surah,
            "from_ayah": entry.from_ayah,
            "to_surah": entry.to_surah,
            "to_ayah": entry.to_ayah,
            "from_page": entry.from_page,
            "to_page": entry.to_page,
        }
        category_range.setdefault("first", snapshot)
        category_range["last"] = snapshot

    warning_count_result = await db.execute(
        select(StudentWarning.student_id, func.count(StudentWarning.id))
        .where(StudentWarning.student_id.in_(student_ids))
        .group_by(StudentWarning.student_id)
    )
    warning_counts = dict(warning_count_result.all())

    subscription_amounts: dict[int, int] = {}
    if context.effective_role in (UserRole.admin, UserRole.super_admin):
        reference_date = date_from or (sessions[0].date if sessions else date.today())
        subscription_period, _ = monthly_period(reference_date, context.tahfiz.month_start_day)
        subscription_amounts = dict((await db.execute(select(
            StudentSubscription.student_snapshot_id,
            StudentSubscription.amount_due_minor,
        ).where(
            StudentSubscription.tahfiz_id == context.tahfiz_id,
            StudentSubscription.period_start == subscription_period,
            StudentSubscription.student_snapshot_id.in_(student_ids),
            StudentSubscription.is_paid.is_(True),
        ))).all())

    max_warnings = context.tahfiz.max_warnings

    # Build lookup: (student_id, session_id) -> status
    att_lookup: dict[tuple[int, int], str] = {}
    for att in attendance_records:
        if att.student_id is not None:
            att_lookup[(att.student_id, att.session_id)] = att.status

    # Build student grid data
    students_data = []
    for sid in student_ids:
        student = student_map.get(sid)
        if not student:
            continue
        records = confirmed_session_records(sessions, sid, att_lookup)
        # A confirmed session's attendance rows are its student snapshot. If the
        # student has no rows in this range, they joined later and should not be
        # shown as though they participated in these sessions.
        if not any(status is not None for status in records.values()):
            continue
        next_warning_number = warning_counts.get(sid, 0) + 1
        students_data.append({
            "id": sid,
            "name": student.name,
            "profile_pic": signed_media_url(student.profile_pic, context.tahfiz_id),
            "sheikh_id": student.sheikh_id,
            "sheikh_name": student.sheikh.name if student.sheikh else None,
            "next_warning_number": next_warning_number,
            "remaining_warnings": max(max_warnings - next_warning_number, 0),
            **({"subscription_amount_minor": subscription_amounts.get(sid)} if context.effective_role in (UserRole.admin, UserRole.super_admin) else {}),
            "quran_progress_ranges": quran_progress_ranges.get(sid, {}),
            "records": records,
        })

    return {
        "scope": "assigned_students" if context.restricts_sheikh_students else "tenant",
        "sessions": [{"id": s.id, "date": s.date.isoformat(), "circle_id": s.tahfiz_id, "tahfiz_id": s.tahfiz_id} for s in sessions],
        "students": students_data,
    }

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Attendance, AttendanceStatus, Session, Sheikh, Student, StudentStatus, StudentWarning
from app.routers.auth import TenantContext, get_tenant_context

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/dashboard-summary")
async def dashboard_summary(
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    tahfiz_id = context.tahfiz_id
    result = await db.execute(
        select(
            select(func.count(Sheikh.id)).where(Sheikh.tahfiz_id == tahfiz_id).scalar_subquery(),
            select(func.count(Student.id)).where(
                Student.tahfiz_id == tahfiz_id,
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
        .where(Student.tahfiz_id == tahfiz_id, Student.status == StudentStatus.enrolled)
    )
    student_ids = [row[0] for row in result.all()]

    if not student_ids:
        return {
            "circle_id": circle_id,
            "total_attendance_records": 0,
            "present": 0,
            "absent": 0,
            "excused": 0,
            "attendance_rate": 0,
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

    total_present = 0
    total_excused = 0
    total_absent = 0

    for sid in student_ids:
        counts = student_attendance[sid]
        present = counts.get(AttendanceStatus.present, 0)
        excused = counts.get(AttendanceStatus.excused, 0)
        absent_records = counts.get(AttendanceStatus.absent, 0)
        total_present += present
        total_excused += excused
        total_absent += absent_records

    total_applicable = total_present + total_excused + total_absent
    attended = total_present + total_excused
    rate = round((attended / total_applicable * 100), 1) if total_applicable > 0 else 0

    return {
        "circle_id": circle_id,
        "total_attendance_records": total_applicable,
        "present": total_present,
        "absent": total_absent,
        "excused": total_excused,
        "attendance_rate": rate,
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
        .where(Student.tahfiz_id == tahfiz_id, Student.status == StudentStatus.enrolled)
        .order_by(Sheikh.name, Student.sort_order)
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
        present = counts.get(AttendanceStatus.present, 0)
        excused = counts.get(AttendanceStatus.excused, 0)
        absent_records = counts.get(AttendanceStatus.absent, 0)
        not_applicable = counts.get(AttendanceStatus.not_applicable, 0)
        total_records = present + excused + absent_records + not_applicable

        absent = absent_records
        total_applicable = present + excused + absent_records

        rate = round((present + excused) / total_applicable * 100, 1) if total_applicable > 0 else 0

        students_data.append({
            "student_id": row.id,
            "student_name": row.name,
            "profile_pic": row.profile_pic,
            "sheikh_name": row.sheikh_name,
            "total_sessions": total_records,
            "present": present,
            "excused": excused,
            "absent": absent,
            "not_applicable": not_applicable,
            "attendance_rate": rate,
        })

    return {"circle_id": circle_id, "students": students_data}


@router.get("/student/{student_id}/streak")
async def student_streak(
    student_id: int,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    student = await db.scalar(select(Student.id).where(
        Student.id == student_id,
        Student.tahfiz_id == context.tahfiz_id,
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

    present_count = await db.execute(
        select(func.count(Attendance.id))
        .where(
            Attendance.student_id == student_id,
            Attendance.status == AttendanceStatus.present,
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
    limit: int | None = Query(default=None),
    session_ids: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
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
        parsed_ids = [int(s) for s in session_ids.split(",") if s.strip()]
        if parsed_ids:
            query = query.where(Session.id.in_(parsed_ids))
    query = query.order_by(Session.date.desc())
    if limit:
        query = query.limit(limit)
    result = await db.execute(query)
    sessions = list(reversed(result.scalars().all()))

    # Get students
    if sheikh_id:
        result = await db.execute(
            select(Student)
            .options(selectinload(Student.sheikh))
            .where(
                Student.sheikh_id == sheikh_id,
                Student.tahfiz_id == context.tahfiz_id,
                Student.status == StudentStatus.enrolled,
            )
            .order_by(Student.sort_order, Student.name)
        )
        students = result.scalars().all()
        student_ids = [s.id for s in students]
        student_map = {s.id: s for s in students}
    else:
        result = await db.execute(
            select(Student)
            .outerjoin(Sheikh)
            .options(selectinload(Student.sheikh))
            .where(Student.status == StudentStatus.enrolled, Student.tahfiz_id == context.tahfiz_id)
            .order_by(Sheikh.name, Student.name)
        )
        students = result.scalars().all()
        student_ids = [s.id for s in students]
        student_map = {s.id: s for s in students}

    if not student_ids or not sessions:
        return {"sessions": [], "students": []}

    # Get all attendance records for these students in these sessions
    session_ids = [s.id for s in sessions]
    result = await db.execute(
        select(Attendance).where(
            Attendance.student_id.in_(student_ids),
            Attendance.session_id.in_(session_ids),
        )
    )
    attendance_records = result.scalars().all()

    warning_count_result = await db.execute(
        select(StudentWarning.student_id, func.count(StudentWarning.id))
        .where(StudentWarning.student_id.in_(student_ids))
        .group_by(StudentWarning.student_id)
    )
    warning_counts = dict(warning_count_result.all())

    max_warnings = context.tahfiz.max_warnings

    # Build lookup: (student_id, session_id) -> status
    att_lookup: dict[tuple[int, int], str] = {}
    for att in attendance_records:
        if att.student_id is not None:
            att_lookup[(att.student_id, att.session_id)] = att.status.value

    # Build student grid data
    students_data = []
    for sid in student_ids:
        student = student_map.get(sid)
        if not student:
            continue
        records: dict[str, str] = {}
        for sess in sessions:
            default_status = "لا ينطبق" if student.registration_date and student.registration_date > sess.date else "غياب"
            records[str(sess.id)] = att_lookup.get((sid, sess.id), default_status)
        next_warning_number = warning_counts.get(sid, 0) + 1
        students_data.append({
            "id": sid,
            "name": student.name,
            "profile_pic": student.profile_pic,
            "sheikh_id": student.sheikh_id,
            "sheikh_name": student.sheikh.name if student.sheikh else None,
            "next_warning_number": next_warning_number,
            "remaining_warnings": max(max_warnings - next_warning_number, 0),
            "records": records,
        })

    return {
        "sessions": [{"id": s.id, "date": s.date.isoformat(), "circle_id": s.tahfiz_id, "tahfiz_id": s.tahfiz_id} for s in sessions],
        "students": students_data,
    }

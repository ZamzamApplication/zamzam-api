from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Attendance, AttendanceStatus, Circle, Session, Sheikh, Student, StudentStatus
from app.routers.auth import get_current_user_depends

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/circles")
async def list_circles(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    result = await db.execute(select(Circle))
    circles = result.scalars().all()
    return [{"id": c.id, "name": c.name, "description": c.description} for c in circles]


@router.get("/circle/{circle_id}/rate")
async def circle_attendance_rate(
    circle_id: int,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    from collections import Counter

    result = await db.execute(
        select(Student.id)
        .join(Sheikh)
        .where(Sheikh.circle_id == circle_id, Student.status == StudentStatus.enrolled)
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

    session_query = select(func.count(Session.id)).where(
        Session.circle_id == circle_id, Session.is_confirmed == True
    )
    if date_from:
        session_query = session_query.where(Session.date >= date_from)
    if date_to:
        session_query = session_query.where(Session.date <= date_to)

    result = await db.execute(session_query)
    total_sessions = result.scalar() or 0

    att_query = (
        select(Attendance.student_id, Attendance.status)
        .where(Attendance.student_id.in_(student_ids))
        .join(Session)
        .where(Session.is_confirmed == True)
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
    total_not_applicable = 0

    for sid in student_ids:
        counts = student_attendance[sid]
        present = counts.get(AttendanceStatus.present, 0)
        excused = counts.get(AttendanceStatus.excused, 0)
        absent_records = counts.get(AttendanceStatus.absent, 0)
        not_applicable = counts.get(AttendanceStatus.not_applicable, 0)
        total_records = present + excused + absent_records + not_applicable

        no_record = total_sessions - total_records

        total_present += present
        total_excused += excused
        total_absent += absent_records + no_record
        total_not_applicable += not_applicable

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
    current_user=Depends(get_current_user_depends),
):
    result = await db.execute(
        select(Student.id, Student.name, Sheikh.name.label("sheikh_name"))
        .join(Sheikh)
        .where(Sheikh.circle_id == circle_id, Student.status == StudentStatus.enrolled)
        .order_by(Sheikh.name, Student.sort_order)
    )
    rows = result.all()
    student_ids = [r.id for r in rows]

    session_query = select(func.count(Session.id)).where(
        Session.circle_id == circle_id, Session.is_confirmed == True
    )
    if date_from:
        session_query = session_query.where(Session.date >= date_from)
    if date_to:
        session_query = session_query.where(Session.date <= date_to)

    result = await db.execute(session_query)
    total_sessions = result.scalar() or 0

    att_query = (
        select(Attendance.student_id, Attendance.status)
        .where(Attendance.student_id.in_(student_ids))
        .join(Session)
        .where(Session.is_confirmed == True)
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

        no_record = total_sessions - total_records
        absent = absent_records + no_record
        total_applicable = total_sessions - not_applicable

        rate = round((present + excused) / total_applicable * 100, 1) if total_applicable > 0 else 0

        students_data.append({
            "student_id": row.id,
            "student_name": row.name,
            "sheikh_name": row.sheikh_name,
            "total_sessions": total_sessions,
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
    current_user=Depends(get_current_user_depends),
):
    result = await db.execute(
        select(func.count(Attendance.id))
        .where(
            Attendance.student_id == student_id,
            Attendance.status == AttendanceStatus.absent,
        )
        .join(Session)
        .where(Session.is_confirmed == True)
    )
    total_absent = result.scalar() or 0

    result = await db.execute(
        select(func.count(Attendance.id))
        .where(
            Attendance.student_id == student_id,
            Attendance.status != AttendanceStatus.not_applicable,
        )
        .join(Session)
        .where(Session.is_confirmed == True)
    )
    total = result.scalar() or 0

    present_count = await db.execute(
        select(func.count(Attendance.id))
        .where(
            Attendance.student_id == student_id,
            Attendance.status == AttendanceStatus.present,
        )
        .join(Session)
        .where(Session.is_confirmed == True)
    )
    present = present_count.scalar() or 0

    result = await db.execute(
        select(func.count(Attendance.id))
        .where(
            Attendance.student_id == student_id,
            Attendance.status == AttendanceStatus.excused,
        )
        .join(Session)
        .where(Session.is_confirmed == True)
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
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    # Get confirmed sessions ordered by date
    query = select(Session).where(Session.is_confirmed == True)
    if circle_id:
        query = query.where(Session.circle_id == circle_id)
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
            .where(
                Student.sheikh_id == sheikh_id,
                Student.status == StudentStatus.enrolled,
            )
            .order_by(Student.sort_order)
        )
        students = result.scalars().all()
        student_ids = [s.id for s in students]
        student_map = {s.id: s for s in students}
    else:
        result = await db.execute(select(Student).order_by(Student.name))
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
        students_data.append({
            "id": sid,
            "name": student.name,
            "records": records,
        })

    return {
        "sessions": [{"id": s.id, "date": s.date.isoformat(), "circle_id": s.circle_id} for s in sessions],
        "students": students_data,
    }

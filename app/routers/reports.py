from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Attendance, AttendanceStatus, Circle, Session, Student, Sheikh
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
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    # Get all students belonging to this circle's sheikhs
    result = await db.execute(
        select(Student.id)
        .join(Sheikh)
        .where(Sheikh.circle_id == circle_id)
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

    result = await db.execute(
        select(func.count(Attendance.id))
        .where(
            Attendance.student_id.in_(student_ids),
        )
        .join(Session)
        .where(Session.is_confirmed == True)
    )
    total = result.scalar() or 0

    result = await db.execute(
        select(func.count(Attendance.id))
        .where(
            Attendance.student_id.in_(student_ids),
            Attendance.status == AttendanceStatus.present,
        )
        .join(Session)
        .where(Session.is_confirmed == True)
    )
    present = result.scalar() or 0

    result = await db.execute(
        select(func.count(Attendance.id))
        .where(
            Attendance.student_id.in_(student_ids),
            Attendance.status == AttendanceStatus.excused,
        )
        .join(Session)
        .where(Session.is_confirmed == True)
    )
    excused = result.scalar() or 0

    attended = present + excused
    absent = total - attended
    rate = round((attended / total * 100), 1) if total > 0 else 0

    return {
        "circle_id": circle_id,
        "total_attendance_records": total,
        "present": present,
        "absent": absent,
        "excused": excused,
        "attendance_rate": rate,
    }


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
        .where(Attendance.student_id == student_id)
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
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    # Get confirmed sessions ordered by date
    query = select(Session).where(Session.is_confirmed == True)
    if circle_id:
        query = query.where(Session.circle_id == circle_id)
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
                Student.is_enrolled == True,
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
            records[str(sess.id)] = att_lookup.get((sid, sess.id), "غياب")
        students_data.append({
            "id": sid,
            "name": student.name,
            "records": records,
        })

    return {
        "sessions": [{"id": s.id, "date": s.date.isoformat(), "circle_id": s.circle_id} for s in sessions],
        "students": students_data,
    }

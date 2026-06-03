from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Attendance, AttendanceStatus, Circle, Session, Student
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
    result = await db.execute(
        select(func.count(Attendance.id))
        .join(Session)
        .where(Session.circle_id == circle_id, Session.is_confirmed == True)
    )
    total = result.scalar() or 0

    result = await db.execute(
        select(func.count(Attendance.id))
        .join(Session)
        .where(
            Session.circle_id == circle_id,
            Session.is_confirmed == True,
            Attendance.status == AttendanceStatus.present,
        )
    )
    present = result.scalar() or 0

    result = await db.execute(
        select(func.count(Attendance.id))
        .join(Session)
        .where(
            Session.circle_id == circle_id,
            Session.is_confirmed == True,
            Attendance.status == AttendanceStatus.excused,
        )
    )
    excused = result.scalar() or 0

    absent = total - present - excused
    rate = round((present / total * 100), 1) if total > 0 else 0

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
        select(Attendance)
        .where(
            Attendance.student_id == student_id,
            Attendance.status == AttendanceStatus.present,
        )
        .join(Session)
        .where(Session.is_confirmed == True)
        .order_by(Session.date.desc())
        .limit(1)
    )
    last_present = result.scalar_one_or_none()
    if not last_present:
        return {"student_id": student_id, "current_streak": 0}

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

    return {
        "student_id": student_id,
        "total_attended": present,
        "total_absent": total_absent,
        "total_sessions": total,
        "attendance_rate": round((present / total * 100), 1) if total > 0 else 0,
    }

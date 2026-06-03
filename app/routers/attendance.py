from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Attendance, AttendanceStatus
from app.routers.auth import get_current_user_depends

router = APIRouter(prefix="/attendance", tags=["attendance"])


@router.patch("/{attendance_id}")
async def update_attendance(
    attendance_id: int,
    status: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    if status not in [s.value for s in AttendanceStatus]:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {[s.value for s in AttendanceStatus]}")

    result = await db.execute(select(Attendance).where(Attendance.id == attendance_id))
    attendance = result.scalar_one_or_none()
    if not attendance:
        raise HTTPException(status_code=404, detail="Attendance record not found")

    attendance.status = AttendanceStatus(status)
    await db.commit()
    return {"id": attendance.id, "status": attendance.status.value}


@router.post("/upsert")
async def upsert_attendance(
    session_id: int,
    student_id: int,
    status: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    if status not in [s.value for s in AttendanceStatus]:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {[s.value for s in AttendanceStatus]}")

    result = await db.execute(
        select(Attendance).where(
            Attendance.session_id == session_id,
            Attendance.student_id == student_id,
        )
    )
    attendance = result.scalar_one_or_none()

    if attendance:
        attendance.status = AttendanceStatus(status)
    else:
        attendance = Attendance(
            session_id=session_id,
            student_id=student_id,
            status=AttendanceStatus(status),
        )
        db.add(attendance)

    await db.commit()
    await db.refresh(attendance)
    return {"id": attendance.id, "status": attendance.status.value, "session_id": attendance.session_id, "student_id": attendance.student_id}

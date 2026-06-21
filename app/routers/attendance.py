from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Attendance, AttendanceStatus, User
from app.routers.auth import get_current_user_depends
from app.schemas import UpdateAttendanceRequest, UpsertAttendanceRequest

router = APIRouter(prefix="/attendance", tags=["attendance"])


@router.patch("/{attendance_id}")
async def update_attendance(
    attendance_id: int,
    body: UpdateAttendanceRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_depends),
):
    if body.status not in [s.value for s in AttendanceStatus]:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {[s.value for s in AttendanceStatus]}")

    result = await db.execute(select(Attendance).where(Attendance.id == attendance_id))
    attendance = result.scalar_one_or_none()
    if not attendance:
        raise HTTPException(status_code=404, detail="Attendance record not found")

    attendance.status = AttendanceStatus(body.status)
    if body.notes is not None:
        attendance.notes = body.notes
    if body.sheikh_id is not None:
        attendance.sheikh_id = body.sheikh_id
    await db.commit()
    return {"id": attendance.id, "status": attendance.status.value, "notes": attendance.notes, "sheikh_id": attendance.sheikh_id}


@router.post("/upsert")
async def upsert_attendance(
    body: UpsertAttendanceRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_depends),
):
    if body.status not in [s.value for s in AttendanceStatus]:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {[s.value for s in AttendanceStatus]}")

    result = await db.execute(
        select(Attendance).where(
            Attendance.session_id == body.session_id,
            Attendance.student_id == body.student_id,
        )
    )
    attendance = result.scalar_one_or_none()

    if attendance:
        attendance.status = AttendanceStatus(body.status)
        if body.notes is not None:
            attendance.notes = body.notes
        if body.sheikh_id is not None:
            attendance.sheikh_id = body.sheikh_id
    else:
        attendance = Attendance(
            session_id=body.session_id,
            student_id=body.student_id,
            status=AttendanceStatus(body.status),
            notes=body.notes,
            sheikh_id=body.sheikh_id,
        )
        db.add(attendance)

    await db.commit()
    await db.refresh(attendance)
    return {"id": attendance.id, "status": attendance.status.value, "notes": attendance.notes, "session_id": attendance.session_id, "student_id": attendance.student_id, "sheikh_id": attendance.sheikh_id}

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete as sa_delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Attendance, AttendanceStatus, Circle, Session, Sheikh, Student, StudentSheikh
from app.routers.auth import get_current_user_depends
from app.schemas import CreateSessionRequest, UpdateSessionRequest

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("/all")
async def get_all_sessions(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    query = (
        select(Session)
        .options(selectinload(Session.circle))
        .order_by(Session.date.desc())
    )
    result = await db.execute(query)
    sessions = result.scalars().all()
    return [
        {
            "id": s.id,
            "date": s.date.isoformat(),
            "is_confirmed": s.is_confirmed,
            "circle_id": s.circle_id,
            "circle_name": s.circle.name,
        }
        for s in sessions
    ]


@router.get("/past")
async def get_past_sessions(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    query = (
        select(Session)
        .options(selectinload(Session.circle))
        .where(Session.is_confirmed == True)
        .order_by(Session.date.desc())
    )
    result = await db.execute(query)
    sessions = result.scalars().all()
    return [
        {
            "id": s.id,
            "date": s.date.isoformat(),
            "is_confirmed": s.is_confirmed,
            "circle_id": s.circle_id,
            "circle_name": s.circle.name,
        }
        for s in sessions
    ]


@router.get("/upcoming")
async def get_upcoming_sessions(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    query = (
        select(Session)
        .options(selectinload(Session.circle))
        .where(Session.is_confirmed == False)
        .order_by(Session.date)
    )
    result = await db.execute(query)
    sessions = result.scalars().all()
    return [
        {
            "id": s.id,
            "date": s.date.isoformat(),
            "is_confirmed": s.is_confirmed,
            "circle_id": s.circle_id,
            "circle_name": s.circle.name,
        }
        for s in sessions
    ]


@router.post("/")
async def create_session(
    body: CreateSessionRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    result = await db.execute(select(Circle).where(Circle.id == body.circle_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Circle not found")

    session = Session(date=body.session_date, circle_id=body.circle_id)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return {"id": session.id, "date": session.date.isoformat(), "circle_id": session.circle_id}


@router.put("/{session_id}")
async def update_session(
    session_id: int,
    body: UpdateSessionRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session.date = body.session_date
    await db.commit()
    return {"id": session.id, "date": session.date.isoformat()}


@router.get("/{session_id}/attendance")
async def get_session_attendance(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    result = await db.execute(
        select(Session).options(selectinload(Session.circle)).where(Session.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    result = await db.execute(
        select(Sheikh)
        .options(
            selectinload(Sheikh.students).selectinload(StudentSheikh.student)
        )
        .where(Sheikh.circle_id == session.circle_id)
    )
    circle_sheikhs = result.scalars().all()

    # Get all sheikhs in this circle for the dropdown
    circle_sheikhs_list = [
        {"id": s.id, "name": s.name}
        for s in circle_sheikhs
    ]

    sheikh_groups = []
    for sheikh in circle_sheikhs:
        students_list = []
        for ss in sheikh.students:
            if ss.end_date is None or ss.end_date >= session.date:
                att_result = await db.execute(
                    select(Attendance).where(
                        Attendance.session_id == session_id,
                        Attendance.student_id == ss.student_id,
                    )
                )
                att = att_result.scalar_one_or_none()
                # For confirmed sessions, only show students that have an attendance record
                if session.is_confirmed and att is None:
                    continue
                # Default sheikh_id is the student's assigned sheikh, overridden by attendance record
                default_sheikh_id = ss.sheikh_id
                att_sheikh_id = att.sheikh_id if att else default_sheikh_id
                students_list.append({
                    "id": ss.student.id,
                    "name": ss.student.name,
                    "phone": ss.student.phone,
                    "attendance_id": att.id if att else None,
                    "status": att.status.value if att else "غياب",
                    "notes": att.notes if att else None,
                    "sheikh_id": att_sheikh_id,
                })

        sheikh_groups.append({
            "sheikh": {"id": sheikh.id, "name": sheikh.name},
            "students": students_list,
        })

    return {
        "session_id": session.id,
        "date": session.date.isoformat(),
        "is_confirmed": session.is_confirmed,
        "circle_id": session.circle_id,
        "circle_name": session.circle.name,
        "sheikh_groups": sheikh_groups,
        "circle_sheikhs": circle_sheikhs_list,
    }


@router.post("/{session_id}/confirm")
async def confirm_session(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session.is_confirmed = True
    await db.commit()
    return {"message": "Session confirmed"}


@router.delete("/{session_id}")
async def delete_session(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    await db.execute(sa_delete(Attendance).where(Attendance.session_id == session_id))
    await db.delete(session)
    await db.commit()
    return {"message": "Session deleted"}

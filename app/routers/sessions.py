from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Attendance, AttendanceStatus, Circle, Session
from app.routers.auth import get_current_user_depends

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("/upcoming")
async def get_upcoming_sessions(
    circle_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    query = (
        select(Session)
        .options(selectinload(Session.circle))
        .where(Session.is_confirmed == False)
        .order_by(Session.date)
    )
    if circle_id:
        query = query.where(Session.circle_id == circle_id)
    result = await db.execute(query)
    sessions = result.scalars().all()
    return [
        {
            "id": s.id,
            "circle_id": s.circle_id,
            "circle_name": s.circle.name,
            "date": s.date.isoformat(),
            "is_confirmed": s.is_confirmed,
        }
        for s in sessions
    ]


@router.post("/")
async def create_session(
    circle_id: int,
    session_date: date,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    result = await db.execute(select(Circle).where(Circle.id == circle_id))
    circle = result.scalar_one_or_none()
    if not circle:
        raise HTTPException(status_code=404, detail="Circle not found")

    session = Session(circle_id=circle_id, date=session_date)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return {"id": session.id, "date": session.date.isoformat(), "circle_id": session.circle_id}


@router.get("/{session_id}/attendance")
async def get_session_attendance(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    from sqlalchemy import select
    from app.models import Session, Sheikh, StudentSheikh, Attendance, Student
    from sqlalchemy.orm import selectinload
    from sqlalchemy.orm import joinedload

    result = await db.execute(
        select(Session)
        .options(
            selectinload(Session.circle).selectinload(Circle.sheikhs).selectinload(Sheikh.students).selectinload(StudentSheikh.student)
        )
        .where(Session.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    sheikh_groups = []
    for sheikh in session.circle.sheikhs:
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
                students_list.append({
                    "id": ss.student.id,
                    "name": ss.student.name,
                    "phone": ss.student.phone,
                    "attendance_id": att.id if att else None,
                    "status": att.status.value if att else "غياب",
                })

        sheikh_groups.append({
            "sheikh": {"id": sheikh.id, "name": sheikh.name},
            "students": students_list,
        })

    return {
        "session_id": session.id,
        "date": session.date.isoformat(),
        "is_confirmed": session.is_confirmed,
        "sheikh_groups": sheikh_groups,
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

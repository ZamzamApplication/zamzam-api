from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete as sa_delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Attendance, AttendanceStatus, Circle, ExcusedWeekday, Session, Sheikh, Student, StudentStatus
from app.routers.auth import get_current_user_depends, require_admin
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
    _=Depends(require_admin),
):
    if body.default_status not in [s.value for s in AttendanceStatus]:
        raise HTTPException(status_code=400, detail=f"Invalid default status")

    result = await db.execute(select(Circle).where(Circle.id == body.circle_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Circle not found")

    session = Session(date=body.session_date, circle_id=body.circle_id)
    db.add(session)
    await db.flush()

    result = await db.execute(
        select(Student)
        .join(Sheikh)
        .where(
            Sheikh.circle_id == body.circle_id,
            Student.status == StudentStatus.enrolled,
        )
    )
    students = result.scalars().all()

    session_weekday = body.session_date.weekday()  # 0=Mon ... 6=Sun
    # Python weekday(): Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6
    # We use: 0=Sun,1=Mon,2=Tue,3=Wed,4=Thu,5=Fri,6=Sat
    # Convert: (wd + 1) % 7
    weekday_local = (session_weekday + 1) % 7

    for s in students:
        if s.registration_date and s.registration_date > body.session_date:
            status = AttendanceStatus.not_applicable
        else:
            result = await db.execute(
                select(ExcusedWeekday).where(
                    ExcusedWeekday.student_id == s.id,
                    ExcusedWeekday.weekday == weekday_local,
                )
            )
            if result.scalar_one_or_none():
                status = AttendanceStatus.not_applicable
            else:
                status = AttendanceStatus(body.default_status)
        db.add(Attendance(
            session_id=session.id,
            student_id=s.id,
            status=status,
        ))

    await db.commit()
    await db.refresh(session)
    return {"id": session.id, "date": session.date.isoformat(), "circle_id": session.circle_id}


@router.put("/{session_id}")
async def update_session(
    session_id: int,
    body: UpdateSessionRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
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
            selectinload(Sheikh.students)
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
        for s in sheikh.students:
            if s.status != StudentStatus.enrolled:
                continue
            att_result = await db.execute(
                select(Attendance).where(
                    Attendance.session_id == session_id,
                    Attendance.student_id == s.id,
                )
            )
            att = att_result.scalar_one_or_none()
            # Default sheikh_id is the student's assigned sheikh, overridden by attendance record
            default_sheikh_id = s.sheikh_id
            att_sheikh_id = att.sheikh_id if att and att.sheikh_id is not None else default_sheikh_id
            if att:
                status = att.status.value
            else:
                status = "لا ينطبق" if s.registration_date and s.registration_date > session.date else "غياب"
            students_list.append({
                "id": s.id,
                "name": s.name,
                "phone": s.phone,
                "profile_pic": s.profile_pic,
                "attendance_id": att.id if att else None,
                "status": status,
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
    _=Depends(require_admin),
):
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Get all enrolled students in this circle
    result = await db.execute(
        select(Student)
        .join(Sheikh)
        .where(
            Sheikh.circle_id == session.circle_id,
            Student.status == StudentStatus.enrolled,
        )
    )
    all_students = result.scalars().all()
    all_student_ids = {s.id for s in all_students}
    student_map = {s.id: s for s in all_students}

    # Get students who already have attendance records for this session
    result = await db.execute(
        select(Attendance.student_id).where(
            Attendance.session_id == session_id,
        )
    )
    with_records = {row[0] for row in result.all()}

    # Create records for students without one
    session_weekday = session.date.weekday()
    weekday_local = (session_weekday + 1) % 7

    missing = all_student_ids - with_records
    for sid in missing:
        s = student_map.get(sid)
        if s and s.registration_date and s.registration_date > session.date:
            status = AttendanceStatus.not_applicable
        else:
            result = await db.execute(
                select(ExcusedWeekday).where(
                    ExcusedWeekday.student_id == sid,
                    ExcusedWeekday.weekday == weekday_local,
                )
            )
            if s and result.scalar_one_or_none():
                status = AttendanceStatus.not_applicable
            else:
                status = AttendanceStatus.absent
        db.add(Attendance(
            session_id=session_id,
            student_id=sid,
            status=status,
        ))

    session.is_confirmed = True
    await db.commit()
    return {"message": "Session confirmed"}


@router.delete("/{session_id}")
async def delete_session(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    await db.execute(sa_delete(Attendance).where(Attendance.session_id == session_id))
    await db.delete(session)
    await db.commit()
    return {"message": "Session deleted"}

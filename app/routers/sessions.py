from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete as sa_delete, select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.media import signed_media_url
from app.models import (
    Attendance,
    AttendanceBatchOperation,
    AttendanceStatus,
    AuditLog,
    ExcusedWeekday,
    QuranProgressEntry,
    Session,
    Sheikh,
    Student,
    StudentStatus,
)
from app.routers.auth import TenantContext, get_tenant_context, require_tenant_admin
from app.schemas import ConfirmSessionRequest, CreateSessionRequest, ReopenSessionRequest, UpdateSessionRequest

router = APIRouter(prefix="/sessions", tags=["sessions"])


def session_status(session: Session) -> str:
    if session.is_confirmed:
        return "confirmed"
    return "reopened" if session.reopened_at else "draft"


def session_summary(session: Session) -> dict:
    return {
        "id": session.id,
        "date": session.date.isoformat(),
        "is_confirmed": session.is_confirmed,
        "status": session_status(session),
        "version": session.version,
        "tahfiz_id": session.tahfiz_id,
        "tahfiz_name": session.tahfiz.name,
        "circle_id": session.tahfiz_id,
        "circle_name": session.tahfiz.name,
    }


@router.get("/all")
async def get_all_sessions(
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    query = (
        select(Session)
        .options(selectinload(Session.tahfiz))
        .where(Session.tahfiz_id == context.tahfiz_id)
        .order_by(Session.date.desc())
    )
    result = await db.execute(query)
    sessions = result.scalars().all()
    return [session_summary(session) for session in sessions]


@router.get("/past")
async def get_past_sessions(
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    query = (
        select(Session)
        .options(selectinload(Session.tahfiz))
        .where(Session.is_confirmed == True, Session.tahfiz_id == context.tahfiz_id)
        .order_by(Session.date.desc())
    )
    result = await db.execute(query)
    sessions = result.scalars().all()
    return [session_summary(session) for session in sessions]


@router.get("/upcoming")
async def get_upcoming_sessions(
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    query = (
        select(Session)
        .options(selectinload(Session.tahfiz))
        .where(Session.is_confirmed == False, Session.tahfiz_id == context.tahfiz_id)
        .order_by(Session.date)
    )
    result = await db.execute(query)
    sessions = result.scalars().all()
    return [session_summary(session) for session in sessions]


@router.post("/")
async def create_session(
    body: CreateSessionRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    if body.default_status not in [s.value for s in AttendanceStatus]:
        raise HTTPException(status_code=400, detail=f"Invalid default status")

    session = Session(date=body.session_date, tahfiz_id=context.tahfiz_id)
    db.add(session)
    await db.flush()

    result = await db.execute(
        select(Student)
        .join(Sheikh)
        .where(
            Sheikh.tahfiz_id == context.tahfiz_id,
            Student.status == StudentStatus.enrolled,
        )
    )
    students = result.scalars().all()

    session_weekday = body.session_date.weekday()  # 0=Mon ... 6=Sun
    # Python weekday(): Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6
    # We use: 0=Sun,1=Mon,2=Tue,3=Wed,4=Thu,5=Fri,6=Sat
    # Convert: (wd + 1) % 7
    weekday_local = (session_weekday + 1) % 7
    excused_rows = (await db.execute(
        select(ExcusedWeekday).where(
            ExcusedWeekday.student_id.in_([student.id for student in students]),
            ExcusedWeekday.weekday == weekday_local,
        )
    )).scalars().all() if students else []
    excused_by_student = {row.student_id: row for row in excused_rows}

    for s in students:
        notes = None
        if s.registration_date and s.registration_date > body.session_date:
            status = AttendanceStatus.not_applicable
        else:
            excused_weekday = excused_by_student.get(s.id)
            if excused_weekday:
                status = AttendanceStatus.not_applicable
                notes = excused_weekday.note
            else:
                status = AttendanceStatus(body.default_status)
        db.add(Attendance(
            session_id=session.id,
            student_id=s.id,
            tahfiz_id=context.tahfiz_id,
            status=status,
            notes=notes,
        ))

    await db.commit()
    await db.refresh(session)
    return {"id": session.id, "date": session.date.isoformat(), "tahfiz_id": session.tahfiz_id, "circle_id": session.tahfiz_id}


@router.put("/{session_id}")
async def update_session(
    session_id: int,
    body: UpdateSessionRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    result = await db.execute(select(Session).where(Session.id == session_id, Session.tahfiz_id == context.tahfiz_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.is_confirmed:
        raise HTTPException(status_code=409, detail="Confirmed sessions must be reopened before changing the date")

    session.date = body.session_date
    session.version += 1
    db.add(AuditLog(
        actor_user_id=context.user.id,
        tahfiz_id=context.tahfiz_id,
        action="session.date_updated",
        details=f"session={session.id}; date={body.session_date.isoformat()}",
    ))
    await db.commit()
    return {"id": session.id, "date": session.date.isoformat(), "version": session.version}


@router.get("/{session_id}/attendance")
async def get_session_attendance(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    result = await db.execute(
        select(Session).options(selectinload(Session.tahfiz)).where(
            Session.id == session_id,
            Session.tahfiz_id == context.tahfiz_id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    result = await db.execute(
        select(Sheikh)
        .options(
            selectinload(Sheikh.students)
        )
        .where(Sheikh.tahfiz_id == session.tahfiz_id)
    )
    circle_sheikhs = result.scalars().all()

    # Get all sheikhs in this circle for the dropdown
    circle_sheikhs_list = [
        {"id": s.id, "name": s.name}
        for s in circle_sheikhs
    ]

    sheikh_groups = []
    session_weekday = session.date.weekday()
    weekday_local = (session_weekday + 1) % 7
    student_ids = [
        student.id
        for sheikh in circle_sheikhs
        for student in sheikh.students
        if student.status == StudentStatus.enrolled
    ]
    attendance_rows = (await db.execute(
        select(Attendance).where(
            Attendance.session_id == session_id,
            Attendance.tahfiz_id == context.tahfiz_id,
            Attendance.student_id.in_(student_ids),
        )
    )).scalars().all() if student_ids else []
    attendance_by_student = {row.student_id: row for row in attendance_rows}
    excused_rows = (await db.execute(
        select(ExcusedWeekday).where(
            ExcusedWeekday.student_id.in_(student_ids),
            ExcusedWeekday.weekday == weekday_local,
        )
    )).scalars().all() if student_ids else []
    excused_by_student = {row.student_id: row for row in excused_rows}

    for sheikh in circle_sheikhs:
        students_list = []
        for s in sheikh.students:
            if s.status != StudentStatus.enrolled:
                continue
            excused_weekday = excused_by_student.get(s.id)
            excused_note = excused_weekday.note if excused_weekday else None
            att = attendance_by_student.get(s.id)
            # Default sheikh_id is the student's assigned sheikh, overridden by attendance record
            default_sheikh_id = s.sheikh_id
            att_sheikh_id = att.sheikh_id if att and att.sheikh_id is not None else default_sheikh_id
            if att:
                status = att.status.value
                notes = att.notes if att.notes is not None else (excused_note if status == AttendanceStatus.not_applicable.value else None)
            else:
                if s.registration_date and s.registration_date > session.date:
                    status = "لا ينطبق"
                    notes = None
                elif excused_weekday:
                    status = "لا ينطبق"
                    notes = excused_note
                else:
                    status = "غياب"
                    notes = None
            students_list.append({
                "id": s.id,
                "name": s.name,
                "phone": s.phone,
                "profile_pic": signed_media_url(s.profile_pic, context.tahfiz_id),
                "attendance_id": att.id if att else None,
                "status": status,
                "notes": notes,
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
        "status": session_status(session),
        "version": session.version,
        "tahfiz_id": session.tahfiz_id,
        "tahfiz_name": session.tahfiz.name,
        "circle_id": session.tahfiz_id,
        "circle_name": session.tahfiz.name,
        "sheikh_groups": sheikh_groups,
        "circle_sheikhs": circle_sheikhs_list,
    }


@router.post("/{session_id}/confirm")
async def confirm_session(
    session_id: int,
    body: ConfirmSessionRequest | None = None,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    result = await db.execute(select(Session).where(Session.id == session_id, Session.tahfiz_id == context.tahfiz_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.is_confirmed:
        return {"message": "Session already confirmed", "status": "confirmed", "version": session.version}
    expected_version = body.expected_version if body else None
    confirm_update = (
        sa_update(Session)
        .where(
            Session.id == session_id,
            Session.tahfiz_id == context.tahfiz_id,
            Session.is_confirmed == False,
        )
        .values(is_confirmed=True, version=Session.version + 1)
        .returning(Session.version)
    )
    if expected_version is not None:
        confirm_update = confirm_update.where(Session.version == expected_version)
    resulting_version = await db.scalar(confirm_update)
    if resulting_version is None:
        current = (await db.execute(select(Session.is_confirmed, Session.version).where(
            Session.id == session_id,
            Session.tahfiz_id == context.tahfiz_id,
        ))).one_or_none()
        if current and current.is_confirmed:
            return {"message": "Session already confirmed", "status": "confirmed", "version": current.version}
        raise HTTPException(
            status_code=409,
            detail={"code": "session_version_conflict", "current_version": current.version if current else None},
        )

    # Get all enrolled students in this circle
    result = await db.execute(
        select(Student)
        .join(Sheikh)
        .where(
            Sheikh.tahfiz_id == session.tahfiz_id,
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
            Attendance.tahfiz_id == context.tahfiz_id,
        )
    )
    with_records = {row[0] for row in result.all()}

    # Create records for students without one
    session_weekday = session.date.weekday()
    weekday_local = (session_weekday + 1) % 7

    missing = all_student_ids - with_records
    excused_rows = (await db.execute(
        select(ExcusedWeekday).where(
            ExcusedWeekday.student_id.in_(missing),
            ExcusedWeekday.weekday == weekday_local,
        )
    )).scalars().all() if missing else []
    excused_by_student = {row.student_id: row for row in excused_rows}
    for sid in missing:
        s = student_map.get(sid)
        notes = None
        if s and s.registration_date and s.registration_date > session.date:
            status = AttendanceStatus.not_applicable
        else:
            excused_weekday = excused_by_student.get(sid)
            if s and excused_weekday:
                status = AttendanceStatus.not_applicable
                notes = excused_weekday.note
            else:
                status = AttendanceStatus.absent
        db.add(Attendance(
            session_id=session_id,
            student_id=sid,
            tahfiz_id=context.tahfiz_id,
            status=status,
            notes=notes,
        ))

    db.add(AuditLog(
        actor_user_id=context.user.id,
        tahfiz_id=context.tahfiz_id,
        action="session.confirmed",
        details=f"session={session.id}; version={resulting_version}",
    ))
    await db.commit()
    return {"message": "Session confirmed", "status": "confirmed", "version": resulting_version}


@router.post("/{session_id}/reopen")
async def reopen_session(
    session_id: int,
    body: ReopenSessionRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    session = await db.scalar(select(Session).where(
        Session.id == session_id,
        Session.tahfiz_id == context.tahfiz_id,
    ))
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.is_confirmed:
        raise HTTPException(status_code=409, detail="Session is already editable")

    reason = body.reason.strip()
    reopen_update = (
        sa_update(Session)
        .where(
            Session.id == session_id,
            Session.tahfiz_id == context.tahfiz_id,
            Session.is_confirmed == True,
        )
        .values(
            is_confirmed=False,
            reopened_at=datetime.utcnow(),
            reopened_reason=reason,
            reopened_by_id=context.user.id,
            version=Session.version + 1,
        )
        .returning(Session.version)
    )
    if body.expected_version is not None:
        reopen_update = reopen_update.where(Session.version == body.expected_version)
    resulting_version = await db.scalar(reopen_update)
    if resulting_version is None:
        current_version = await db.scalar(select(Session.version).where(
            Session.id == session_id,
            Session.tahfiz_id == context.tahfiz_id,
        ))
        raise HTTPException(
            status_code=409,
            detail={"code": "session_version_conflict", "current_version": current_version},
        )
    db.add(AuditLog(
        actor_user_id=context.user.id,
        tahfiz_id=context.tahfiz_id,
        action="session.reopened",
        details=f"session={session.id}; reason={reason}",
    ))
    await db.commit()
    return {"message": "Session reopened", "status": "reopened", "version": resulting_version}


@router.delete("/{session_id}")
async def delete_session(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    result = await db.execute(select(Session).where(Session.id == session_id, Session.tahfiz_id == context.tahfiz_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    await db.execute(sa_delete(QuranProgressEntry).where(
        QuranProgressEntry.session_id == session_id,
        QuranProgressEntry.tahfiz_id == context.tahfiz_id,
    ))
    await db.execute(sa_delete(AttendanceBatchOperation).where(
        AttendanceBatchOperation.session_id == session_id,
        AttendanceBatchOperation.tahfiz_id == context.tahfiz_id,
    ))
    await db.execute(sa_delete(Attendance).where(
        Attendance.session_id == session_id,
        Attendance.tahfiz_id == context.tahfiz_id,
    ))
    db.add(AuditLog(
        actor_user_id=context.user.id,
        tahfiz_id=context.tahfiz_id,
        action="session.deleted",
        details=f"session={session.id}; date={session.date.isoformat()}",
    ))
    await db.delete(session)
    await db.commit()
    return {"message": "Session deleted"}

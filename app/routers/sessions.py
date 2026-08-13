from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete as sa_delete, false, func, select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.excused_periods import automatic_attendance, periods_on_date
from app.time import utcnow
from app.media import signed_media_url
from app.models import (
    ACTIVE_STUDENT_STATUSES,
    Attendance,
    AttendanceBatchOperation,
    AttendanceStatus,
    AuditLog,
    ExcusedWeekday,
    QuranProgressEntry,
    Session,
    Sheikh,
    Student,
    StudentQuranPlan,
    StudentStatus,
    absent_status_option,
)
from app.routers.auth import TenantContext, get_tenant_context, require_tenant_admin
from app.schemas import ConfirmSessionRequest, CreateSessionRequest, ReopenSessionRequest, SessionQuranProgressRequest, UpdateSessionMembershipRequest, UpdateSessionRequest

router = APIRouter(prefix="/sessions", tags=["sessions"])


def session_status(session: Session) -> str:
    if session.is_confirmed:
        return "confirmed"
    return "reopened" if session.reopened_at else "draft"


def student_is_in_session(session: Session, attendance: Attendance | None) -> bool:
    """Use persisted attendance as the membership snapshot once confirmed."""
    if session.explicit_membership:
        return attendance is not None
    return not session.is_confirmed or attendance is not None


def session_summary(session: Session) -> dict:
    return {
        "id": session.id,
        "date": session.date.isoformat(),
        "name": session.name,
        "daily_sequence": session.daily_sequence,
        "explicit_membership": session.explicit_membership,
        "student_count": len(session.attendance_records),
        "is_confirmed": session.is_confirmed,
        "quran_progress_enabled": session.quran_progress_enabled,
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
        .options(selectinload(Session.tahfiz), selectinload(Session.attendance_records))
        .where(Session.tahfiz_id == context.tahfiz_id)
        .order_by(Session.date.desc(), Session.daily_sequence.desc(), Session.id.desc())
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
        .options(selectinload(Session.tahfiz), selectinload(Session.attendance_records))
        .where(Session.is_confirmed == True, Session.tahfiz_id == context.tahfiz_id)
        .order_by(Session.date.desc(), Session.daily_sequence.desc(), Session.id.desc())
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
        .options(selectinload(Session.tahfiz), selectinload(Session.attendance_records))
        .where(Session.is_confirmed == False, Session.tahfiz_id == context.tahfiz_id)
        .order_by(Session.date, Session.daily_sequence, Session.id)
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
    multiple_enabled = context.tahfiz.multiple_sessions_per_day_enabled
    if not multiple_enabled:
        duplicate = await db.scalar(select(Session.id).where(
            Session.tahfiz_id == context.tahfiz_id,
            Session.date == body.session_date,
        ).limit(1))
        if duplicate is not None:
            raise HTTPException(status_code=409, detail={
                "code": "session_date_exists",
                "message": "توجد حلقة بالفعل في هذا التاريخ. فعّل خيار تعدد الحلقات اليومية لإنشاء حلقة أخرى.",
            })
        if body.student_ids is not None:
            raise HTTPException(status_code=400, detail={"code": "multiple_sessions_disabled"})
    elif body.student_ids is None:
        raise HTTPException(status_code=422, detail={"code": "session_students_required"})

    daily_sequence = int(await db.scalar(select(func.coalesce(func.max(Session.daily_sequence), 0)).where(
        Session.tahfiz_id == context.tahfiz_id,
        Session.date == body.session_date,
    )) or 0) + 1
    session = Session(
        date=body.session_date,
        name=body.name,
        daily_sequence=daily_sequence,
        explicit_membership=multiple_enabled,
        tahfiz_id=context.tahfiz_id,
        quran_progress_enabled=context.tahfiz.progress_tracking_enabled,
    )
    db.add(session)
    await db.flush()

    result = await db.execute(
        select(Student)
        .join(Sheikh)
        .where(
            Sheikh.tahfiz_id == context.tahfiz_id,
            Student.status.in_(ACTIVE_STUDENT_STATUSES),
            *([Student.id.in_(body.student_ids)] if multiple_enabled else []),
        )
    )
    students = result.scalars().all()
    if multiple_enabled and {student.id for student in students} != set(body.student_ids or []):
        raise HTTPException(status_code=404, detail="One or more selected students were not found")

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
    period_by_student = await periods_on_date(
        db, context.tahfiz_id, [student.id for student in students], body.session_date
    )

    for s in students:
        status, notes = automatic_attendance(
            context.tahfiz,
            s,
            body.session_date,
            absent_status_option(context.tahfiz),
            period=period_by_student.get(s.id),
            weekday=excused_by_student.get(s.id),
        )
        db.add(Attendance(
            session_id=session.id,
            student_id=s.id,
            tahfiz_id=context.tahfiz_id,
            status=status,
            notes=notes,
        ))

    await db.commit()
    await db.refresh(session)
    return {
        "id": session.id,
        "date": session.date.isoformat(),
        "name": session.name,
        "daily_sequence": session.daily_sequence,
        "explicit_membership": session.explicit_membership,
        "student_count": len(students),
        "quran_progress_enabled": session.quran_progress_enabled,
        "tahfiz_id": session.tahfiz_id,
        "circle_id": session.tahfiz_id,
    }


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

    if session.date != body.session_date:
        if not context.tahfiz.multiple_sessions_per_day_enabled and not session.explicit_membership:
            duplicate = await db.scalar(select(Session.id).where(
                Session.tahfiz_id == context.tahfiz_id,
                Session.date == body.session_date,
                Session.id != session.id,
            ).limit(1))
            if duplicate is not None:
                raise HTTPException(status_code=409, detail={
                    "code": "session_date_exists",
                    "message": "توجد حلقة بالفعل في هذا التاريخ.",
                })
        session.daily_sequence = int(await db.scalar(select(func.coalesce(func.max(Session.daily_sequence), 0)).where(
            Session.tahfiz_id == context.tahfiz_id,
            Session.date == body.session_date,
            Session.id != session.id,
        )) or 0) + 1
        session.date = body.session_date
        await db.execute(sa_update(StudentQuranPlan).where(
            StudentQuranPlan.tahfiz_id == context.tahfiz_id,
            StudentQuranPlan.last_advanced_session_id == session.id,
        ).values(last_advanced_on=body.session_date, updated_at=utcnow()))
    if "name" in body.model_fields_set:
        session.name = body.name
    session.version += 1
    db.add(AuditLog(
        actor_user_id=context.user.id,
        tahfiz_id=context.tahfiz_id,
        action="session.date_updated",
        details=f"session={session.id}; date={body.session_date.isoformat()}",
    ))
    await db.commit()
    return {
        "id": session.id,
        "date": session.date.isoformat(),
        "name": session.name,
        "daily_sequence": session.daily_sequence,
        "version": session.version,
    }


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
        .where(
            Sheikh.tahfiz_id == session.tahfiz_id,
            *(
                [Sheikh.id == context.sheikh_id]
                if context.restricts_sheikh_students and context.sheikh_id is not None
                else [false()]
                if context.restricts_sheikh_students
                else []
            ),
        )
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
        if student.status in ACTIVE_STUDENT_STATUSES
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
    period_by_student = await periods_on_date(
        db, context.tahfiz_id, student_ids, session.date
    )

    for sheikh in circle_sheikhs:
        students_list = []
        for s in sheikh.students:
            if s.status not in ACTIVE_STUDENT_STATUSES:
                continue
            excused_weekday = excused_by_student.get(s.id)
            excused_note = excused_weekday.note if excused_weekday else None
            att = attendance_by_student.get(s.id)
            # Attendance rows are the membership snapshot for a confirmed session.
            # A student added later must not be synthesized into that snapshot.
            if not student_is_in_session(session, att):
                continue
            # Default sheikh_id is the student's assigned sheikh, overridden by attendance record
            default_sheikh_id = s.sheikh_id
            att_sheikh_id = att.sheikh_id if att and att.sheikh_id is not None else default_sheikh_id
            if att:
                status = att.status
                notes = att.notes if att.notes is not None else (excused_note if status == AttendanceStatus.not_applicable.value else None)
            else:
                status, notes = automatic_attendance(
                    context.tahfiz,
                    s,
                    session.date,
                    absent_status_option(context.tahfiz),
                    period=period_by_student.get(s.id),
                    weekday=excused_weekday,
                )
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
        "name": session.name,
        "daily_sequence": session.daily_sequence,
        "explicit_membership": session.explicit_membership,
        "student_count": sum(len(group["students"]) for group in sheikh_groups),
        "is_confirmed": session.is_confirmed,
        "quran_progress_enabled": session.quran_progress_enabled,
        "status": session_status(session),
        "version": session.version,
        "tahfiz_id": session.tahfiz_id,
        "tahfiz_name": session.tahfiz.name,
        "circle_id": session.tahfiz_id,
        "circle_name": session.tahfiz.name,
        "sheikh_groups": sheikh_groups,
        "circle_sheikhs": circle_sheikhs_list,
    }


@router.put("/{session_id}/membership")
async def update_session_membership(
    session_id: int,
    body: UpdateSessionMembershipRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    session = await db.scalar(select(Session).where(
        Session.id == session_id,
        Session.tahfiz_id == context.tahfiz_id,
    ))
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.explicit_membership:
        raise HTTPException(status_code=409, detail={"code": "session_membership_not_selective"})
    if session.is_confirmed:
        raise HTTPException(status_code=409, detail="Confirmed sessions must be reopened before changing membership")
    if body.expected_version is not None and session.version != body.expected_version:
        raise HTTPException(
            status_code=409,
            detail={"code": "session_version_conflict", "current_version": session.version},
        )

    requested_ids = set(body.student_ids)
    students = (await db.execute(
        select(Student)
        .join(Sheikh)
        .where(
            Sheikh.tahfiz_id == context.tahfiz_id,
            Student.status.in_(ACTIVE_STUDENT_STATUSES),
            Student.id.in_(requested_ids),
        )
    )).scalars().all()
    if {student.id for student in students} != requested_ids:
        raise HTTPException(status_code=404, detail="One or more selected students were not found")

    existing_rows = (await db.execute(select(Attendance).where(
        Attendance.session_id == session_id,
        Attendance.tahfiz_id == context.tahfiz_id,
    ))).scalars().all()
    existing_by_student = {row.student_id: row for row in existing_rows if row.student_id is not None}
    removed_ids = set(existing_by_student) - requested_ids
    if removed_ids:
        progress_student = await db.scalar(select(QuranProgressEntry.student_id).where(
            QuranProgressEntry.session_id == session_id,
            QuranProgressEntry.tahfiz_id == context.tahfiz_id,
            QuranProgressEntry.student_id.in_(removed_ids),
        ).limit(1))
        if progress_student is not None:
            raise HTTPException(status_code=409, detail={
                "code": "session_member_has_quran_progress",
                "student_id": progress_student,
                "message": "لا يمكن حذف الطالب من الحلقة لأن له مقدار قرآن محفوظاً فيها. امسح المقدار أولاً.",
            })
        await db.execute(sa_delete(Attendance).where(
            Attendance.session_id == session_id,
            Attendance.tahfiz_id == context.tahfiz_id,
            Attendance.student_id.in_(removed_ids),
        ))

    added = [student for student in students if student.id not in existing_by_student]
    weekday_local = (session.date.weekday() + 1) % 7
    added_ids = [student.id for student in added]
    excused_rows = (await db.execute(select(ExcusedWeekday).where(
        ExcusedWeekday.student_id.in_(added_ids),
        ExcusedWeekday.weekday == weekday_local,
    ))).scalars().all() if added_ids else []
    excused_by_student = {row.student_id: row for row in excused_rows}
    period_by_student = await periods_on_date(db, context.tahfiz_id, added_ids, session.date)
    for student in added:
        status, notes = automatic_attendance(
            context.tahfiz,
            student,
            session.date,
            absent_status_option(context.tahfiz),
            period=period_by_student.get(student.id),
            weekday=excused_by_student.get(student.id),
        )
        db.add(Attendance(
            session_id=session_id,
            student_id=student.id,
            tahfiz_id=context.tahfiz_id,
            status=status,
            notes=notes,
        ))

    if added or removed_ids:
        session.version += 1
        db.add(AuditLog(
            actor_user_id=context.user.id,
            tahfiz_id=context.tahfiz_id,
            action="session.membership_updated",
            details=f"session={session.id}; added={len(added)}; removed={len(removed_ids)}; version={session.version}",
        ))
        await db.commit()
    return {
        "session_id": session.id,
        "student_ids": sorted(requested_ids),
        "student_count": len(requested_ids),
        "version": session.version,
    }


@router.put("/{session_id}/progress-tracking")
async def update_session_progress_tracking(
    session_id: int,
    body: SessionQuranProgressRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    session = await db.scalar(select(Session).where(
        Session.id == session_id,
        Session.tahfiz_id == context.tahfiz_id,
    ))
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.is_confirmed:
        raise HTTPException(status_code=409, detail="Confirmed sessions must be reopened before changing Quran progress")
    if body.expected_version is not None and session.version != body.expected_version:
        raise HTTPException(
            status_code=409,
            detail={"code": "session_version_conflict", "current_version": session.version},
        )
    if not body.enabled:
        has_progress = await db.scalar(select(QuranProgressEntry.id).where(
            QuranProgressEntry.session_id == session_id,
            QuranProgressEntry.tahfiz_id == context.tahfiz_id,
        ).limit(1))
        if has_progress is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "session_progress_exists",
                    "reason": "لا يمكن إيقاف المتابعة بعد حفظ مقدار قرآن في هذه الحلقة",
                },
            )
    if session.quran_progress_enabled != body.enabled:
        session.quran_progress_enabled = body.enabled
        session.version += 1
        db.add(AuditLog(
            actor_user_id=context.user.id,
            tahfiz_id=context.tahfiz_id,
            action="session.quran_progress_toggled",
            details=f"session={session.id}; enabled={str(body.enabled).lower()}",
        ))
        await db.commit()
    return {
        "session_id": session.id,
        "quran_progress_enabled": session.quran_progress_enabled,
        "version": session.version,
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
            Student.status.in_(ACTIVE_STUDENT_STATUSES),
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

    missing = set() if session.explicit_membership else all_student_ids - with_records
    excused_rows = (await db.execute(
        select(ExcusedWeekday).where(
            ExcusedWeekday.student_id.in_(missing),
            ExcusedWeekday.weekday == weekday_local,
        )
    )).scalars().all() if missing else []
    excused_by_student = {row.student_id: row for row in excused_rows}
    period_by_student = await periods_on_date(
        db, context.tahfiz_id, missing, session.date
    )
    for sid in missing:
        s = student_map.get(sid)
        if not s:
            continue
        status, notes = automatic_attendance(
            context.tahfiz,
            s,
            session.date,
            absent_status_option(context.tahfiz),
            period=period_by_student.get(sid),
            weekday=excused_by_student.get(sid),
        )
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
            reopened_at=utcnow(),
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
    if session.is_confirmed:
        raise HTTPException(status_code=409, detail={
            "code": "confirmed_session_delete_forbidden",
            "message": "Confirmed sessions must be reopened before permanent deletion",
            "required_action": "reopen",
        })

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
        details=(
            f"session={session.id}; date={session.date.isoformat()}; "
            f"previous_status={session_status(session)}"
        ),
    ))
    await db.delete(session)
    await db.commit()
    return {"message": "Session deleted"}

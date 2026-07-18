from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Attendance, AttendanceBatchOperation, AttendanceStatus, AuditLog, Session, Sheikh, Student
from app.routers.auth import TenantContext, get_tenant_context
from app.schemas import AttendanceBatchRequest, UpdateAttendanceRequest, UpsertAttendanceRequest

router = APIRouter(prefix="/attendance", tags=["attendance"])


@router.patch("/{attendance_id}")
async def update_attendance(
    attendance_id: int,
    body: UpdateAttendanceRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    if body.status not in [s.value for s in AttendanceStatus]:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {[s.value for s in AttendanceStatus]}")
    if body.sheikh_id is not None:
        sheikh = await db.scalar(select(Sheikh).where(
            Sheikh.id == body.sheikh_id,
            Sheikh.tahfiz_id == context.tahfiz_id,
        ))
        if not sheikh:
            raise HTTPException(status_code=404, detail="Sheikh not found")

    result = await db.execute(select(Attendance).where(
        Attendance.id == attendance_id,
        Attendance.tahfiz_id == context.tahfiz_id,
    ))
    attendance = result.scalar_one_or_none()
    if not attendance:
        raise HTTPException(status_code=404, detail="Attendance record not found")
    session = await db.scalar(select(Session).where(
        Session.id == attendance.session_id,
        Session.tahfiz_id == context.tahfiz_id,
    ))
    if not session or session.is_confirmed:
        raise HTTPException(status_code=409, detail="Confirmed sessions are locked")

    attendance.status = AttendanceStatus(body.status)
    if body.notes is not None:
        attendance.notes = body.notes
    if body.sheikh_id is not None:
        attendance.sheikh_id = body.sheikh_id
    session.version += 1
    await db.commit()
    return {"id": attendance.id, "status": attendance.status.value, "notes": attendance.notes, "sheikh_id": attendance.sheikh_id, "version": session.version}


@router.post("/upsert")
async def upsert_attendance(
    body: UpsertAttendanceRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    if body.status not in [s.value for s in AttendanceStatus]:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {[s.value for s in AttendanceStatus]}")
    if body.sheikh_id is not None:
        sheikh = await db.scalar(select(Sheikh).where(
            Sheikh.id == body.sheikh_id,
            Sheikh.tahfiz_id == context.tahfiz_id,
        ))
        if not sheikh:
            raise HTTPException(status_code=404, detail="Sheikh not found")

    session = await db.scalar(select(Session).where(
        Session.id == body.session_id,
        Session.tahfiz_id == context.tahfiz_id,
    ))
    student = await db.scalar(select(Student).where(
        Student.id == body.student_id,
        Student.tahfiz_id == context.tahfiz_id,
    ))
    if not session or not student:
        raise HTTPException(status_code=404, detail="Session or student not found")
    if session.is_confirmed:
        raise HTTPException(status_code=409, detail="Confirmed sessions are locked")

    result = await db.execute(
        select(Attendance).where(
            Attendance.session_id == body.session_id,
            Attendance.student_id == body.student_id,
            Attendance.tahfiz_id == context.tahfiz_id,
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
            tahfiz_id=context.tahfiz_id,
            status=AttendanceStatus(body.status),
            notes=body.notes,
            sheikh_id=body.sheikh_id,
        )
        db.add(attendance)

    session.version += 1
    await db.commit()
    await db.refresh(attendance)
    return {"id": attendance.id, "status": attendance.status.value, "notes": attendance.notes, "session_id": attendance.session_id, "student_id": attendance.student_id, "sheikh_id": attendance.sheikh_id, "version": session.version}


@router.post("/batch")
async def batch_attendance(
    body: AttendanceBatchRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=100),
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    existing_operation = await db.scalar(select(AttendanceBatchOperation).where(
        AttendanceBatchOperation.tahfiz_id == context.tahfiz_id,
        AttendanceBatchOperation.idempotency_key == idempotency_key,
    ))
    if existing_operation:
        if existing_operation.session_id != body.session_id:
            raise HTTPException(status_code=409, detail="Idempotency key was used for another session")
        return {
            "session_id": existing_operation.session_id,
            "version": existing_operation.resulting_version,
            "saved": len(body.updates),
            "replayed": True,
        }

    session = await db.scalar(select(Session).where(
        Session.id == body.session_id,
        Session.tahfiz_id == context.tahfiz_id,
    ))
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.is_confirmed:
        raise HTTPException(status_code=409, detail="Confirmed sessions are locked")
    if body.expected_version is not None and body.expected_version != session.version:
        raise HTTPException(
            status_code=409,
            detail={"code": "session_version_conflict", "current_version": session.version},
        )

    student_ids = {item.student_id for item in body.updates}
    valid_student_ids = set((await db.execute(
        select(Student.id).where(
            Student.id.in_(student_ids),
            Student.tahfiz_id == context.tahfiz_id,
        )
    )).scalars().all())
    if valid_student_ids != student_ids:
        raise HTTPException(status_code=404, detail="One or more students were not found")

    sheikh_ids = {item.sheikh_id for item in body.updates if item.sheikh_id is not None}
    if sheikh_ids:
        valid_sheikh_ids = set((await db.execute(
            select(Sheikh.id).where(
                Sheikh.id.in_(sheikh_ids),
                Sheikh.tahfiz_id == context.tahfiz_id,
            )
        )).scalars().all())
        if valid_sheikh_ids != sheikh_ids:
            raise HTTPException(status_code=404, detail="One or more sheikhs were not found")

    version_update = (
        update(Session)
        .where(
            Session.id == session.id,
            Session.tahfiz_id == context.tahfiz_id,
            Session.is_confirmed == False,
        )
        .values(version=Session.version + 1)
        .returning(Session.version)
    )
    if body.expected_version is not None:
        version_update = version_update.where(Session.version == body.expected_version)
    resulting_version = await db.scalar(version_update)
    if resulting_version is None:
        current_version = await db.scalar(select(Session.version).where(
            Session.id == body.session_id,
            Session.tahfiz_id == context.tahfiz_id,
        ))
        raise HTTPException(
            status_code=409,
            detail={"code": "session_version_conflict", "current_version": current_version},
        )

    for item in body.updates:
        if item.status not in [status.value for status in AttendanceStatus]:
            raise HTTPException(status_code=400, detail=f"Invalid attendance status: {item.status}")
        values = {
            "session_id": body.session_id,
            "student_id": item.student_id,
            "tahfiz_id": context.tahfiz_id,
            "status": AttendanceStatus(item.status),
            "notes": item.notes,
            "sheikh_id": item.sheikh_id,
        }
        statement = sqlite_insert(Attendance).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=["session_id", "student_id"],
            set_={
                "status": statement.excluded.status,
                "notes": statement.excluded.notes,
                "sheikh_id": statement.excluded.sheikh_id,
                "tahfiz_id": context.tahfiz_id,
            },
        )
        await db.execute(statement)

    db.add(AttendanceBatchOperation(
        tahfiz_id=context.tahfiz_id,
        session_id=session.id,
        idempotency_key=idempotency_key,
        resulting_version=resulting_version,
    ))
    db.add(AuditLog(
        actor_user_id=context.user.id,
        tahfiz_id=context.tahfiz_id,
        action="attendance.batch_updated",
        details=f"session={session.id}; records={len(body.updates)}; version={resulting_version}",
    ))
    await db.commit()
    return {
        "session_id": session.id,
        "version": resulting_version,
        "saved": len(body.updates),
        "replayed": False,
    }

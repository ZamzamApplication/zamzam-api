import json
from datetime import date, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.media import signed_media_url
from app.models import (
    Attendance,
    AuditLog,
    ProgressCategory,
    QuranProgressEntry,
    QuranProgressRevision,
    QuranRangeType,
    Session,
    Sheikh,
    Student,
    SyncChange,
    SyncMutationReceipt,
    attendance_status_options,
)
from app.routers.auth import TenantContext, get_tenant_context
from app.routers.progress import progress_snapshot
from app.schemas import QuranProgressItem


router = APIRouter(prefix="/sync/v1", tags=["mobile-sync"])


class SyncMutation(BaseModel):
    mutation_id: str = Field(min_length=8, max_length=64)
    device_id: str = Field(min_length=8, max_length=100)
    entity_type: Literal["attendance", "quran_progress"]
    entity_key: str = Field(min_length=1, max_length=160)
    base_revision: int = Field(ge=0)
    values: dict[str, Any]
    client_changed_at: datetime | None = None


class SyncMutationBatch(BaseModel):
    mutations: list[SyncMutation] = Field(min_length=1, max_length=500)


def serialize_session(row: Session) -> dict[str, Any]:
    return {
        "id": row.id,
        "tahfiz_id": row.tahfiz_id,
        "date": row.date.isoformat(),
        "is_confirmed": row.is_confirmed,
        "version": row.version,
        "reopened_at": row.reopened_at.isoformat() if row.reopened_at else None,
    }


def serialize_student(row: Student) -> dict[str, Any]:
    return {
        "id": row.id,
        "tahfiz_id": row.tahfiz_id,
        "name": row.name,
        "phone": row.phone,
        "student_code": row.student_id,
        "profile_pic": signed_media_url(row.profile_pic, row.tahfiz_id),
        "status": row.status.value,
        "registration_date": row.registration_date.isoformat() if row.registration_date else None,
        "sheikh_id": row.sheikh_id,
        "sort_order": row.sort_order,
    }


def serialize_sheikh(row: Sheikh) -> dict[str, Any]:
    return {
        "id": row.id,
        "tahfiz_id": row.tahfiz_id,
        "name": row.name,
        "phone": row.phone,
    }


def serialize_attendance(row: Attendance) -> dict[str, Any]:
    return {
        "id": row.id,
        "tahfiz_id": row.tahfiz_id,
        "session_id": row.session_id,
        "student_id": row.student_id,
        "sheikh_id": row.sheikh_id,
        "status": row.status,
        "notes": row.notes,
        "revision": row.revision,
        "updated_at": row.updated_at.isoformat(),
    }


def serialize_progress(row: QuranProgressEntry) -> dict[str, Any]:
    return {
        "id": row.id,
        "tahfiz_id": row.tahfiz_id,
        "session_id": row.session_id,
        "student_id": row.student_id,
        "sheikh_id": row.sheikh_id,
        "recorded_by_id": row.recorded_by_id,
        "category": row.category.value,
        "range_type": row.range_type.value,
        "from_surah": row.from_surah,
        "from_ayah": row.from_ayah,
        "to_surah": row.to_surah,
        "to_ayah": row.to_ayah,
        "from_page": row.from_page,
        "to_page": row.to_page,
        "quality_score": row.quality_score,
        "mistakes": row.mistakes,
        "notes": row.notes,
        "next_assignment": row.next_assignment,
        "revision": row.revision,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


async def current_cursor(db: AsyncSession, tahfiz_id: int) -> int:
    return int(await db.scalar(
        select(func.coalesce(func.max(SyncChange.id), 0)).where(SyncChange.tahfiz_id == tahfiz_id)
    ) or 0)


@router.get("/bootstrap")
async def bootstrap(
    history_days: int = Query(default=90, ge=7, le=3650),
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    cutoff = date.today() - timedelta(days=history_days)
    sessions = (await db.execute(
        select(Session)
        .where(
            Session.tahfiz_id == context.tahfiz_id,
            or_(Session.is_confirmed.is_(False), Session.date >= cutoff),
        )
        .order_by(Session.date.desc(), Session.id.desc())
    )).scalars().all()
    session_ids = [row.id for row in sessions]
    students = (await db.execute(
        select(Student)
        .where(Student.tahfiz_id == context.tahfiz_id)
        .order_by(Student.sort_order, Student.name)
    )).scalars().all()
    sheikhs = (await db.execute(
        select(Sheikh)
        .where(Sheikh.tahfiz_id == context.tahfiz_id)
        .order_by(Sheikh.name)
    )).scalars().all()
    attendance = (await db.execute(
        select(Attendance).where(
            Attendance.tahfiz_id == context.tahfiz_id,
            Attendance.session_id.in_(session_ids),
        )
    )).scalars().all() if session_ids else []
    progress = (await db.execute(
        select(QuranProgressEntry).where(
            QuranProgressEntry.tahfiz_id == context.tahfiz_id,
            QuranProgressEntry.session_id.in_(session_ids),
        )
    )).scalars().all() if session_ids else []

    return {
        "schema_version": 1,
        "cursor": await current_cursor(db, context.tahfiz_id),
        "server_time": datetime.utcnow().isoformat(),
        "tahfiz": {
            "id": context.tahfiz.id,
            "name": context.tahfiz.name,
            "attendance_statuses": attendance_status_options(context.tahfiz),
            "progress_tracking_enabled": context.tahfiz.progress_tracking_enabled,
            "week_start_day": context.tahfiz.week_start_day,
            "month_start_day": context.tahfiz.month_start_day,
        },
        "sheikhs": [serialize_sheikh(row) for row in sheikhs],
        "students": [serialize_student(row) for row in students],
        "sessions": [serialize_session(row) for row in sessions],
        "attendance": [serialize_attendance(row) for row in attendance],
        "quran_progress": [serialize_progress(row) for row in progress],
    }


async def change_payload(db: AsyncSession, change: SyncChange) -> dict[str, Any] | None:
    if change.operation == "delete":
        return None
    if change.entity_type == "attendance":
        row = await db.get(Attendance, int(change.entity_key))
        return serialize_attendance(row) if row and row.tahfiz_id == change.tahfiz_id else None
    if change.entity_type == "session":
        row = await db.get(Session, int(change.entity_key))
        return serialize_session(row) if row and row.tahfiz_id == change.tahfiz_id else None
    if change.entity_type == "student":
        row = await db.get(Student, int(change.entity_key))
        return serialize_student(row) if row and row.tahfiz_id == change.tahfiz_id else None
    if change.entity_type == "sheikh":
        row = await db.get(Sheikh, int(change.entity_key))
        return serialize_sheikh(row) if row and row.tahfiz_id == change.tahfiz_id else None
    if change.entity_type == "quran_progress":
        session_id, student_id, category = change.entity_key.split(":", 2)
        row = await db.scalar(select(QuranProgressEntry).where(
            QuranProgressEntry.tahfiz_id == change.tahfiz_id,
            QuranProgressEntry.session_id == int(session_id),
            QuranProgressEntry.student_id == int(student_id),
            QuranProgressEntry.category == ProgressCategory(category),
        ))
        return serialize_progress(row) if row else None
    return None


@router.get("/changes")
async def changes(
    cursor: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    rows = (await db.execute(
        select(SyncChange)
        .where(SyncChange.tahfiz_id == context.tahfiz_id, SyncChange.id > cursor)
        .order_by(SyncChange.id)
        .limit(limit)
    )).scalars().all()
    items = []
    for row in rows:
        payload = await change_payload(db, row)
        operation = row.operation if payload is not None else "delete"
        items.append({
            "cursor": row.id,
            "entity_type": row.entity_type,
            "entity_key": row.entity_key,
            "operation": operation,
            "payload": payload,
        })
    next_cursor = rows[-1].id if rows else cursor
    more = bool(await db.scalar(select(SyncChange.id).where(
        SyncChange.tahfiz_id == context.tahfiz_id,
        SyncChange.id > next_cursor,
    ).limit(1)))
    return {"changes": items, "next_cursor": next_cursor, "has_more": more}


async def apply_attendance(
    mutation: SyncMutation,
    db: AsyncSession,
    context: TenantContext,
) -> dict[str, Any]:
    values = mutation.values
    try:
        session_id = int(values["session_id"])
        student_id = int(values["student_id"])
        status = str(values["status"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Invalid attendance mutation")
    session = await db.scalar(select(Session).where(
        Session.id == session_id,
        Session.tahfiz_id == context.tahfiz_id,
    ))
    student = await db.scalar(select(Student).where(
        Student.id == student_id,
        Student.tahfiz_id == context.tahfiz_id,
    ))
    if not session or not student:
        return {"status": "rejected", "code": "entity_not_found"}
    if session.is_confirmed:
        return {"status": "rejected", "code": "session_locked"}
    if status not in attendance_status_options(context.tahfiz):
        return {"status": "rejected", "code": "invalid_attendance_status"}
    row = await db.scalar(select(Attendance).where(
        Attendance.session_id == session_id,
        Attendance.student_id == student_id,
        Attendance.tahfiz_id == context.tahfiz_id,
    ))
    current_revision = row.revision if row else 0
    if current_revision != mutation.base_revision:
        return {
            "status": "conflict",
            "code": "revision_conflict",
            "server": serialize_attendance(row) if row else None,
            "local": values,
        }
    sheikh_id = values.get("sheikh_id")
    if sheikh_id is not None and not await db.scalar(select(Sheikh.id).where(
        Sheikh.id == int(sheikh_id),
        Sheikh.tahfiz_id == context.tahfiz_id,
    )):
        return {"status": "rejected", "code": "invalid_sheikh"}
    now = datetime.utcnow()
    if row:
        row.status = status
        row.notes = values.get("notes")
        row.sheikh_id = int(sheikh_id) if sheikh_id is not None else None
        row.revision += 1
        row.updated_at = now
    else:
        row = Attendance(
            session_id=session_id,
            student_id=student_id,
            tahfiz_id=context.tahfiz_id,
            status=status,
            notes=values.get("notes"),
            sheikh_id=int(sheikh_id) if sheikh_id is not None else None,
            revision=1,
            updated_at=now,
        )
        db.add(row)
    session.version += 1
    await db.flush()
    return {"status": "applied", "entity": serialize_attendance(row)}


async def apply_progress(
    mutation: SyncMutation,
    db: AsyncSession,
    context: TenantContext,
) -> dict[str, Any]:
    if not context.tahfiz.progress_tracking_enabled:
        return {"status": "rejected", "code": "progress_tracking_disabled"}
    try:
        item = QuranProgressItem.model_validate(mutation.values)
        category = ProgressCategory(item.category)
        range_type = QuranRangeType(item.range_type)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="Invalid Quran progress mutation")
    session_id = int(mutation.values.get("session_id", 0))
    session = await db.scalar(select(Session).where(
        Session.id == session_id,
        Session.tahfiz_id == context.tahfiz_id,
    ))
    student = await db.scalar(select(Student).where(
        Student.id == item.student_id,
        Student.tahfiz_id == context.tahfiz_id,
    ))
    if not session or not student:
        return {"status": "rejected", "code": "entity_not_found"}
    if session.is_confirmed:
        return {"status": "rejected", "code": "session_locked"}
    row = await db.scalar(select(QuranProgressEntry).where(
        QuranProgressEntry.tahfiz_id == context.tahfiz_id,
        QuranProgressEntry.session_id == session_id,
        QuranProgressEntry.student_id == item.student_id,
        QuranProgressEntry.category == category,
    ))
    current_revision = row.revision if row else 0
    if current_revision != mutation.base_revision:
        return {
            "status": "conflict",
            "code": "revision_conflict",
            "server": serialize_progress(row) if row else None,
            "local": mutation.values,
        }
    before = progress_snapshot(row) if row else None
    values = {
        "sheikh_id": item.sheikh_id,
        "recorded_by_id": context.user.id,
        "range_type": range_type,
        "from_surah": item.from_surah,
        "from_ayah": item.from_ayah,
        "to_surah": item.to_surah,
        "to_ayah": item.to_ayah,
        "from_page": item.from_page,
        "to_page": item.to_page,
        "quality_score": item.quality_score,
        "mistakes": item.mistakes,
        "notes": item.notes,
        "next_assignment": item.next_assignment,
        "updated_at": datetime.utcnow(),
    }
    if row:
        after = progress_snapshot(item)
        if before != after:
            db.add(QuranProgressRevision(
                tahfiz_id=context.tahfiz_id,
                progress_entry_id=row.id,
                session_id=session_id,
                student_id=item.student_id,
                category=category,
                editor_user_id=context.user.id,
                before_json=json.dumps(before, ensure_ascii=False, sort_keys=True),
                after_json=json.dumps(after, ensure_ascii=False, sort_keys=True),
            ))
        for key, value in values.items():
            setattr(row, key, value)
        row.revision += 1
    else:
        row = QuranProgressEntry(
            tahfiz_id=context.tahfiz_id,
            session_id=session_id,
            student_id=item.student_id,
            category=category,
            revision=1,
            **values,
        )
        db.add(row)
    await db.flush()
    return {"status": "applied", "entity": serialize_progress(row)}


@router.post("/mutations")
async def mutations(
    body: SyncMutationBatch,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    results = []
    for mutation in body.mutations:
        receipt = await db.scalar(select(SyncMutationReceipt).where(
            SyncMutationReceipt.tahfiz_id == context.tahfiz_id,
            SyncMutationReceipt.mutation_id == mutation.mutation_id,
        ))
        if receipt:
            replay = json.loads(receipt.result_json)
            replay["replayed"] = True
            results.append(replay)
            continue
        result = (
            await apply_attendance(mutation, db, context)
            if mutation.entity_type == "attendance"
            else await apply_progress(mutation, db, context)
        )
        result = {"mutation_id": mutation.mutation_id, **result, "replayed": False}
        db.add(SyncMutationReceipt(
            tahfiz_id=context.tahfiz_id,
            mutation_id=mutation.mutation_id,
            device_id=mutation.device_id,
            result_json=json.dumps(result, ensure_ascii=False, sort_keys=True),
        ))
        results.append(result)
    db.add(AuditLog(
        actor_user_id=context.user.id,
        tahfiz_id=context.tahfiz_id,
        action="sync.mutations_processed",
        details=json.dumps({
            "count": len(body.mutations),
            "applied": sum(item["status"] == "applied" for item in results),
            "conflicts": sum(item["status"] == "conflict" for item in results),
        }, sort_keys=True),
    ))
    await db.commit()
    return {"results": results, "cursor": await current_cursor(db, context.tahfiz_id)}

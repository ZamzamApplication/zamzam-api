import json
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    AuditLog,
    ProgressCategory,
    QuranProgressEntry,
    QuranProgressRevision,
    QuranRangeType,
    Session,
    Sheikh,
    Student,
    StudentGoal,
    StudentGoalStatus,
    User,
)
from app.routers.auth import TenantContext, get_tenant_context
from app.schemas import (
    CreateStudentGoalRequest,
    QuranProgressBatchRequest,
    UpdateStudentGoalRequest,
)

router = APIRouter(tags=["quran-progress"])


def ensure_enabled(context: TenantContext) -> None:
    if not context.tahfiz.progress_tracking_enabled:
        raise HTTPException(
            status_code=409,
            detail={"code": "progress_tracking_disabled", "reason": "Qur'an progress tracking is disabled"},
        )


def serialize_entry(entry: QuranProgressEntry, session_date: date | None = None) -> dict:
    return {
        "id": entry.id,
        "session_id": entry.session_id,
        "student_id": entry.student_id,
        "sheikh_id": entry.sheikh_id,
        "recorded_by_id": entry.recorded_by_id,
        "category": entry.category.value,
        "range_type": entry.range_type.value,
        "from_surah": entry.from_surah,
        "from_ayah": entry.from_ayah,
        "to_surah": entry.to_surah,
        "to_ayah": entry.to_ayah,
        "from_page": entry.from_page,
        "to_page": entry.to_page,
        "quality_score": entry.quality_score,
        "mistakes": entry.mistakes,
        "notes": entry.notes,
        "next_assignment": entry.next_assignment,
        "created_at": entry.created_at.isoformat(),
        "updated_at": entry.updated_at.isoformat(),
        "session_date": session_date.isoformat() if session_date else None,
    }


def progress_snapshot(entry_or_item) -> dict:
    range_type = entry_or_item.range_type
    return {
        "range_type": range_type.value if hasattr(range_type, "value") else range_type,
        "from_surah": entry_or_item.from_surah,
        "from_ayah": entry_or_item.from_ayah,
        "to_surah": entry_or_item.to_surah,
        "to_ayah": entry_or_item.to_ayah,
        "from_page": entry_or_item.from_page,
        "to_page": entry_or_item.to_page,
        "quality_score": entry_or_item.quality_score,
        "mistakes": entry_or_item.mistakes,
        "notes": entry_or_item.notes,
        "next_assignment": entry_or_item.next_assignment,
    }


def serialize_goal(goal: StudentGoal) -> dict:
    return {
        "id": goal.id,
        "student_id": goal.student_id,
        "range_type": goal.range_type.value,
        "from_surah": goal.from_surah,
        "from_ayah": goal.from_ayah,
        "to_surah": goal.to_surah,
        "to_ayah": goal.to_ayah,
        "from_page": goal.from_page,
        "to_page": goal.to_page,
        "target_date": goal.target_date.isoformat() if goal.target_date else None,
        "notes": goal.notes,
        "status": goal.status.value,
        "completed_at": goal.completed_at.isoformat() if goal.completed_at else None,
        "created_at": goal.created_at.isoformat(),
        "updated_at": goal.updated_at.isoformat(),
    }


@router.get("/sessions/{session_id}/progress")
async def session_progress(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    if not context.tahfiz.progress_tracking_enabled:
        return {"enabled": False, "entries": [], "previous_entries": []}
    session = await db.scalar(select(Session).where(
        Session.id == session_id,
        Session.tahfiz_id == context.tahfiz_id,
    ))
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    entries = (await db.execute(
        select(QuranProgressEntry)
        .where(
            QuranProgressEntry.session_id == session_id,
            QuranProgressEntry.tahfiz_id == context.tahfiz_id,
        )
        .order_by(QuranProgressEntry.student_id, QuranProgressEntry.category)
    )).scalars().all()
    ranked_previous = (
        select(
            QuranProgressEntry.id.label("entry_id"),
            func.row_number().over(
                partition_by=(QuranProgressEntry.student_id, QuranProgressEntry.category),
                order_by=(Session.date.desc(), Session.id.desc(), QuranProgressEntry.updated_at.desc()),
            ).label("row_number"),
        )
        .join(Session, Session.id == QuranProgressEntry.session_id)
        .where(
            QuranProgressEntry.tahfiz_id == context.tahfiz_id,
            or_(
                Session.date < session.date,
                and_(Session.date == session.date, Session.id < session.id),
            ),
        )
        .subquery()
    )
    previous_rows = (await db.execute(
        select(QuranProgressEntry).where(
            QuranProgressEntry.id.in_(
                select(ranked_previous.c.entry_id).where(ranked_previous.c.row_number == 1)
            )
        )
    )).scalars().all()
    return {
        "enabled": True,
        "entries": [serialize_entry(entry) for entry in entries],
        "previous_entries": [serialize_entry(entry) for entry in previous_rows],
    }


@router.post("/sessions/{session_id}/progress/batch")
async def save_session_progress(
    session_id: int,
    body: QuranProgressBatchRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    ensure_enabled(context)
    session = await db.scalar(select(Session).where(
        Session.id == session_id,
        Session.tahfiz_id == context.tahfiz_id,
    ))
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.is_confirmed:
        raise HTTPException(status_code=409, detail="Confirmed sessions are locked")

    student_ids = {item.student_id for item in body.updates}
    valid_students = set((await db.execute(select(Student.id).where(
        Student.id.in_(student_ids),
        Student.tahfiz_id == context.tahfiz_id,
    ))).scalars().all())
    if valid_students != student_ids:
        raise HTTPException(status_code=404, detail="One or more students were not found")

    sheikh_ids = {item.sheikh_id for item in body.updates if item.sheikh_id is not None}
    if sheikh_ids:
        valid_sheikhs = set((await db.execute(select(Sheikh.id).where(
            Sheikh.id.in_(sheikh_ids),
            Sheikh.tahfiz_id == context.tahfiz_id,
        ))).scalars().all())
        if valid_sheikhs != sheikh_ids:
            raise HTTPException(status_code=404, detail="One or more sheikhs were not found")

    existing_entries = (await db.execute(select(QuranProgressEntry).where(
        QuranProgressEntry.session_id == session_id,
        QuranProgressEntry.student_id.in_(student_ids),
        QuranProgressEntry.tahfiz_id == context.tahfiz_id,
    ))).scalars().all()
    existing_by_key = {
        (entry.student_id, entry.category.value): entry
        for entry in existing_entries
    }
    changed_records: list[dict] = []
    for item in body.updates:
        try:
            category = ProgressCategory(item.category)
            range_type = QuranRangeType(item.range_type)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid progress category or range type")
        values = {
            "tahfiz_id": context.tahfiz_id,
            "session_id": session_id,
            "student_id": item.student_id,
            "sheikh_id": item.sheikh_id,
            "recorded_by_id": context.user.id,
            "category": category,
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
        existing = existing_by_key.get((item.student_id, category.value))
        before = progress_snapshot(existing) if existing else None
        after = progress_snapshot(item)
        if existing and before != after:
            db.add(QuranProgressRevision(
                tahfiz_id=context.tahfiz_id,
                progress_entry_id=existing.id,
                session_id=session_id,
                student_id=item.student_id,
                category=category,
                editor_user_id=context.user.id,
                before_json=json.dumps(before, ensure_ascii=False, sort_keys=True),
                after_json=json.dumps(after, ensure_ascii=False, sort_keys=True),
            ))
            changed_records.append({
                "entry_id": existing.id,
                "student_id": item.student_id,
                "category": category.value,
                "before": before,
                "after": after,
            })
        statement = sqlite_insert(QuranProgressEntry).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=["session_id", "student_id", "category"],
            set_={key: value for key, value in values.items() if key not in {"session_id", "student_id", "category"}},
        )
        await db.execute(statement)

    db.add(AuditLog(
        actor_user_id=context.user.id,
        tahfiz_id=context.tahfiz_id,
        action="quran_progress.batch_updated",
        details=json.dumps({
            "session_id": session_id,
            "records": len(body.updates),
            "changed": changed_records,
        }, ensure_ascii=False, sort_keys=True),
    ))
    await db.commit()
    return {"session_id": session_id, "saved": len(body.updates)}


@router.get("/students/{student_id}/progress")
async def student_progress(
    student_id: int,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    if not context.tahfiz.progress_tracking_enabled:
        return {"enabled": False, "entries": [], "goals": [], "average_quality": 0, "trend": [], "revisions": []}
    student = await db.scalar(select(Student.id).where(
        Student.id == student_id,
        Student.tahfiz_id == context.tahfiz_id,
    ))
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    entries = (await db.execute(
        select(QuranProgressEntry)
        .join(Session, Session.id == QuranProgressEntry.session_id)
        .where(
            QuranProgressEntry.student_id == student_id,
            QuranProgressEntry.tahfiz_id == context.tahfiz_id,
        )
        .order_by(Session.date.desc(), QuranProgressEntry.category)
    )).scalars().all()
    session_ids = {entry.session_id for entry in entries}
    session_dates = dict((await db.execute(
        select(Session.id, Session.date).where(
            Session.id.in_(session_ids),
            Session.tahfiz_id == context.tahfiz_id,
        )
    )).all()) if session_ids else {}
    goals = (await db.execute(
        select(StudentGoal)
        .where(StudentGoal.student_id == student_id, StudentGoal.tahfiz_id == context.tahfiz_id)
        .order_by(StudentGoal.created_at.desc())
    )).scalars().all()
    revisions = (await db.execute(
        select(QuranProgressRevision, User.username)
        .join(User, User.id == QuranProgressRevision.editor_user_id)
        .where(
            QuranProgressRevision.student_id == student_id,
            QuranProgressRevision.tahfiz_id == context.tahfiz_id,
        )
        .order_by(QuranProgressRevision.created_at.desc())
        .limit(50)
    )).all()
    average = round(sum(entry.quality_score for entry in entries) / len(entries), 1) if entries else 0
    return {
        "enabled": True,
        "entries": [serialize_entry(entry, session_dates.get(entry.session_id)) for entry in entries],
        "goals": [serialize_goal(goal) for goal in goals],
        "average_quality": average,
        "trend": [
            {
                "entry_id": entry.id,
                "session_date": session_dates[entry.session_id].isoformat(),
                "category": entry.category.value,
                "quality_score": entry.quality_score,
                "mistakes": entry.mistakes,
            }
            for entry in reversed(entries[:12])
            if entry.session_id in session_dates
        ],
        "revisions": [
            {
                "id": revision.id,
                "progress_entry_id": revision.progress_entry_id,
                "session_id": revision.session_id,
                "category": revision.category.value,
                "editor_user_id": revision.editor_user_id,
                "editor_username": username,
                "before": json.loads(revision.before_json),
                "after": json.loads(revision.after_json),
                "created_at": revision.created_at.isoformat(),
            }
            for revision, username in revisions
        ],
    }


@router.post("/students/{student_id}/goals")
async def create_student_goal(
    student_id: int,
    body: CreateStudentGoalRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    ensure_enabled(context)
    student = await db.scalar(select(Student.id).where(
        Student.id == student_id,
        Student.tahfiz_id == context.tahfiz_id,
    ))
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    goal = StudentGoal(
        tahfiz_id=context.tahfiz_id,
        student_id=student_id,
        range_type=QuranRangeType(body.range_type),
        from_surah=body.from_surah,
        from_ayah=body.from_ayah,
        to_surah=body.to_surah,
        to_ayah=body.to_ayah,
        from_page=body.from_page,
        to_page=body.to_page,
        target_date=body.target_date,
        notes=body.notes,
        created_by_id=context.user.id,
    )
    db.add(goal)
    await db.commit()
    await db.refresh(goal)
    return serialize_goal(goal)


@router.put("/students/{student_id}/goals/{goal_id}")
async def update_student_goal(
    student_id: int,
    goal_id: int,
    body: UpdateStudentGoalRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    ensure_enabled(context)
    goal = await db.scalar(select(StudentGoal).where(
        StudentGoal.id == goal_id,
        StudentGoal.student_id == student_id,
        StudentGoal.tahfiz_id == context.tahfiz_id,
    ))
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    if "target_date" in body.model_fields_set:
        goal.target_date = body.target_date
    if "notes" in body.model_fields_set:
        goal.notes = body.notes
    if body.status is not None:
        try:
            goal.status = StudentGoalStatus(body.status)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid goal status")
        goal.completed_at = datetime.utcnow() if goal.status == StudentGoalStatus.completed else None
    await db.commit()
    return serialize_goal(goal)


@router.get("/reports/quran-progress")
async def progress_report(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    if not context.tahfiz.progress_tracking_enabled:
        return {"enabled": False, "students": [], "category_totals": {}}
    student_query = (
        select(
            QuranProgressEntry.student_id,
            Student.name,
            func.count(QuranProgressEntry.id),
            func.avg(QuranProgressEntry.quality_score),
            func.sum(QuranProgressEntry.mistakes),
        )
        .join(Student, Student.id == QuranProgressEntry.student_id)
        .join(Session, Session.id == QuranProgressEntry.session_id)
        .where(QuranProgressEntry.tahfiz_id == context.tahfiz_id)
        .group_by(QuranProgressEntry.student_id, Student.name)
        .order_by(Student.name)
    )
    category_query = (
        select(QuranProgressEntry.category, func.count(QuranProgressEntry.id))
        .join(Session, Session.id == QuranProgressEntry.session_id)
        .where(QuranProgressEntry.tahfiz_id == context.tahfiz_id)
        .group_by(QuranProgressEntry.category)
    )
    if date_from:
        student_query = student_query.where(Session.date >= date_from)
        category_query = category_query.where(Session.date >= date_from)
    if date_to:
        student_query = student_query.where(Session.date <= date_to)
        category_query = category_query.where(Session.date <= date_to)
    latest_query = (
        select(QuranProgressEntry, Session.date)
        .join(Session, Session.id == QuranProgressEntry.session_id)
        .where(QuranProgressEntry.tahfiz_id == context.tahfiz_id)
        .order_by(Session.date.desc(), QuranProgressEntry.updated_at.desc())
    )
    if date_from:
        latest_query = latest_query.where(Session.date >= date_from)
    if date_to:
        latest_query = latest_query.where(Session.date <= date_to)
    rows = (await db.execute(student_query)).all()
    category_rows = (await db.execute(category_query)).all()
    latest_by_student: dict[int, dict] = {}
    for entry, session_date in (await db.execute(latest_query)).all():
        latest_by_student.setdefault(entry.student_id, serialize_entry(entry, session_date))
    return {
        "enabled": True,
        "students": [
            {
                "student_id": student_id,
                "student_name": name,
                "entries": count,
                "average_quality": round(float(average or 0), 1),
                "mistakes": mistakes or 0,
                "latest_entry": latest_by_student.get(student_id),
            }
            for student_id, name, count, average, mistakes in rows
        ],
        "category_totals": {category.value: count for category, count in category_rows},
    }

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    AuditLog,
    ProgressCategory,
    QuranProgressEntry,
    QuranRangeType,
    Session,
    Sheikh,
    Student,
    StudentGoal,
    StudentGoalStatus,
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
        return {"enabled": False, "entries": []}
    session = await db.scalar(select(Session.id).where(
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
    return {"enabled": True, "entries": [serialize_entry(entry) for entry in entries]}


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
        details=f"session={session_id}; records={len(body.updates)}",
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
        return {"enabled": False, "entries": [], "goals": [], "average_quality": 0, "trend": []}
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
    rows = (await db.execute(student_query)).all()
    category_rows = (await db.execute(category_query)).all()
    return {
        "enabled": True,
        "students": [
            {
                "student_id": student_id,
                "student_name": name,
                "entries": count,
                "average_quality": round(float(average or 0), 1),
                "mistakes": mistakes or 0,
            }
            for student_id, name, count, average, mistakes in rows
        ],
        "category_totals": {category.value: count for category, count in category_rows},
    }

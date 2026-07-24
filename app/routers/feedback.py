from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.database import get_db
from app.models import (
    AuditLog,
    FeedbackCategory,
    FeedbackReport,
    FeedbackStatus,
    Tahfiz,
    User,
)
from app.routers.auth import TenantContext, get_tenant_context, require_super_admin
from app.schemas import CreateFeedbackRequest, UpdateFeedbackStatusRequest

router = APIRouter(tags=["feedback"])


def serialize_feedback(
    report: FeedbackReport,
    reporter_username: str | None = None,
    tahfiz_name: str | None = None,
    reviewer_username: str | None = None,
) -> dict:
    return {
        "id": report.id,
        "reporter_user_id": report.reporter_user_id,
        "reporter_username": reporter_username or report.reporter_username,
        "tahfiz_id": report.tahfiz_id,
        "tahfiz_name": tahfiz_name,
        "category": report.category.value,
        "title": report.title,
        "description": report.description,
        "page_url": report.page_url,
        "status": report.status.value,
        "resolution_note": report.resolution_note,
        "reviewed_by_id": report.reviewed_by_id,
        "reviewer_username": reviewer_username,
        "reviewed_at": report.reviewed_at.isoformat() if report.reviewed_at else None,
        "created_at": report.created_at.isoformat(),
        "updated_at": report.updated_at.isoformat(),
    }


def feedback_rows_query():
    reporter = aliased(User)
    reviewer = aliased(User)
    statement = (
        select(FeedbackReport, reporter.username, Tahfiz.name, reviewer.username)
        .outerjoin(reporter, reporter.id == FeedbackReport.reporter_user_id)
        .outerjoin(Tahfiz, Tahfiz.id == FeedbackReport.tahfiz_id)
        .outerjoin(reviewer, reviewer.id == FeedbackReport.reviewed_by_id)
    )
    return statement, reporter


@router.post("/feedback", status_code=201)
async def create_feedback(
    body: CreateFeedbackRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    report = FeedbackReport(
        reporter_user_id=context.user.id,
        reporter_username=context.user.username,
        tahfiz_id=context.tahfiz.id,
        category=FeedbackCategory(body.category),
        title=body.title,
        description=body.description,
        page_url=body.page_url,
        status=FeedbackStatus.open,
    )
    db.add(report)
    await db.flush()
    db.add(AuditLog(
        actor_user_id=context.user.id,
        tahfiz_id=context.tahfiz.id,
        action="feedback.created",
        details=f"feedback={report.id}; category={report.category.value}",
    ))
    await db.commit()
    await db.refresh(report)
    return serialize_feedback(
        report,
        reporter_username=context.user.username,
        tahfiz_name=context.tahfiz.name,
    )


@router.get("/platform/feedback")
async def list_feedback(
    status: FeedbackStatus | None = Query(default=None),
    category: FeedbackCategory | None = Query(default=None),
    query: str | None = Query(default=None, max_length=100),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_super_admin),
):
    statement, reporter = feedback_rows_query()
    if status:
        statement = statement.where(FeedbackReport.status == status)
    if category:
        statement = statement.where(FeedbackReport.category == category)
    if query and query.strip():
        term = f"%{query.strip()}%"
        statement = statement.where(or_(
            FeedbackReport.title.ilike(term),
            FeedbackReport.description.ilike(term),
            FeedbackReport.reporter_username.ilike(term),
            reporter.username.ilike(term),
            Tahfiz.name.ilike(term),
        ))
    rows = (await db.execute(
        statement.order_by(FeedbackReport.created_at.desc()).limit(200)
    )).all()
    return [
        serialize_feedback(report, reporter_username, tahfiz_name, reviewer_username)
        for report, reporter_username, tahfiz_name, reviewer_username in rows
    ]


@router.patch("/platform/feedback/{feedback_id}")
async def update_feedback_status(
    feedback_id: int,
    body: UpdateFeedbackStatusRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin),
):
    report = await db.get(FeedbackReport, feedback_id)
    if not report:
        raise HTTPException(status_code=404, detail="Feedback report not found")
    previous_status = report.status
    report.status = FeedbackStatus(body.status)
    report.resolution_note = body.resolution_note
    report.reviewed_by_id = admin.id
    reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    report.reviewed_at = reviewed_at
    report.updated_at = reviewed_at
    db.add(AuditLog(
        actor_user_id=admin.id,
        tahfiz_id=report.tahfiz_id,
        action="feedback.status_changed",
        details=(
            f"feedback={report.id}; from={previous_status.value}; "
            f"to={report.status.value}; note={body.resolution_note or ''}"
        ),
    ))
    await db.commit()

    statement, _ = feedback_rows_query()
    row = (await db.execute(
        statement.where(FeedbackReport.id == report.id)
    )).one()
    return serialize_feedback(*row)

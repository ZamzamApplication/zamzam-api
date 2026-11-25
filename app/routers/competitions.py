"""Tenant competitions (e.g. Fajr attendance) with daily check-ins and a public leaderboard.

Admins configure competitions and rosters. Sheikhs and admins record daily entries, with
sheikhs limited to their own students whenever the Tahfiz restricts sheikh access. The
public endpoint exposes only display names and computed totals, never student records.
"""
import json
import secrets
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import (ACTIVE_STUDENT_STATUSES, AuditLog, Competition, CompetitionEntry, CompetitionParticipant,
                        Sheikh, Student, StudentCategoryMembership, Tahfiz, TahfizStatus, UserRole)
from app.routers.auth import TenantContext, get_tenant_context, require_tenant_admin, student_scope_clause
from app.time import utcnow

router = APIRouter(prefix="/competitions", tags=["competitions"])

MAX_PARTICIPANTS = 1000
MAX_DURATION_DAYS = 366
TROPHIES = {1: "gold", 2: "silver", 3: "bronze"}
STATUS_TRANSITIONS = {
    "draft": {"active"},
    "active": {"ended", "draft"},
    "ended": {"active"},
}


async def require_competition_staff(context: TenantContext = Depends(get_tenant_context)) -> TenantContext:
    if context.effective_role not in (UserRole.admin, UserRole.super_admin, UserRole.sheikh):
        raise HTTPException(status_code=403, detail="Competition staff access required")
    return context


def is_admin(context: TenantContext) -> bool:
    return context.effective_role in (UserRole.admin, UserRole.super_admin)


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CompetitionInput(StrictInput):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    start_date: date
    end_date: date
    points_per_check: int = Field(default=1, ge=1, le=100)
    completion_threshold: int | None = Field(default=None, ge=1, le=100_000)
    name_display: Literal["short", "full"] = "short"
    public_limit: int = Field(default=10, ge=0, le=MAX_PARTICIPANTS)

    @model_validator(mode="after")
    def valid_dates(self):
        if self.end_date < self.start_date:
            raise ValueError("End date must be on or after the start date")
        if (self.end_date - self.start_date).days >= MAX_DURATION_DAYS:
            raise ValueError("Competitions can last at most one year")
        return self


class CompetitionUpdateInput(CompetitionInput):
    expected_version: int = Field(ge=1)


class StatusInput(StrictInput):
    status: Literal["draft", "active", "ended"]
    expected_version: int = Field(ge=1)


class ParticipantsInput(StrictInput):
    student_ids: list[int] = Field(default_factory=list, max_length=MAX_PARTICIPANTS)
    sheikh_ids: list[int] = Field(default_factory=list, max_length=200)
    category_ids: list[int] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def something_selected(self):
        if not (self.student_ids or self.sheikh_ids or self.category_ids):
            raise ValueError("Select at least one student, sheikh or category")
        return self


class EntriesInput(StrictInput):
    date: date
    participant_ids: list[int] = Field(min_length=1, max_length=MAX_PARTICIPANTS)
    done: bool

    @model_validator(mode="after")
    def unique_participants(self):
        if len(set(self.participant_ids)) != len(self.participant_ids):
            raise ValueError("Duplicate participants")
        return self


class PublicLinkInput(StrictInput):
    enabled: bool
    regenerate: bool = False
    expected_version: int = Field(ge=1)


def audit(db, context, action, competition_id, **details):
    db.add(AuditLog(actor_user_id=context.user.id, tahfiz_id=context.tahfiz_id,
                    action=f"competition.{action}",
                    details=json.dumps({"competition_id": competition_id, **details}, ensure_ascii=False, default=str)))


def public_url(competition: Competition) -> str | None:
    if not competition.public_token:
        return None
    return f"{settings.PUBLIC_WEB_URL.rstrip('/')}/leaderboard/{competition.public_token}"


def competition_json(competition: Competition, include_link: bool) -> dict:
    data = {key: getattr(competition, key) for key in (
        "id", "title", "description", "start_date", "end_date", "status", "points_per_check",
        "completion_threshold", "public_enabled", "name_display", "public_limit", "version", "updated_at")}
    if include_link:
        data["public_url"] = public_url(competition)
    return data


def display_name(name: str, mode: str) -> str:
    """Public name. "short" keeps the first name plus the next name's initial (e.g. "أحمد م.")."""
    parts = name.split()
    if mode == "full" or not parts:
        return name.strip()
    return f"{parts[0]} {parts[1][0]}." if len(parts) > 1 else parts[0]


def best_streak(days: list[date]) -> int:
    best = current = 0
    previous = None
    for day in sorted(days):
        current = current + 1 if previous is not None and day - previous == timedelta(days=1) else 1
        best = max(best, current)
        previous = day
    return best


def compute_standings(competition: Competition, participants, entries) -> list[dict]:
    """Competition ranking: ties share a rank (1, 1, 3) and every tied leader gets the same trophy."""
    by_participant: dict[int, list[CompetitionEntry]] = {}
    for entry in entries:
        by_participant.setdefault(entry.participant_id, []).append(entry)
    rows = []
    for participant in participants:
        own = by_participant.get(participant.id, [])
        points = sum(entry.points for entry in own)
        rows.append({
            "participant_id": participant.id,
            "student_id": participant.student_id,
            "name": participant.name,
            "points": points,
            "days": len(own),
            "best_streak": best_streak([entry.entry_date for entry in own]),
        })
    rows.sort(key=lambda row: (-row["points"], -row["best_streak"], row["name"], row["participant_id"]))
    threshold = competition.completion_threshold
    for row in rows:
        row["rank"] = 1 + sum(1 for other in rows if other["points"] > row["points"])
        row["trophy"] = TROPHIES.get(row["rank"]) if row["points"] > 0 else None
        row["completed"] = bool(threshold) and row["points"] >= threshold
    return rows


async def get_competition(db, context, competition_id) -> Competition:
    competition = await db.scalar(select(Competition).where(
        Competition.id == competition_id, Competition.tahfiz_id == context.tahfiz_id)
        .execution_options(populate_existing=True))
    if competition is None:
        raise HTTPException(404, "المسابقة غير موجودة")
    return competition


async def lock_competition(db, context, competition_id, expected_version=None, allow_ended=False) -> Competition:
    clauses = [Competition.id == competition_id, Competition.tahfiz_id == context.tahfiz_id]
    if expected_version is not None:
        clauses.append(Competition.version == expected_version)
    if not allow_ended:
        clauses.append(Competition.status != "ended")
    result = await db.execute(update(Competition).where(*clauses)
                              .values(version=Competition.version + 1, updated_at=utcnow())
                              .execution_options(synchronize_session=False))
    if result.rowcount != 1:
        competition = await get_competition(db, context, competition_id)
        if competition.status == "ended" and not allow_ended:
            raise HTTPException(409, "انتهت المسابقة ونتائجها مجمّدة. أعد فتحها أولاً للتعديل.")
        raise HTTPException(409, "تغيّرت بيانات المسابقة. حدّث الصفحة ثم حاول مجدداً.")
    return await get_competition(db, context, competition_id)


async def load_roster(db, tahfiz_id, competition_id):
    participants = (await db.execute(select(CompetitionParticipant).where(
        CompetitionParticipant.competition_id == competition_id,
        CompetitionParticipant.tahfiz_id == tahfiz_id).order_by(CompetitionParticipant.name, CompetitionParticipant.id))).scalars().all()
    entries = (await db.execute(select(CompetitionEntry).where(
        CompetitionEntry.competition_id == competition_id,
        CompetitionEntry.tahfiz_id == tahfiz_id).order_by(CompetitionEntry.entry_date))).scalars().all()
    return participants, entries


async def markable_participant_ids(db, context, competition_id) -> set[int]:
    """Participants this user may record entries for (sheikhs: their own students only)."""
    query = select(CompetitionParticipant.id).where(
        CompetitionParticipant.competition_id == competition_id,
        CompetitionParticipant.tahfiz_id == context.tahfiz_id)
    if not is_admin(context):
        query = query.join(Student, Student.id == CompetitionParticipant.student_id).where(student_scope_clause(context))
    return set((await db.execute(query)).scalars().all())


@router.get("")
async def list_competitions(db: AsyncSession = Depends(get_db), context: TenantContext = Depends(require_competition_staff)):
    competitions = (await db.execute(select(Competition).where(Competition.tahfiz_id == context.tahfiz_id)
                                     .order_by(Competition.start_date.desc(), Competition.id.desc()))).scalars().all()
    counts = dict((await db.execute(select(CompetitionParticipant.competition_id, func.count()).where(
        CompetitionParticipant.tahfiz_id == context.tahfiz_id).group_by(CompetitionParticipant.competition_id))).all())
    if not is_admin(context):
        competitions = [item for item in competitions if item.status != "draft"]
    return [{**competition_json(item, is_admin(context)), "participant_count": counts.get(item.id, 0)} for item in competitions]


@router.get("/students")
async def competition_students(db: AsyncSession = Depends(get_db), context: TenantContext = Depends(require_tenant_admin)):
    """Roster candidates with the attributes used for bulk selection."""
    rows = (await db.execute(select(Student, Sheikh.name).outerjoin(Sheikh,
        (Sheikh.id == Student.sheikh_id) & (Sheikh.tahfiz_id == context.tahfiz_id)).where(
        Student.tahfiz_id == context.tahfiz_id, Student.status.in_(ACTIVE_STUDENT_STATUSES))
        .order_by(Student.name, Student.id))).all()
    memberships = (await db.execute(select(StudentCategoryMembership.student_id, StudentCategoryMembership.category_id)
                                    .where(StudentCategoryMembership.tahfiz_id == context.tahfiz_id))).all()
    categories: dict[int, list[int]] = {}
    for student_id, category_id in memberships:
        categories.setdefault(student_id, []).append(category_id)
    return [{"id": student.id, "name": student.name, "sheikh_id": student.sheikh_id, "sheikh_name": sheikh or "",
             "category_ids": categories.get(student.id, [])} for student, sheikh in rows]


@router.get("/public/{token}")
async def public_leaderboard(token: str, db: AsyncSession = Depends(get_db)):
    """Unauthenticated, read-only leaderboard. Exposes display names and totals only."""
    competition = await db.scalar(select(Competition).join(Tahfiz, Tahfiz.id == Competition.tahfiz_id).where(
        Competition.public_token == token, Competition.public_enabled.is_(True),
        Competition.status.in_(("active", "ended")), Tahfiz.status == TahfizStatus.active))
    if competition is None:
        raise HTTPException(404, "لوحة المتصدرين غير متاحة")
    tahfiz = await db.get(Tahfiz, competition.tahfiz_id)
    participants, entries = await load_roster(db, competition.tahfiz_id, competition.id)
    standings = [row for row in compute_standings(competition, participants, entries) if row["points"] > 0]
    limit = competition.public_limit
    shown = [row for row in standings if not limit or row["rank"] <= limit]
    return {
        "title": competition.title,
        "description": competition.description,
        "tahfiz_name": tahfiz.name,
        "start_date": competition.start_date,
        "end_date": competition.end_date,
        "status": competition.status,
        "points_per_check": competition.points_per_check,
        "completion_threshold": competition.completion_threshold,
        "participant_count": len(participants),
        "hidden_count": len(participants) - len(shown),
        "updated_at": max((entry.recorded_at for entry in entries), default=competition.updated_at),
        "leaderboard": [{key: row[key] for key in ("rank", "trophy", "points", "days", "best_streak", "completed")}
                        | {"name": display_name(row["name"], competition.name_display)} for row in shown],
    }


@router.get("/student/{student_id}")
async def student_competitions(student_id: int, on: date | None = None, db: AsyncSession = Depends(get_db),
                               context: TenantContext = Depends(require_competition_staff)):
    """Active competitions for one student, for the student page's quick check-in card."""
    student = await db.scalar(select(Student).where(Student.id == student_id, student_scope_clause(context)))
    if student is None:
        raise HTTPException(404, "الطالب غير موجود")
    day = on or utcnow().date()
    rows = (await db.execute(select(Competition, CompetitionParticipant).join(
        CompetitionParticipant, CompetitionParticipant.competition_id == Competition.id).where(
        Competition.tahfiz_id == context.tahfiz_id, CompetitionParticipant.tahfiz_id == context.tahfiz_id,
        CompetitionParticipant.student_id == student_id, Competition.status == "active")
        .order_by(Competition.start_date, Competition.id))).all()
    result = []
    for competition, participant in rows:
        participants, entries = await load_roster(db, context.tahfiz_id, competition.id)
        standing = next(row for row in compute_standings(competition, participants, entries)
                        if row["participant_id"] == participant.id)
        result.append({**competition_json(competition, False), "participant_id": participant.id,
                       "date": day, "done": any(e.participant_id == participant.id and e.entry_date == day for e in entries),
                       "can_record": competition.start_date <= day <= competition.end_date,
                       **{key: standing[key] for key in ("points", "days", "rank", "trophy", "completed")}})
    return result


@router.post("", status_code=201)
async def create_competition(body: CompetitionInput, db: AsyncSession = Depends(get_db),
                             context: TenantContext = Depends(require_tenant_admin)):
    competition = Competition(tahfiz_id=context.tahfiz_id, created_by_id=context.user.id, **body.model_dump())
    db.add(competition)
    await db.flush()
    audit(db, context, "created", competition.id, title=competition.title,
          start_date=competition.start_date, end_date=competition.end_date)
    await db.commit()
    return competition_json(competition, True)


@router.get("/{competition_id}")
async def competition_detail(competition_id: int, db: AsyncSession = Depends(get_db),
                             context: TenantContext = Depends(require_competition_staff)):
    competition = await get_competition(db, context, competition_id)
    if competition.status == "draft" and not is_admin(context):
        raise HTTPException(404, "المسابقة غير موجودة")
    participants, entries = await load_roster(db, context.tahfiz_id, competition_id)
    markable = await markable_participant_ids(db, context, competition_id)
    return {
        "competition": competition_json(competition, is_admin(context)),
        "participants": [{"id": p.id, "student_id": p.student_id, "name": p.name, "can_record": p.id in markable}
                         for p in participants],
        "entries": [{"participant_id": e.participant_id, "date": e.entry_date, "points": e.points} for e in entries],
        "standings": compute_standings(competition, participants, entries),
    }


@router.put("/{competition_id}")
async def update_competition(competition_id: int, body: CompetitionUpdateInput, db: AsyncSession = Depends(get_db),
                             context: TenantContext = Depends(require_tenant_admin)):
    competition = await lock_competition(db, context, competition_id, body.expected_version)
    outside = await db.scalar(select(func.count()).select_from(CompetitionEntry).where(
        CompetitionEntry.competition_id == competition_id, CompetitionEntry.tahfiz_id == context.tahfiz_id,
        or_(CompetitionEntry.entry_date < body.start_date, CompetitionEntry.entry_date > body.end_date)))
    if outside:
        raise HTTPException(409, "توجد تسجيلات خارج الفترة الجديدة. احذفها أولاً أو اختر فترة تشملها.")
    values = body.model_dump(exclude={"expected_version"})
    before = competition_json(competition, False)
    for key, value in values.items():
        setattr(competition, key, value)
    if values["points_per_check"] != before["points_per_check"]:
        # v1 scores every check equally, so re-price existing entries to keep totals consistent.
        await db.execute(update(CompetitionEntry).where(
            CompetitionEntry.competition_id == competition_id, CompetitionEntry.tahfiz_id == context.tahfiz_id)
            .values(points=values["points_per_check"]))
    audit(db, context, "updated", competition_id, before=before, changes=values)
    await db.commit()
    return competition_json(competition, True)


@router.patch("/{competition_id}/status")
async def change_status(competition_id: int, body: StatusInput, db: AsyncSession = Depends(get_db),
                        context: TenantContext = Depends(require_tenant_admin)):
    competition = await lock_competition(db, context, competition_id, body.expected_version, allow_ended=True)
    previous = competition.status
    if body.status not in STATUS_TRANSITIONS[previous]:
        raise HTTPException(409, "لا يمكن تغيير حالة المسابقة بهذا الشكل")
    if body.status == "draft" and await db.scalar(select(func.count()).select_from(CompetitionEntry).where(
            CompetitionEntry.competition_id == competition_id, CompetitionEntry.tahfiz_id == context.tahfiz_id)):
        raise HTTPException(409, "لا يمكن إرجاع مسابقة بها تسجيلات إلى المسودة")
    competition.status = body.status
    audit(db, context, "status_changed", competition_id, before=previous, after=body.status)
    await db.commit()
    return competition_json(competition, True)


@router.post("/{competition_id}/public-link")
async def set_public_link(competition_id: int, body: PublicLinkInput, db: AsyncSession = Depends(get_db),
                          context: TenantContext = Depends(require_tenant_admin)):
    competition = await lock_competition(db, context, competition_id, body.expected_version, allow_ended=True)
    if body.enabled and (body.regenerate or not competition.public_token):
        competition.public_token = secrets.token_urlsafe(32)
    competition.public_enabled = body.enabled
    audit(db, context, "public_link_changed", competition_id, enabled=body.enabled, regenerated=body.regenerate)
    await db.commit()
    return competition_json(competition, True)


@router.post("/{competition_id}/participants", status_code=201)
async def add_participants(competition_id: int, body: ParticipantsInput, db: AsyncSession = Depends(get_db),
                           context: TenantContext = Depends(require_tenant_admin)):
    await lock_competition(db, context, competition_id)
    base = [Student.tahfiz_id == context.tahfiz_id, Student.status.in_(ACTIVE_STUDENT_STATUSES)]
    selected: dict[int, Student] = {}
    if body.student_ids:
        students = (await db.execute(select(Student).where(*base, Student.id.in_(body.student_ids)))).scalars().all()
        if {student.id for student in students} != set(body.student_ids):
            raise HTTPException(404, "أحد الطلاب غير موجود أو غير متاح")
        selected.update((student.id, student) for student in students)
    if body.sheikh_ids:
        found = set((await db.execute(select(Sheikh.id).where(
            Sheikh.id.in_(body.sheikh_ids), Sheikh.tahfiz_id == context.tahfiz_id))).scalars().all())
        if found != set(body.sheikh_ids):
            raise HTTPException(404, "أحد المشايخ غير موجود")
        students = (await db.execute(select(Student).where(*base, Student.sheikh_id.in_(body.sheikh_ids)))).scalars().all()
        selected.update((student.id, student) for student in students)
    if body.category_ids:
        students = (await db.execute(select(Student).join(StudentCategoryMembership,
            StudentCategoryMembership.student_id == Student.id).where(
            *base, StudentCategoryMembership.tahfiz_id == context.tahfiz_id,
            StudentCategoryMembership.category_id.in_(body.category_ids)))).scalars().all()
        selected.update((student.id, student) for student in students)
    existing = set((await db.execute(select(CompetitionParticipant.student_id).where(
        CompetitionParticipant.competition_id == competition_id,
        CompetitionParticipant.tahfiz_id == context.tahfiz_id))).scalars().all())
    new = [student for student_id, student in selected.items() if student_id not in existing]
    if len(existing) + len(new) > MAX_PARTICIPANTS:
        raise HTTPException(409, "الحد الأقصى للمشاركين ١٠٠٠")
    for student in sorted(new, key=lambda item: item.id):
        db.add(CompetitionParticipant(tahfiz_id=context.tahfiz_id, competition_id=competition_id,
                                      student_id=student.id, name=student.name))
    audit(db, context, "participants_added", competition_id, student_ids=sorted(item.id for item in new))
    await db.commit()
    return {"added": len(new), "already_participating": len(selected) - len(new)}


@router.delete("/{competition_id}/participants/{participant_id}")
async def remove_participant(competition_id: int, participant_id: int, db: AsyncSession = Depends(get_db),
                             context: TenantContext = Depends(require_tenant_admin)):
    await lock_competition(db, context, competition_id)
    participant = await db.scalar(select(CompetitionParticipant).where(
        CompetitionParticipant.id == participant_id, CompetitionParticipant.competition_id == competition_id,
        CompetitionParticipant.tahfiz_id == context.tahfiz_id))
    if participant is None:
        raise HTTPException(404, "المشارك غير موجود")
    removed = await db.execute(delete(CompetitionEntry).where(
        CompetitionEntry.participant_id == participant_id, CompetitionEntry.tahfiz_id == context.tahfiz_id))
    await db.delete(participant)
    audit(db, context, "participant_removed", competition_id, participant_id=participant_id,
          student_id=participant.student_id, name=participant.name, entries_removed=removed.rowcount)
    await db.commit()
    return {"ok": True}


@router.post("/{competition_id}/entries")
async def record_entries(competition_id: int, body: EntriesInput, db: AsyncSession = Depends(get_db),
                         context: TenantContext = Depends(require_competition_staff)):
    """Bulk mark (done=true) or unmark (done=false) a day for many participants. Idempotent."""
    competition = await get_competition(db, context, competition_id)
    if competition.status != "active":
        raise HTTPException(409, "يمكن التسجيل في المسابقات الجارية فقط")
    if not competition.start_date <= body.date <= competition.end_date:
        raise HTTPException(422, "التاريخ خارج فترة المسابقة")
    # One day of slack covers tenants ahead of UTC (e.g. Fajr in Egypt happens before UTC midnight rolls).
    if body.date > utcnow().date() + timedelta(days=1):
        raise HTTPException(422, "لا يمكن التسجيل لتاريخ مستقبلي")
    requested = set(body.participant_ids)
    if not requested <= await markable_participant_ids(db, context, competition_id):
        raise HTTPException(404, "أحد المشاركين غير موجود أو ليس ضمن طلابك")
    existing = set((await db.execute(select(CompetitionEntry.participant_id).where(
        CompetitionEntry.competition_id == competition_id, CompetitionEntry.tahfiz_id == context.tahfiz_id,
        CompetitionEntry.entry_date == body.date, CompetitionEntry.participant_id.in_(requested)))).scalars().all())
    if body.done:
        changed = sorted(requested - existing)
        for participant_id in changed:
            db.add(CompetitionEntry(tahfiz_id=context.tahfiz_id, competition_id=competition_id,
                                    participant_id=participant_id, entry_date=body.date,
                                    points=competition.points_per_check, recorded_by_id=context.user.id))
    else:
        changed = sorted(existing)
        if changed:
            await db.execute(delete(CompetitionEntry).where(
                CompetitionEntry.competition_id == competition_id, CompetitionEntry.tahfiz_id == context.tahfiz_id,
                CompetitionEntry.entry_date == body.date, CompetitionEntry.participant_id.in_(changed)))
    if changed:
        audit(db, context, "entries_recorded" if body.done else "entries_removed", competition_id,
              date=body.date, participant_ids=changed)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "سجّل مستخدم آخر نفس اليوم في نفس اللحظة. حدّث الصفحة ثم حاول مجدداً.")
    return {"changed": len(changed), "unchanged": len(requested) - len(changed)}

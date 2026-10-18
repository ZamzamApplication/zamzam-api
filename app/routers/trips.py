"""Tenant-admin trip preparation and independent, auditable headcounts."""
import json
import re
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import ACTIVE_STUDENT_STATUSES, AuditLog, Sheikh, Student, Trip, TripCheck, TripGroup, TripParticipant, TripRound
from app.routers.auth import TenantContext, require_tenant_admin
from app.time import utcnow

router = APIRouter(prefix="/trips", tags=["trips"])


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TripInput(StrictInput):
    name: str = Field(min_length=1, max_length=120)
    date: date
    destination: str = Field(default="", max_length=200)
    meeting_point: str = Field(default="", max_length=200)
    departure_time: str = ""
    fee_minor: int = Field(default=0, ge=0, le=100_000_000)
    currency: Literal["EGP", "SAR", "USD"] = "EGP"
    notes: str = Field(default="", max_length=4000)

    @field_validator("departure_time")
    @classmethod
    def valid_time(cls, value):
        if value and not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError("Invalid departure time")
        return value


class GroupInput(StrictInput):
    name: str = Field(min_length=1, max_length=100)


class GuestInput(StrictInput):
    is_adult: bool = False
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(default="", max_length=30)


class RosterInput(StrictInput):
    group_id: int | None = None
    guardian_id: int | None = None
    student_ids: list[int] = Field(default_factory=list, max_length=1000)
    guests: list[GuestInput] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def valid_roster(self):
        if not self.student_ids and not self.guests:
            raise ValueError("Select at least one participant")
        if len(self.student_ids) != len(set(self.student_ids)):
            raise ValueError("Duplicate students")
        return self


class ParticipantInput(StrictInput):
    group_id: int | None = None
    guardian_id: int | None = None
    is_adult: bool | None = None
    expected_version: int = Field(ge=1)
    paid_minor: int | None = Field(default=None, ge=0, le=100_000_000)
    fee_minor: int | None = Field(default=None, ge=0, le=100_000_000)
    active: bool | None = None
    payment_exempt: bool | None = None
    exemption_reason: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def non_null_fields(self):
        if any(getattr(self, key) is None for key in self.model_fields_set - {"expected_version", "group_id", "guardian_id"}):
            raise ValueError("Fields cannot be null")
        return self


class RoundInput(StrictInput):
    title: str = Field(min_length=1, max_length=120)
    expected_version: int = Field(ge=1)


class CheckInput(StrictInput):
    status: Literal["pending", "present", "absent"]
    expected_version: int = Field(ge=1)


class TripStatusInput(StrictInput):
    status: Literal["planned", "completed"]
    expected_version: int = Field(ge=1)


def audit(db, context, action, trip_id, **details):
    db.add(AuditLog(actor_user_id=context.user.id, tahfiz_id=context.tahfiz_id,
                    action=f"trip.{action}", details=json.dumps({"trip_id": trip_id, **details}, ensure_ascii=False, default=str)))


async def get_trip(db, context, trip_id):
    trip = await db.scalar(select(Trip).where(Trip.id == trip_id, Trip.tahfiz_id == context.tahfiz_id)
                           .execution_options(populate_existing=True))
    if trip is None:
        raise HTTPException(404, "الرحلة غير موجودة")
    return trip


async def lock_trip(db, context, trip_id, expected_version=None, allow_completed=False):
    clauses = [Trip.id == trip_id, Trip.tahfiz_id == context.tahfiz_id]
    if expected_version is not None:
        clauses.append(Trip.version == expected_version)
    if not allow_completed:
        clauses.append(Trip.status != "completed")
    result = await db.execute(update(Trip).where(*clauses).values(version=Trip.version + 1, updated_at=utcnow())
                              .execution_options(synchronize_session=False))
    if result.rowcount != 1:
        await get_trip(db, context, trip_id)
        raise HTTPException(409, "تغيّرت بيانات الرحلة أو انتهت. حدّث الصفحة ثم حاول مجدداً.")
    return await get_trip(db, context, trip_id)


def trip_json(trip):
    return {key: getattr(trip, key) for key in ("id", "name", "date", "destination", "meeting_point", "departure_time",
                                               "fee_minor", "currency", "notes", "status", "version", "updated_at")}


def participant_json(participant):
    return {key: getattr(participant, key) for key in ("id", "student_id", "group_id", "guardian_id", "is_adult", "kind", "name", "phone", "student_code", "sheikh_name",
                                                      "fee_minor", "paid_minor", "payment_exempt", "exemption_reason", "active", "notes", "version")}


async def current_round(db, context, trip_id):
    return await db.scalar(select(TripRound).where(TripRound.trip_id == trip_id,
        TripRound.tahfiz_id == context.tahfiz_id, TripRound.closed_at.is_(None)).order_by(TripRound.id.desc())
        .execution_options(populate_existing=True))


async def validate_group(db, context, trip_id, group_id):
    if group_id is not None and not await db.scalar(select(TripGroup.id).where(
        TripGroup.id == group_id, TripGroup.trip_id == trip_id, TripGroup.tahfiz_id == context.tahfiz_id)):
        raise HTTPException(404, "المجموعة غير موجودة في هذه الرحلة")


async def validate_guardian(db, context, trip_id, guardian_id, person_id=None):
    if guardian_id is None:
        return
    guardian = await db.scalar(select(TripParticipant).where(TripParticipant.id == guardian_id,
        TripParticipant.trip_id == trip_id, TripParticipant.tahfiz_id == context.tahfiz_id))
    if not guardian or not guardian.active or not guardian.is_adult or guardian.guardian_id or guardian.id == person_id:
        raise HTTPException(422, "اختر مرافقاً بالغاً مستقلاً ومشاركاً في نفس الرحلة")


@router.get("")
async def list_trips(db: AsyncSession = Depends(get_db), context: TenantContext = Depends(require_tenant_admin)):
    trips = (await db.execute(select(Trip).where(Trip.tahfiz_id == context.tahfiz_id).order_by(Trip.date.desc(), Trip.id.desc()))).scalars().all()
    counts = dict((await db.execute(select(TripParticipant.trip_id, func.count()).where(
        TripParticipant.tahfiz_id == context.tahfiz_id, TripParticipant.active.is_(True)).group_by(TripParticipant.trip_id))).all())
    return [{**trip_json(trip), "participant_count": counts.get(trip.id, 0)} for trip in trips]


@router.get("/students")
async def trip_students(db: AsyncSession = Depends(get_db), context: TenantContext = Depends(require_tenant_admin)):
    rows = (await db.execute(select(Student, Sheikh.name).outerjoin(Sheikh,
        (Sheikh.id == Student.sheikh_id) & (Sheikh.tahfiz_id == context.tahfiz_id)).where(
        Student.tahfiz_id == context.tahfiz_id, Student.status.in_(ACTIVE_STUDENT_STATUSES)).order_by(Student.name, Student.id))).all()
    return [{"id": student.id, "name": student.name, "phone": student.phone or "", "student_code": student.student_id or "",
             "sheikh_name": sheikh or ""} for student, sheikh in rows]


@router.post("", status_code=201)
async def create_trip(body: TripInput, db: AsyncSession = Depends(get_db), context: TenantContext = Depends(require_tenant_admin)):
    trip = Trip(tahfiz_id=context.tahfiz_id, **body.model_dump())
    db.add(trip)
    await db.flush()
    audit(db, context, "created", trip.id, name=trip.name, date=trip.date)
    await db.commit()
    return trip_json(trip)


@router.get("/{trip_id}")
async def trip_detail(trip_id: int, round_id: int | None = Query(default=None), db: AsyncSession = Depends(get_db),
                      context: TenantContext = Depends(require_tenant_admin)):
    trip = await get_trip(db, context, trip_id)
    groups = (await db.execute(select(TripGroup).where(TripGroup.trip_id == trip_id, TripGroup.tahfiz_id == context.tahfiz_id).order_by(TripGroup.id))).scalars().all()
    participants = (await db.execute(select(TripParticipant).where(TripParticipant.trip_id == trip_id,
        TripParticipant.tahfiz_id == context.tahfiz_id).order_by(TripParticipant.name, TripParticipant.id))).scalars().all()
    rounds = (await db.execute(select(TripRound).where(TripRound.trip_id == trip_id,
        TripRound.tahfiz_id == context.tahfiz_id).order_by(TripRound.id.desc()))).scalars().all()
    selected = next((item for item in rounds if item.id == round_id), None) if round_id else (rounds[0] if rounds else None)
    if round_id is not None and selected is None:
        raise HTTPException(404, "جولة التحقق غير موجودة")
    checks = (await db.execute(select(TripCheck).where(TripCheck.round_id == selected.id,
        TripCheck.tahfiz_id == context.tahfiz_id))).scalars().all() if selected else []
    return {"trip": trip_json(trip), "groups": [{"id": group.id, "name": group.name} for group in groups], "participants": [participant_json(item) for item in participants],
            "rounds": [{"id": item.id, "title": item.title, "created_at": item.created_at, "closed_at": item.closed_at} for item in rounds],
            "selected_round_id": selected.id if selected else None,
            "checks": [{key: getattr(item, key) for key in ("participant_id", "group_id", "status", "checked_at", "version")} for item in checks]}


@router.post("/{trip_id}/participants", status_code=201)
async def add_participants(trip_id: int, body: RosterInput, db: AsyncSession = Depends(get_db), context: TenantContext = Depends(require_tenant_admin)):
    trip = await lock_trip(db, context, trip_id)
    await validate_group(db, context, trip_id, body.group_id)
    await validate_guardian(db, context, trip_id, body.guardian_id)
    students = (await db.execute(select(Student, Sheikh.name).outerjoin(Sheikh,
        (Sheikh.id == Student.sheikh_id) & (Sheikh.tahfiz_id == context.tahfiz_id)).where(
        Student.tahfiz_id == context.tahfiz_id, Student.id.in_(body.student_ids), Student.status.in_(ACTIVE_STUDENT_STATUSES)))).all() if body.student_ids else []
    if {student.id for student, _ in students} != set(body.student_ids):
        raise HTTPException(404, "أحد الطلاب غير موجود أو غير متاح")
    existing = (await db.execute(select(TripParticipant).where(TripParticipant.trip_id == trip_id,
        TripParticipant.tahfiz_id == context.tahfiz_id))).scalars().all()
    if any(item.student_id in body.student_ids for item in existing):
        raise HTTPException(409, "أحد الطلاب مسجل بالفعل. يمكنك إعادة تفعيل مشاركته من القائمة.")
    if len(existing) + len(students) + len(body.guests) > 1000:
        raise HTTPException(409, "الحد الأقصى للمشاركين ١٠٠٠")
    people = [TripParticipant(tahfiz_id=context.tahfiz_id, trip_id=trip_id, student_id=student.id, kind="student",
                name=student.name, phone=student.phone or "", student_code=student.student_id or "", sheikh_name=sheikh or "", fee_minor=trip.fee_minor, group_id=body.group_id, guardian_id=body.guardian_id)
              for student, sheikh in students]
    people.extend(TripParticipant(tahfiz_id=context.tahfiz_id, trip_id=trip_id, kind="guest", name=guest.name,
                                 phone=guest.phone, fee_minor=trip.fee_minor, group_id=body.group_id, is_adult=guest.is_adult,
                                 guardian_id=None if guest.is_adult else body.guardian_id) for guest in body.guests)
    headcount = await current_round(db, context, trip_id)
    for person in people:
        db.add(person)
        await db.flush()
        if headcount:
            db.add(TripCheck(tahfiz_id=context.tahfiz_id, trip_id=trip_id, round_id=headcount.id, participant_id=person.id, group_id=person.group_id))
    audit(db, context, "participants_added", trip_id, participant_ids=[person.id for person in people])
    await db.commit()
    return {"added": len(people)}


@router.patch("/{trip_id}/participants/{participant_id}")
async def update_participant(trip_id: int, participant_id: int, body: ParticipantInput, db: AsyncSession = Depends(get_db),
                             context: TenantContext = Depends(require_tenant_admin)):
    await lock_trip(db, context, trip_id)
    person = await db.scalar(select(TripParticipant).where(TripParticipant.id == participant_id,
        TripParticipant.trip_id == trip_id, TripParticipant.tahfiz_id == context.tahfiz_id).execution_options(populate_existing=True))
    if person is None:
        raise HTTPException(404, "المشارك غير موجود")
    if person.version != body.expected_version:
        raise HTTPException(409, "تم تعديل المشارك من جهاز آخر. حدّث البيانات ثم حاول مجدداً.")
    values = body.model_dump(exclude_unset=True, exclude={"expected_version"})
    if values.get("paid_minor", person.paid_minor) > values.get("fee_minor", person.fee_minor):
        raise HTTPException(422, "المبلغ المدفوع لا يمكن أن يزيد عن رسوم المشاركة")
    if "group_id" in values:
        await validate_group(db, context, trip_id, values["group_id"])
    if "guardian_id" in values:
        await validate_guardian(db, context, trip_id, values["guardian_id"], person.id)
    if values.get("is_adult", person.is_adult) and values.get("guardian_id", person.guardian_id) is not None:
        raise HTTPException(422, "المرافق البالغ يجب أن يكون مستقلاً")
    if not values.get("is_adult", person.is_adult) or not values.get("active", person.active):
        dependents = await db.scalar(select(func.count()).select_from(TripParticipant).where(
            TripParticipant.guardian_id == person.id, TripParticipant.trip_id == trip_id,
            TripParticipant.tahfiz_id == context.tahfiz_id, TripParticipant.active.is_(True)))
        if dependents:
            raise HTTPException(409, "انقل الطلاب المرتبطين بهذا المرافق إلى مرافق آخر أولاً")
    before = participant_json(person)
    await db.execute(update(TripParticipant).where(TripParticipant.id == person.id,
        TripParticipant.tahfiz_id == context.tahfiz_id, TripParticipant.version == body.expected_version)
        .values(**values, version=TripParticipant.version + 1).execution_options(synchronize_session=False))
    headcount = await current_round(db, context, trip_id)
    if headcount and "group_id" in values:
        await db.execute(update(TripCheck).where(TripCheck.round_id == headcount.id,
            TripCheck.participant_id == person.id, TripCheck.tahfiz_id == context.tahfiz_id).values(group_id=values["group_id"]))
    if headcount and "active" in values and values["active"] != person.active:
        if values["active"]:
            db.add(TripCheck(tahfiz_id=context.tahfiz_id, trip_id=trip_id, round_id=headcount.id, participant_id=person.id, group_id=values.get("group_id", person.group_id)))
        else:
            check = await db.scalar(select(TripCheck).where(TripCheck.round_id == headcount.id,
                TripCheck.participant_id == person.id, TripCheck.tahfiz_id == context.tahfiz_id))
            audit(db, context, "headcount_removed", trip_id, round_id=headcount.id, participant_id=person.id,
                  previous_status=check.status if check else None)
            await db.execute(delete(TripCheck).where(TripCheck.round_id == headcount.id,
                TripCheck.participant_id == person.id, TripCheck.tahfiz_id == context.tahfiz_id))
    audit(db, context, "participant_updated", trip_id, participant_id=person.id, before=before, changes=values)
    await db.commit()
    return {"ok": True}


@router.post("/{trip_id}/rounds", status_code=201)
async def start_round(trip_id: int, body: RoundInput, db: AsyncSession = Depends(get_db), context: TenantContext = Depends(require_tenant_admin)):
    await lock_trip(db, context, trip_id, body.expected_version)
    people = (await db.execute(select(TripParticipant).where(TripParticipant.trip_id == trip_id,
        TripParticipant.tahfiz_id == context.tahfiz_id, TripParticipant.active.is_(True)))).scalars().all()
    if not people:
        raise HTTPException(409, "أضف مشاركين قبل بدء التحقق")
    count = await db.scalar(select(func.count()).select_from(TripRound).where(TripRound.trip_id == trip_id, TripRound.tahfiz_id == context.tahfiz_id))
    if count >= 100:
        raise HTTPException(409, "وصلت للحد الأقصى لجولات التحقق")
    now = utcnow()
    await db.execute(update(TripRound).where(TripRound.trip_id == trip_id, TripRound.tahfiz_id == context.tahfiz_id,
        TripRound.closed_at.is_(None)).values(closed_at=now))
    headcount = TripRound(tahfiz_id=context.tahfiz_id, trip_id=trip_id, title=body.title, created_by_id=context.user.id)
    db.add(headcount)
    await db.flush()
    for person in people:
        db.add(TripCheck(tahfiz_id=context.tahfiz_id, trip_id=trip_id, round_id=headcount.id, participant_id=person.id, group_id=person.group_id))
    audit(db, context, "round_started", trip_id, round_id=headcount.id, title=body.title, expected=len(people))
    await db.commit()
    return {"id": headcount.id}


@router.patch("/{trip_id}/rounds/{round_id}/checks/{participant_id}")
async def mark_check(trip_id: int, round_id: int, participant_id: int, body: CheckInput,
                     db: AsyncSession = Depends(get_db), context: TenantContext = Depends(require_tenant_admin)):
    await lock_trip(db, context, trip_id)
    headcount = await current_round(db, context, trip_id)
    if headcount is None or headcount.id != round_id:
        raise HTTPException(409, "هذه جولة سابقة للعرض فقط. افتح جولة التحقق الحالية.")
    check = await db.scalar(select(TripCheck).where(TripCheck.round_id == round_id, TripCheck.participant_id == participant_id,
        TripCheck.trip_id == trip_id, TripCheck.tahfiz_id == context.tahfiz_id).execution_options(populate_existing=True))
    if check is None:
        raise HTTPException(404, "المشارك غير موجود في جولة التحقق")
    if check.version != body.expected_version:
        raise HTTPException(409, "تم تسجيل هذا المشارك من جهاز آخر. حدّث البيانات ثم حاول مجدداً.")
    before = check.status
    await db.execute(update(TripCheck).where(TripCheck.id == check.id, TripCheck.tahfiz_id == context.tahfiz_id,
        TripCheck.version == body.expected_version).values(status=body.status,
        checked_at=utcnow() if body.status != "pending" else None, checked_by_id=context.user.id,
        version=TripCheck.version + 1).execution_options(synchronize_session=False))
    audit(db, context, "checked", trip_id, round_id=round_id, participant_id=participant_id, before=before, after=body.status)
    await db.commit()
    return {"ok": True}


@router.patch("/{trip_id}/status")
async def trip_status(trip_id: int, body: TripStatusInput, db: AsyncSession = Depends(get_db), context: TenantContext = Depends(require_tenant_admin)):
    trip = await lock_trip(db, context, trip_id, body.expected_version, allow_completed=True)
    trip.status = body.status
    if body.status == "completed":
        await db.execute(update(TripRound).where(TripRound.trip_id == trip_id, TripRound.tahfiz_id == context.tahfiz_id,
            TripRound.closed_at.is_(None)).values(closed_at=utcnow()))
    audit(db, context, "status_changed", trip_id, status=body.status)
    await db.commit()
    return {"ok": True}


@router.post("/{trip_id}/groups", status_code=201)
async def add_group(trip_id: int, body: GroupInput, db: AsyncSession = Depends(get_db), context: TenantContext = Depends(require_tenant_admin)):
    await lock_trip(db, context, trip_id)
    existing = await db.scalar(select(TripGroup.id).where(TripGroup.trip_id == trip_id,
        TripGroup.tahfiz_id == context.tahfiz_id, TripGroup.name == body.name))
    if existing:
        raise HTTPException(409, "توجد مجموعة بهذا الاسم بالفعل")
    count = await db.scalar(select(func.count()).select_from(TripGroup).where(TripGroup.trip_id == trip_id, TripGroup.tahfiz_id == context.tahfiz_id))
    if count >= 100:
        raise HTTPException(409, "الحد الأقصى للمجموعات ١٠٠")
    group = TripGroup(tahfiz_id=context.tahfiz_id, trip_id=trip_id, name=body.name)
    db.add(group)
    await db.flush()
    audit(db, context, "group_added", trip_id, group_id=group.id, name=group.name)
    await db.commit()
    return {"id": group.id, "name": group.name}


class GroupAssignmentInput(StrictInput):
    group_id: int | None
    participants: list[dict[str, int]] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def valid_participants(self):
        if any(set(item) != {"id", "expected_version"} or item["expected_version"] < 1 for item in self.participants):
            raise ValueError("Invalid participants")
        if len({item["id"] for item in self.participants}) != len(self.participants):
            raise ValueError("Duplicate participants")
        return self


@router.post("/{trip_id}/assign-group")
async def assign_group(trip_id: int, body: GroupAssignmentInput, db: AsyncSession = Depends(get_db), context: TenantContext = Depends(require_tenant_admin)):
    await lock_trip(db, context, trip_id)
    await validate_group(db, context, trip_id, body.group_id)
    versions = {item["id"]: item["expected_version"] for item in body.participants}
    people = (await db.execute(select(TripParticipant).where(TripParticipant.id.in_(versions),
        TripParticipant.trip_id == trip_id, TripParticipant.tahfiz_id == context.tahfiz_id,
        TripParticipant.active.is_(True)).execution_options(populate_existing=True))).scalars().all()
    if {person.id for person in people} != set(versions):
        raise HTTPException(404, "أحد المشاركين غير موجود في هذه الرحلة")
    if any(person.version != versions[person.id] for person in people):
        raise HTTPException(409, "تغيّرت بيانات أحد المشاركين. حدّث البيانات قبل توزيع المجموعات.")
    before = {person.id: person.group_id for person in people}
    await db.execute(update(TripParticipant).where(TripParticipant.id.in_(versions), TripParticipant.tahfiz_id == context.tahfiz_id,
        TripParticipant.trip_id == trip_id).values(group_id=body.group_id, version=TripParticipant.version + 1)
        .execution_options(synchronize_session=False))
    headcount = await current_round(db, context, trip_id)
    if headcount:
        await db.execute(update(TripCheck).where(TripCheck.round_id == headcount.id, TripCheck.tahfiz_id == context.tahfiz_id,
            TripCheck.participant_id.in_(versions)).values(group_id=body.group_id))
    audit(db, context, "group_assigned", trip_id, group_id=body.group_id, before=before)
    await db.commit()
    return {"ok": True}

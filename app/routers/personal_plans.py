import json
import secrets
from datetime import date
from typing import Annotated, Literal
from uuid import uuid4
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import PersonalPlan, User
from app.routers.auth import get_current_user_depends
from app.time import utcnow

router = APIRouter(tags=["personal plans"])
ShareMode = Literal["private", "readonly", "read_mark"]


class PlanConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    planOwnerType: Literal["student", "female-student", "teacher", "female-teacher"]
    studentName: str = Field(max_length=120)
    startDate: date
    endDate: date
    weekdays: list[Annotated[int, Field(ge=0, le=6)]] = Field(min_length=1, max_length=7)
    includeCompletionCheckboxes: bool
    tracks: list[dict] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_range_and_size(self):
        if not 0 <= (self.endDate - self.startDate).days < 730:
            raise ValueError("Invalid plan date range")
        if len(json.dumps(self.tracks, ensure_ascii=False).encode()) > 1_000_000:
            raise ValueError("Plan content is too large")
        for track in self.tracks:
            if (track.get("kind") not in ("quran", "quantity", "playlist")
                or type(track.get("enabled")) is not bool
                or type(track.get("dailyAmount")) is not int
                or not 1 <= track["dailyAmount"] <= 1000
                or not isinstance(track.get("id"), str) or not 1 <= len(track["id"]) <= 100
                or not isinstance(track.get("name"), str) or not 1 <= len(track["name"]) <= 120):
                raise ValueError("Invalid plan track")

        def validate_links(value):
            if isinstance(value, list):
                for item in value:
                    validate_links(item)
            elif isinstance(value, dict):
                for key, item in value.items():
                    if key == "url" and item:
                        if not isinstance(item, str):
                            raise ValueError("Invalid media link")
                        url = urlparse(item)
                        if url.scheme not in {"https", "http"} or not url.hostname or url.username or url.password:
                            raise ValueError("Invalid media link")
                    validate_links(item)
        validate_links(self.tracks)
        return self


class SavePlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    configuration: PlanConfiguration
    study_dates: list[date] = Field(max_length=730)
    completed_dates: list[date] = Field(default_factory=list, max_length=730)
    expected_version: int | None = Field(default=None, ge=1)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value):
        if not value.strip():
            raise ValueError("Plan name is required")
        return value.strip()

    @model_validator(mode="after")
    def validate_dates(self):
        if len(set(self.study_dates)) != len(self.study_dates):
            raise ValueError("Duplicate study dates")
        if any(not self.configuration.startDate <= day <= self.configuration.endDate for day in self.study_dates):
            raise ValueError("Study dates must be inside the plan period")
        if not set(self.completed_dates).issubset(self.study_dates):
            raise ValueError("Completion dates must be study dates")
        return self


class PlanStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    completed: bool | None = None
    archived: bool | None = None
    share_mode: ShareMode | None = None


class PlanProgressRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    date: date
    done: bool


def serialize_plan(plan: PersonalPlan, *, owner=False, summary=False):
    result = {
        "id": plan.id,
        "name": plan.name,
        "completed": plan.completed,
        "archived": plan.archived,
        "share_mode": plan.share_mode,
        "version": plan.version,
        "created_at": plan.created_at.isoformat(),
        "updated_at": plan.updated_at.isoformat(),
        "can_edit": owner,
        "can_mark": not plan.archived and (owner or plan.share_mode == "read_mark"),
        "completed_dates": json.loads(plan.completed_dates),
        "study_dates": json.loads(plan.study_dates),
    }
    if owner:
        result["share_token"] = plan.share_token
    if not summary:
        result["configuration"] = json.loads(plan.configuration)
    return result


async def owned_plan(plan_id: str, db: AsyncSession, user: User):
    plan = await db.scalar(select(PersonalPlan).where(PersonalPlan.id == plan_id, PersonalPlan.owner_user_id == user.id))
    if plan is None:
        raise HTTPException(404, "Plan not found")
    return plan


async def shared_plan(token: str, db: AsyncSession):
    if len(token) != 43:
        raise HTTPException(404, "Plan not found")
    plan = await db.scalar(select(PersonalPlan).where(PersonalPlan.share_token == token, PersonalPlan.share_mode != "private"))
    if plan is None:
        raise HTTPException(404, "Plan not found")
    return plan


async def change_plan(plan: PersonalPlan, expected_version: int, values: dict, db: AsyncSession):
    result = await db.execute(update(PersonalPlan).where(
        PersonalPlan.id == plan.id, PersonalPlan.version == expected_version,
    ).values(**values, version=PersonalPlan.version + 1, updated_at=utcnow()).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        await db.rollback()
        raise HTTPException(409, "Plan changed. Reload before saving.")
    await db.commit()
    await db.refresh(plan)
    return plan


@router.get("/personal-plans")
async def list_plans(response: Response, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user_depends)):
    response.headers["Cache-Control"] = "private, no-store"
    plans = (await db.scalars(select(PersonalPlan).where(PersonalPlan.owner_user_id == user.id).order_by(PersonalPlan.updated_at.desc()))).all()
    return [serialize_plan(plan, owner=True, summary=True) for plan in plans]


@router.post("/personal-plans", status_code=201)
async def create_plan(body: SavePlanRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user_depends)):
    count = await db.scalar(select(func.count()).select_from(PersonalPlan).where(PersonalPlan.owner_user_id == user.id))
    if count >= 200:
        raise HTTPException(409, "Saved plan limit reached (200)")
    plan = PersonalPlan(
        id=str(uuid4()), owner_user_id=user.id, name=body.name,
        configuration=body.configuration.model_dump_json(),
        study_dates=json.dumps([str(day) for day in body.study_dates]),
        completed_dates=json.dumps(sorted({str(day) for day in body.completed_dates})),
        completed=bool(body.study_dates) and set(body.completed_dates) == set(body.study_dates),
    )
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return serialize_plan(plan, owner=True)


@router.get("/personal-plans/{plan_id}")
async def get_plan(plan_id: str, response: Response, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user_depends)):
    response.headers["Cache-Control"] = "private, no-store"
    return serialize_plan(await owned_plan(plan_id, db, user), owner=True)


@router.put("/personal-plans/{plan_id}")
async def save_plan(plan_id: str, body: SavePlanRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user_depends)):
    plan = await owned_plan(plan_id, db, user)
    if body.expected_version is None:
        raise HTTPException(422, "expected_version is required")
    changed = plan.configuration != body.configuration.model_dump_json()
    values = {
        "name": body.name, "configuration": body.configuration.model_dump_json(),
        "study_dates": json.dumps([str(day) for day in body.study_dates]),
        "completed_dates": json.dumps(sorted({str(day) for day in body.completed_dates})),
    }
    if changed:
        values["completed"] = False
    return serialize_plan(await change_plan(plan, body.expected_version, values, db), owner=True)


@router.patch("/personal-plans/{plan_id}")
async def set_plan_status(plan_id: str, body: PlanStatusRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user_depends)):
    plan = await owned_plan(plan_id, db, user)
    values = body.model_dump(exclude={"expected_version"}, exclude_none=True)
    if body.share_mode is not None and body.share_mode != plan.share_mode:
        values["share_token"] = None if body.share_mode == "private" else secrets.token_urlsafe(32)
    return serialize_plan(await change_plan(plan, body.expected_version, values, db), owner=True)


async def mark_progress(plan: PersonalPlan, body: PlanProgressRequest, db: AsyncSession):
    if plan.archived:
        raise HTTPException(409, "Restore the archived plan before marking progress")
    study_dates = set(json.loads(plan.study_dates))
    day = str(body.date)
    if day not in study_dates:
        raise HTTPException(422, "Not a study date")
    done = set(json.loads(plan.completed_dates))
    if body.done:
        done.add(day)
    else:
        done.discard(day)
    return await change_plan(plan, body.expected_version, {"completed_dates": json.dumps(sorted(done)), "completed": bool(study_dates) and done == study_dates}, db)


@router.patch("/personal-plans/{plan_id}/progress")
async def owner_progress(plan_id: str, body: PlanProgressRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user_depends)):
    return serialize_plan(await mark_progress(await owned_plan(plan_id, db, user), body, db), owner=True)


@router.delete("/personal-plans/{plan_id}", status_code=204)
async def delete_plan(plan_id: str, expected_version: int = Query(ge=1), db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user_depends)):
    plan = await owned_plan(plan_id, db, user)
    result = await db.execute(delete(PersonalPlan).where(PersonalPlan.id == plan.id, PersonalPlan.version == expected_version))
    if result.rowcount != 1:
        await db.rollback()
        raise HTTPException(409, "Plan changed. Reload before deleting.")
    await db.commit()


@router.get("/shared-plans/{token}")
async def get_shared_plan(token: str, response: Response, db: AsyncSession = Depends(get_db)):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return serialize_plan(await shared_plan(token, db))


@router.patch("/shared-plans/{token}/progress")
async def shared_progress(token: str, body: PlanProgressRequest, db: AsyncSession = Depends(get_db)):
    plan = await shared_plan(token, db)
    if plan.share_mode != "read_mark":
        raise HTTPException(403, "This link is read-only")
    return serialize_plan(await mark_progress(plan, body, db))

"""Tenant administered public student intake; approval is an atomic enrollment."""
import json
import secrets
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import (AuditLog, Student, StudentCustomField, StudentRegistrationForm,
                        StudentRegistrationRequest, StudentStatus, Tahfiz, TahfizStatus)
from app.routers.auth import (TenantContext, require_tenant_admin, utcnow,
                              check_rate_limit, record_rate_limit, client_ip)
from app.routers.management import (apply_student_custom_field_values, normalize_student_custom_value,
                                     set_student_categories)
from app.routers.subscriptions import ensure_current_subscription_records
from app.schemas import CreateStudentRequest

router = APIRouter(prefix="/student-registration", tags=["student-registration"])


class FormInput(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    public_field_ids: list[int] = Field(default_factory=list, max_length=100)
    is_active: bool = True

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value):
        if not value.strip():
            raise ValueError("Title is required")
        return value.strip()


class Submission(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=20)
    birthday: date | None = None
    answers: dict[int, str | bool | int | float | None] = Field(default_factory=dict, max_length=100)
    website: str = Field(default="", max_length=200)  # honeypot

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value):
        if not value.strip():
            raise ValueError("Name is required")
        return value.strip()


class Approval(BaseModel):
    student: CreateStudentRequest

    @field_validator("student")
    @classmethod
    def validate_student(cls, value):
        if not value.name.strip():
            raise ValueError("Name is required")
        value.name = value.name.strip()
        return value


def field_data(field):
    return dict(id=field.id, name=field.name, field_type=field.field_type,
                options=json.loads(field.options), is_required=field.is_required)


def form_data(form):
    url = f"{settings.PUBLIC_WEB_URL.rstrip('/')}/register/{form.token}"
    return dict(id=form.id, title=form.title, description=form.description,
                public_field_ids=json.loads(form.public_field_ids), is_active=form.is_active,
                token=form.token, url=url, print_url=url + "/print")


def request_data(row):
    return dict(id=row.id, form_id=row.form_id, name=row.name, phone=row.phone,
                birthday=row.birthday, answers=json.loads(row.answers),
                fields=json.loads(row.field_snapshot), status=row.status,
                student_id=row.student_id, created_at=row.created_at,
                reviewed_at=row.reviewed_at)


async def public_form(token, db):
    form = await db.scalar(select(StudentRegistrationForm).join(Tahfiz).where(
        StudentRegistrationForm.token == token, StudentRegistrationForm.is_active == True,
        Tahfiz.status == TahfizStatus.active))
    if not form:
        raise HTTPException(404, "رابط التسجيل غير متاح")
    return form


async def public_fields(form, db):
    return (await db.execute(select(StudentCustomField).where(
        StudentCustomField.tahfiz_id == form.tahfiz_id,
        StudentCustomField.id.in_(json.loads(form.public_field_ids)),
        StudentCustomField.is_active == True).order_by(StudentCustomField.sort_order, StudentCustomField.id))).scalars().all()


@router.get("/public/{token}")
async def get_public_form(token: str, db: AsyncSession = Depends(get_db)):
    form = await public_form(token, db)
    tahfiz = await db.get(Tahfiz, form.tahfiz_id)
    return dict(title=form.title, description=form.description, tahfiz_name=tahfiz.name,
                fields=[field_data(f) for f in await public_fields(form, db)])


@router.post("/public/{token}", status_code=201)
async def submit(token: str, body: Submission, request: Request, db: AsyncSession = Depends(get_db)):
    key = f"student-registration:{client_ip(request)}"
    await check_rate_limit(db, key, 10, 3600)
    await record_rate_limit(db, key, 3600)
    form = await public_form(token, db)
    if body.website:
        raise HTTPException(422, "تعذر إرسال الطلب")
    fields = await public_fields(form, db)
    allowed = {f.id for f in fields}
    if set(body.answers) - allowed:
        raise HTTPException(422, "تحتوي الإجابة على حقول غير متاحة")
    answers = {str(f.id): normalize_student_custom_value(f, body.answers.get(f.id)) for f in fields}
    db.add(StudentRegistrationRequest(tahfiz_id=form.tahfiz_id, form_id=form.id,
        name=body.name, phone=body.phone, birthday=body.birthday,
        answers=json.dumps(answers, ensure_ascii=False),
        field_snapshot=json.dumps([field_data(f) for f in fields], ensure_ascii=False)))
    await db.commit()
    return {"message": "تم إرسال طلبك. ستراجعه إدارة التحفيظ قبل إضافتك."}


@router.get("/forms")
async def forms(db: AsyncSession = Depends(get_db), context: TenantContext = Depends(require_tenant_admin)):
    rows = (await db.execute(select(StudentRegistrationForm).where(
        StudentRegistrationForm.tahfiz_id == context.tahfiz_id).order_by(StudentRegistrationForm.id.desc()))).scalars().all()
    return [form_data(f) for f in rows]


async def save_form(body, db, context, form=None):
    ids = list(dict.fromkeys(body.public_field_ids))
    found = (await db.execute(select(StudentCustomField.id).where(
        StudentCustomField.tahfiz_id == context.tahfiz_id, StudentCustomField.is_active == True,
        StudentCustomField.id.in_(ids)))).scalars().all()
    if set(ids) != set(found):
        raise HTTPException(422, "One or more fields are unavailable")
    if form is None:
        form = StudentRegistrationForm(tahfiz_id=context.tahfiz_id, token=secrets.token_urlsafe(32))
        db.add(form)
    form.title, form.description = body.title, body.description
    form.public_field_ids, form.is_active = json.dumps(ids), body.is_active
    db.add(AuditLog(actor_user_id=context.user.id, tahfiz_id=context.tahfiz_id,
                    action="student_registration.form_saved", details=body.title))
    await db.commit()
    return form_data(form)


@router.post("/forms", status_code=201)
async def create_form(body: FormInput, db: AsyncSession = Depends(get_db), context: TenantContext = Depends(require_tenant_admin)):
    return await save_form(body, db, context)


@router.put("/forms/{form_id}")
async def update_form(form_id: int, body: FormInput, db: AsyncSession = Depends(get_db), context: TenantContext = Depends(require_tenant_admin)):
    form = await db.scalar(select(StudentRegistrationForm).where(
        StudentRegistrationForm.id == form_id, StudentRegistrationForm.tahfiz_id == context.tahfiz_id))
    if not form:
        raise HTTPException(404, "Form not found")
    return await save_form(body, db, context, form)


@router.get("/notifications")
async def notifications(db: AsyncSession = Depends(get_db), context: TenantContext = Depends(require_tenant_admin)):
    count = await db.scalar(select(func.count()).select_from(StudentRegistrationRequest).where(
        StudentRegistrationRequest.tahfiz_id == context.tahfiz_id, StudentRegistrationRequest.status == "pending"))
    return {"pending_count": count}


@router.get("/requests")
async def requests(status: str = "pending", db: AsyncSession = Depends(get_db), context: TenantContext = Depends(require_tenant_admin)):
    if status not in {"pending", "approved", "rejected"}:
        raise HTTPException(422, "Invalid status")
    rows = (await db.execute(select(StudentRegistrationRequest).where(
        StudentRegistrationRequest.tahfiz_id == context.tahfiz_id,
        StudentRegistrationRequest.status == status).order_by(StudentRegistrationRequest.id.desc()).limit(500))).scalars().all()
    return [request_data(r) for r in rows]


async def claim(request_id, status, db, context):
    # Conditional UPDATE serializes simultaneous approvals, including on SQLite.
    result = await db.execute(update(StudentRegistrationRequest).where(
        StudentRegistrationRequest.id == request_id, StudentRegistrationRequest.tahfiz_id == context.tahfiz_id,
        StudentRegistrationRequest.status == "pending").values(
            status=status, reviewed_by_id=context.user.id, reviewed_at=utcnow()))
    if result.rowcount != 1:
        raise HTTPException(409, "الطلب غير متاح أو تمت مراجعته بالفعل")
    return await db.get(StudentRegistrationRequest, request_id)


@router.post("/requests/{request_id}/reject")
async def reject(request_id: int, db: AsyncSession = Depends(get_db), context: TenantContext = Depends(require_tenant_admin)):
    await claim(request_id, "rejected", db, context)
    db.add(AuditLog(actor_user_id=context.user.id, tahfiz_id=context.tahfiz_id,
                    action="student_registration.rejected", details=f"request={request_id}"))
    await db.commit()
    return {"status": "rejected"}


@router.post("/requests/{request_id}/approve")
async def approve(request_id: int, body: Approval, db: AsyncSession = Depends(get_db), context: TenantContext = Depends(require_tenant_admin)):
    from app.models import Sheikh, ParentPhone, ParentType
    try:
        row = await claim(request_id, "approved", db, context)
        data = body.student
        if data.sheikh_id is not None and not await db.scalar(select(Sheikh.id).where(
                Sheikh.id == data.sheikh_id, Sheikh.tahfiz_id == context.tahfiz_id)):
            raise HTTPException(404, "Sheikh not found")
        student = Student(tahfiz_id=context.tahfiz_id, name=data.name, phone=data.phone,
            birthday=data.birthday, student_id=data.student_id, sheikh_id=data.sheikh_id,
            status=StudentStatus(data.status), registration_date=data.registration_date or date.today(),
            quran_progress_enabled=data.quran_progress_enabled)
        db.add(student)
        await db.flush()
        # Only current fields are written; the original answers remain in the request history.
        active_ids = set((await db.execute(select(StudentCustomField.id).where(
            StudentCustomField.tahfiz_id == context.tahfiz_id, StudentCustomField.is_active == True))).scalars().all())
        values = {int(k): v for k, v in json.loads(row.answers).items() if int(k) in active_ids}
        values.update(data.custom_field_values)
        await apply_student_custom_field_values(db, context, student.id, values)
        await set_student_categories(db, context.tahfiz_id, student.id, data.category_ids)
        for pp in data.parent_phones:
            db.add(ParentPhone(student_id=student.id, phone_number=pp.phone_number,
                               parent_type=ParentType(pp.parent_type), name=pp.name))
        row.student_id = student.id
        if context.tahfiz.subscriptions_enabled and student.status == StudentStatus.enrolled:
            await ensure_current_subscription_records(db, context)
        db.add(AuditLog(actor_user_id=context.user.id, tahfiz_id=context.tahfiz_id,
            action="student_registration.approved", details=f"request={request_id}; student={student.id}"))
        await db.commit()
        return {"student_id": student.id}
    except Exception:
        await db.rollback()
        raise

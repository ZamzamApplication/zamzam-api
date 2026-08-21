import asyncio
import json
import os
import shutil
import sqlite3
import tempfile
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from starlette.background import BackgroundTask
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import delete as sa_delete, func, select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.attendance_streaks import attendance_status_streak
from app.database import get_db

from app.integrations import encrypt_secret, tenant_whatsend_config, validate_whatsend_url
from app.time import utcnow
from app.media import signed_media_url
from app.models import (
    ACTIVE_STUDENT_STATUSES,
    Attendance,
    AuditLog,
    DeviceSession,
    Expense,
    ExcusedWeekday,
    ParentPhone,
    ParentType,
    QuranProgressEntry,
    QuranProgressRevision,
    SavedFilter,
    Session,
    Sheikh,
    Student,
    StudentCategory,
    StudentCategoryMembership,
    StudentCustomField,
    StudentCustomFieldValue,
    StudentExcusedPeriod,
    StudentGoal,
    StudentQuranPlan,
    StudentStatus,
    StudentSubscription,
    StudentWarning,
    Tahfiz,
    TahfizInvitation,
    User,
    UserRole,
    UserTahfizMembership,
    absent_status_option,
    attendance_status_options,
    attendance_status_color_options,
    attendance_streak_status_option,
    present_status_option,
    ATTENDANCE_STATUS_COLOR_KEYS,
    DEFAULT_EXCEL_EXPORT_TEMPLATES,
    excel_export_template_options,
    expense_category_options,
    excused_absence_reset_status_options,
)
from app.routers.auth import TenantContext, get_tenant_context, pwd_context, require_super_admin, require_tenant_admin, student_scope_clause
from app.routers.subscriptions import ensure_current_subscription_records, serialize_record as serialize_subscription_record
from app.schemas import (
    CreateParentPhone,
    CreateExcusedPeriodRequest,
    CreateSheikhRequest,
    CreateStudentRequest,
    StudentCategoryRequest,
    StudentCustomFieldRequest,
    UpdateStudentCustomFieldRequest,
    UpdateStudentCustomFieldValuesRequest,
    CreateUserRequest,
    CreateWarningRequest,
    DeleteSheikhRequest,
    MoveStudentRequest,
    MoveStudentResponse,
    ReorderStudentsRequest,
    SendStudentWarningRequest,
    SendWarningsRequest,
    EarlyReturnRequest,
    ExcusedPeriodOut,
    UpdateTahfizSettingsRequest,
    UpdateExcusedWeekdaysRequest,
    UpdateExcusedPeriodRequest,
    UpdateParentPhone,
    UpdateSheikhRequest,
    UpdateStudentRequest,
    UpdateUserRequest,
)

router = APIRouter(tags=["management"])

UPLOAD_DIR = Path(settings.UPLOAD_DIR)
UPLOAD_DIR.mkdir(exist_ok=True)
MAX_PROFILE_UPLOAD_BYTES = 10 * 1024 * 1024
PROFILE_IMAGE_SIZE = (512, 512)
PROFILE_IMAGE_QUALITY = 82


def serialize_student_categories(student: Student) -> list[dict]:
    return [
        {"id": membership.category.id, "name": membership.category.name}
        for membership in sorted(student.category_memberships, key=lambda row: (row.category.name, row.category.id))
    ]


async def set_student_categories(
    db: AsyncSession,
    tahfiz_id: int,
    student_id: int,
    category_ids: list[int],
) -> None:
    requested = set(category_ids)
    valid = set((await db.execute(select(StudentCategory.id).where(
        StudentCategory.tahfiz_id == tahfiz_id,
        StudentCategory.id.in_(requested),
    ))).scalars().all()) if requested else set()
    if valid != requested:
        raise HTTPException(status_code=404, detail="One or more student categories were not found")
    await db.execute(sa_delete(StudentCategoryMembership).where(
        StudentCategoryMembership.tahfiz_id == tahfiz_id,
        StudentCategoryMembership.student_id == student_id,
    ))
    for category_id in category_ids:
        db.add(StudentCategoryMembership(
            tahfiz_id=tahfiz_id,
            category_id=category_id,
            student_id=student_id,
        ))


def serialize_student_custom_field(field: StudentCustomField, context: TenantContext) -> dict:
    try:
        options = json.loads(field.options or "[]")
    except (TypeError, json.JSONDecodeError):
        options = []
    is_admin = context.effective_role in (UserRole.admin, UserRole.super_admin)
    return {
        "id": field.id,
        "name": field.name,
        "field_type": field.field_type,
        "options": options if isinstance(options, list) else [],
        "is_required": field.is_required,
        "is_active": field.is_active,
        "sort_order": field.sort_order,
        "created_by_user_id": field.created_by_user_id,
        "can_edit": is_admin or field.created_by_user_id == context.user.id,
    }


def can_create_student_custom_fields(context: TenantContext) -> bool:
    return (
        context.effective_role in (UserRole.admin, UserRole.super_admin)
        or (context.effective_role == UserRole.sheikh and context.tahfiz.sheikh_custom_fields_enabled is True)
    )


def normalize_student_custom_value(field: StudentCustomField, raw_value) -> str | None:
    if raw_value is None or raw_value == "":
        if field.is_required:
            raise HTTPException(status_code=422, detail={"code": "required_custom_field", "field_id": field.id})
        return None
    if field.field_type == "text":
        value = str(raw_value).strip()
        if len(value) > 2000:
            raise HTTPException(status_code=422, detail={"code": "custom_field_value_too_long", "field_id": field.id})
        return value or None
    if field.field_type == "number":
        try:
            value = Decimal(str(raw_value))
        except InvalidOperation as exc:
            raise HTTPException(status_code=422, detail={"code": "invalid_custom_field_number", "field_id": field.id}) from exc
        if not value.is_finite():
            raise HTTPException(status_code=422, detail={"code": "invalid_custom_field_number", "field_id": field.id})
        return format(value, "f")
    if field.field_type == "date":
        try:
            return date.fromisoformat(str(raw_value)).isoformat()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "invalid_custom_field_date", "field_id": field.id}) from exc
    if field.field_type == "checkbox":
        if isinstance(raw_value, bool):
            return "true" if raw_value else "false"
        if str(raw_value).lower() in {"true", "false"}:
            return str(raw_value).lower()
        raise HTTPException(status_code=422, detail={"code": "invalid_custom_field_checkbox", "field_id": field.id})
    options = json.loads(field.options or "[]")
    value = str(raw_value)
    if value not in options:
        raise HTTPException(status_code=422, detail={"code": "invalid_custom_field_option", "field_id": field.id})
    return value


async def apply_student_custom_field_values(
    db: AsyncSession,
    context: TenantContext,
    student_id: int,
    raw_values: dict[int, str | bool | int | float | None],
) -> dict[int, str]:
    active_fields = (await db.execute(select(StudentCustomField).where(
        StudentCustomField.tahfiz_id == context.tahfiz_id,
        StudentCustomField.is_active == True,
    ))).scalars().all()
    field_map = {field.id: field for field in active_fields}
    if any(field_id not in field_map for field_id in raw_values):
        raise HTTPException(status_code=404, detail="One or more custom fields were not found")

    existing_rows = (await db.execute(select(StudentCustomFieldValue).where(
        StudentCustomFieldValue.tahfiz_id == context.tahfiz_id,
        StudentCustomFieldValue.student_id == student_id,
    ))).scalars().all()
    existing = {row.field_id: row for row in existing_rows}
    normalized_updates = {
        field_id: normalize_student_custom_value(field_map[field_id], value)
        for field_id, value in raw_values.items()
    }
    final_values = {field_id: row.value for field_id, row in existing.items()}
    for field_id, value in normalized_updates.items():
        if value is None:
            final_values.pop(field_id, None)
        else:
            final_values[field_id] = value

    missing_required = [field.id for field in active_fields if field.is_required and not final_values.get(field.id)]
    if missing_required:
        raise HTTPException(status_code=422, detail={"code": "required_custom_fields", "field_ids": missing_required})

    for field_id, value in normalized_updates.items():
        row = existing.get(field_id)
        if value is None:
            if row:
                await db.delete(row)
        elif row:
            row.value = value
            row.updated_by_user_id = context.user.id
            row.updated_at = utcnow()
        else:
            db.add(StudentCustomFieldValue(
                tahfiz_id=context.tahfiz_id,
                student_id=student_id,
                field_id=field_id,
                value=value,
                updated_by_user_id=context.user.id,
            ))
    return final_values


@router.get("/student-custom-fields")
async def list_student_custom_fields(
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    query = select(StudentCustomField).where(StudentCustomField.tahfiz_id == context.tahfiz_id)
    if not include_inactive:
        query = query.where(StudentCustomField.is_active == True)
    rows = (await db.execute(query.order_by(StudentCustomField.sort_order, StudentCustomField.name, StudentCustomField.id))).scalars().all()
    return {
        "fields": [serialize_student_custom_field(row, context) for row in rows],
        "can_create": can_create_student_custom_fields(context),
    }


@router.post("/student-custom-fields", status_code=201)
async def create_student_custom_field(
    body: StudentCustomFieldRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    if not can_create_student_custom_fields(context):
        raise HTTPException(status_code=403, detail="Custom field creation is disabled")
    duplicate = await db.scalar(select(StudentCustomField.id).where(
        StudentCustomField.tahfiz_id == context.tahfiz_id,
        StudentCustomField.name == body.name,
    ))
    if duplicate is not None:
        raise HTTPException(status_code=409, detail={"code": "student_custom_field_name_exists"})
    max_order = int(await db.scalar(select(func.coalesce(func.max(StudentCustomField.sort_order), -1)).where(
        StudentCustomField.tahfiz_id == context.tahfiz_id,
    )) or 0)
    field = StudentCustomField(
        tahfiz_id=context.tahfiz_id,
        name=body.name,
        field_type=body.field_type,
        options=json.dumps(body.options, ensure_ascii=False),
        is_required=body.is_required,
        sort_order=max_order + 1,
        created_by_user_id=context.user.id,
    )
    db.add(field)
    await db.flush()
    db.add(AuditLog(actor_user_id=context.user.id, tahfiz_id=context.tahfiz_id, action="student_custom_field.created", details=f"field={field.id}; name={field.name}"))
    await db.commit()
    return serialize_student_custom_field(field, context)


@router.put("/student-custom-fields/{field_id}")
async def update_student_custom_field(
    field_id: int,
    body: UpdateStudentCustomFieldRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    field = await db.scalar(select(StudentCustomField).where(StudentCustomField.id == field_id, StudentCustomField.tahfiz_id == context.tahfiz_id))
    if not field:
        raise HTTPException(status_code=404, detail="Student custom field not found")
    if context.effective_role not in (UserRole.admin, UserRole.super_admin) and field.created_by_user_id != context.user.id:
        raise HTTPException(status_code=403, detail="Not allowed to edit this custom field")
    duplicate = await db.scalar(select(StudentCustomField.id).where(
        StudentCustomField.tahfiz_id == context.tahfiz_id,
        StudentCustomField.name == body.name,
        StudentCustomField.id != field_id,
    ))
    if duplicate is not None:
        raise HTTPException(status_code=409, detail={"code": "student_custom_field_name_exists"})
    value_rows = (await db.execute(select(StudentCustomFieldValue.value).where(
        StudentCustomFieldValue.tahfiz_id == context.tahfiz_id,
        StudentCustomFieldValue.field_id == field.id,
    ))).scalars().all()
    if field.field_type != body.field_type and value_rows:
        raise HTTPException(status_code=409, detail={"code": "custom_field_type_locked"})
    if body.field_type == "select" and any(value not in body.options for value in value_rows):
        raise HTTPException(status_code=409, detail={"code": "custom_field_options_in_use"})
    field.name = body.name
    field.field_type = body.field_type
    field.options = json.dumps(body.options, ensure_ascii=False)
    field.is_required = body.is_required
    field.is_active = body.is_active
    db.add(AuditLog(actor_user_id=context.user.id, tahfiz_id=context.tahfiz_id, action="student_custom_field.updated", details=f"field={field.id}; name={field.name}; active={field.is_active}"))
    await db.commit()
    return serialize_student_custom_field(field, context)


@router.put("/students/{student_id}/custom-field-values")
async def update_student_custom_field_values(
    student_id: int,
    body: UpdateStudentCustomFieldValuesRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    student = await db.scalar(select(Student).where(Student.id == student_id, student_scope_clause(context)))
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    raw_values = {item.field_id: item.value for item in body.values}
    final_values = await apply_student_custom_field_values(db, context, student_id, raw_values)
    field_ids = list(raw_values)
    db.add(AuditLog(actor_user_id=context.user.id, tahfiz_id=context.tahfiz_id, action="student.custom_fields_updated", details=f"student={student_id}; fields={','.join(map(str, field_ids))}"))
    await db.commit()
    return {"student_id": student_id, "values": {str(field_id): value for field_id, value in final_values.items()}}


@router.get("/student-categories")
async def list_student_categories(
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    rows = (await db.execute(select(StudentCategory).where(
        StudentCategory.tahfiz_id == context.tahfiz_id,
    ).order_by(StudentCategory.name, StudentCategory.id))).scalars().all()
    counts = dict((await db.execute(
        select(StudentCategoryMembership.category_id, func.count(StudentCategoryMembership.id))
        .join(Student, Student.id == StudentCategoryMembership.student_id)
        .where(
            StudentCategoryMembership.tahfiz_id == context.tahfiz_id,
            Student.tahfiz_id == context.tahfiz_id,
            Student.status.in_(ACTIVE_STUDENT_STATUSES),
        )
        .group_by(StudentCategoryMembership.category_id)
    )).all())
    return [{"id": row.id, "name": row.name, "student_count": counts.get(row.id, 0)} for row in rows]


@router.post("/student-categories", status_code=201)
async def create_student_category(
    body: StudentCategoryRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    existing = await db.scalar(select(StudentCategory.id).where(
        StudentCategory.tahfiz_id == context.tahfiz_id,
        StudentCategory.name == body.name,
    ))
    if existing is not None:
        raise HTTPException(status_code=409, detail={"code": "student_category_name_exists"})
    category = StudentCategory(tahfiz_id=context.tahfiz_id, name=body.name)
    db.add(category)
    await db.flush()
    db.add(AuditLog(
        actor_user_id=context.user.id,
        tahfiz_id=context.tahfiz_id,
        action="student_category.created",
        details=f"category={category.id}; name={category.name}",
    ))
    await db.commit()
    return {"id": category.id, "name": category.name, "student_count": 0}


@router.put("/student-categories/{category_id}")
async def update_student_category(
    category_id: int,
    body: StudentCategoryRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    category = await db.scalar(select(StudentCategory).where(
        StudentCategory.id == category_id,
        StudentCategory.tahfiz_id == context.tahfiz_id,
    ))
    if not category:
        raise HTTPException(status_code=404, detail="Student category not found")
    duplicate = await db.scalar(select(StudentCategory.id).where(
        StudentCategory.tahfiz_id == context.tahfiz_id,
        StudentCategory.name == body.name,
        StudentCategory.id != category_id,
    ))
    if duplicate is not None:
        raise HTTPException(status_code=409, detail={"code": "student_category_name_exists"})
    previous = category.name
    category.name = body.name
    db.add(AuditLog(
        actor_user_id=context.user.id,
        tahfiz_id=context.tahfiz_id,
        action="student_category.updated",
        details=f"category={category.id}; from={previous}; to={category.name}",
    ))
    await db.commit()
    return {"id": category.id, "name": category.name}


@router.delete("/student-categories/{category_id}")
async def delete_student_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    category = await db.scalar(select(StudentCategory).where(
        StudentCategory.id == category_id,
        StudentCategory.tahfiz_id == context.tahfiz_id,
    ))
    if not category:
        raise HTTPException(status_code=404, detail="Student category not found")
    await db.execute(sa_delete(StudentCategoryMembership).where(
        StudentCategoryMembership.tahfiz_id == context.tahfiz_id,
        StudentCategoryMembership.category_id == category_id,
    ))
    await db.delete(category)
    db.add(AuditLog(
        actor_user_id=context.user.id,
        tahfiz_id=context.tahfiz_id,
        action="student_category.deleted",
        details=f"category={category_id}; name={category.name}",
    ))
    await db.commit()
    return {"message": "Student category deleted"}


def serialize_excused_period(period: StudentExcusedPeriod) -> dict:
    today = utcnow().date()
    if period.cancelled_at is not None:
        status = "cancelled"
    elif today < period.start_date:
        status = "upcoming"
    elif today <= period.end_date:
        status = "active"
    else:
        status = "completed"
    return {
        "id": period.id,
        "student_id": period.student_id,
        "start_date": period.start_date.isoformat(),
        "end_date": period.end_date.isoformat(),
        "reason": period.reason,
        "status": status,
        "cancelled_at": period.cancelled_at.isoformat() if period.cancelled_at else None,
        "created_at": period.created_at.isoformat(),
        "updated_at": period.updated_at.isoformat(),
    }


async def ensure_no_excused_period_overlap(
    db: AsyncSession,
    tahfiz_id: int,
    student_id: int,
    start_date: date,
    end_date: date,
    *,
    exclude_id: int | None = None,
) -> None:
    query = select(StudentExcusedPeriod.id).where(
        StudentExcusedPeriod.tahfiz_id == tahfiz_id,
        StudentExcusedPeriod.student_id == student_id,
        StudentExcusedPeriod.cancelled_at.is_(None),
        StudentExcusedPeriod.start_date <= end_date,
        StudentExcusedPeriod.end_date >= start_date,
    )
    if exclude_id is not None:
        query = query.where(StudentExcusedPeriod.id != exclude_id)
    if await db.scalar(query):
        raise HTTPException(status_code=409, detail={"code": "excused_period_overlap"})


def build_warning_message(student_name: str, warning_number: int, reason: str, remaining: int) -> str:
    return (
        f"انذار رقم {warning_number} الى الطالب \"{student_name}\"\n"
        f" بسبب غيابه بدون اعتذار عن حلقات:\n"
        f"{reason}\n\n"
        f"عدد الانذارات المتبقية قبل الاستبعاد: {remaining}\n\n"
        "— تم إرسال هذه الرسالة عبر نظام زمزم الآلي —"
    )


@router.get("/whatsend/groups")
async def list_whatsend_groups(
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    tahfiz = await db.get(Tahfiz, context.tahfiz_id)
    if not tahfiz.whatsend_enabled:
        raise HTTPException(status_code=409, detail="تكامل واتساب غير مفعّل")
    try:
        return {"groups": await fetch_whatsend_groups(tahfiz)}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"فشل تحميل مجموعات واتساب: {whatsend_error(e)}")


def whatsend_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        response = exc.response
        try:
            data = response.json()
        except ValueError:
            data = None
        detail = data.get("detail") or data.get("message") or data.get("error") if isinstance(data, dict) else None
        if not detail:
            detail = response.text[:500] or response.reason_phrase
        return str(detail)
    if isinstance(exc, httpx.TimeoutException):
        return "انتهت مهلة الاتصال بخدمة واتساب"
    if isinstance(exc, httpx.RequestError):
        return f"تعذر الاتصال بخدمة واتساب: {exc}"
    return str(exc)


async def validate_whatsend_setting_url(enabled: bool, url: str) -> None:
    """Validate network destinations only while the integration is active."""
    if enabled and url:
        await validate_whatsend_url(url)


async def send_whatsend_group_message(tahfiz: Tahfiz, group_id: str, message: str) -> None:
    if not tahfiz.whatsend_enabled:
        raise ValueError("تكامل واتساب غير مفعّل")
    api_url, _, api_key = tenant_whatsend_config(tahfiz)
    if not api_key:
        raise RuntimeError("مفتاح WhatSend API غير مضبوط")
    await validate_whatsend_url(api_url)
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            api_url,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"group_id": group_id, "message": message},
        )
        resp.raise_for_status()


async def fetch_whatsend_groups(tahfiz: Tahfiz) -> list[dict]:
    _, groups_url, api_key = tenant_whatsend_config(tahfiz)
    if not api_key:
        raise RuntimeError("مفتاح WhatSend API غير مضبوط")
    await validate_whatsend_url(groups_url)
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            groups_url,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        resp.raise_for_status()
    data = resp.json()
    groups = data.get("groups", [])
    return [
        {"id": group.get("id"), "name": group.get("name") or group.get("id")}
        for group in groups
        if group.get("id")
    ]


def local_upload_name(path: str | None) -> str | None:
    if not path or path.startswith(("http://", "https://")):
        return None
    if path.startswith("/uploads/"):
        return path.removeprefix("/uploads/")
    if path.startswith("uploads/"):
        return path.removeprefix("uploads/")
    return path


def delete_upload(path: str | None) -> None:
    name = local_upload_name(path)
    if not name:
        return
    target = (UPLOAD_DIR / name).resolve()
    upload_root = UPLOAD_DIR.resolve()
    if upload_root not in target.parents or not target.is_file():
        return
    target.unlink(missing_ok=True)


def compress_profile_image(content: bytes) -> bytes:
    if len(content) > MAX_PROFILE_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Image is too large. Maximum size is 10MB.")

    try:
        with Image.open(BytesIO(content)) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail(PROFILE_IMAGE_SIZE, Image.Resampling.LANCZOS)

            if image.mode not in ("RGB", "L"):
                background = Image.new("RGB", image.size, "white")
                if "A" in image.getbands():
                    background.paste(image, mask=image.getchannel("A"))
                else:
                    background.paste(image)
                image = background
            elif image.mode != "RGB":
                image = image.convert("RGB")

            output = BytesIO()
            image.save(output, format="WEBP", quality=PROFILE_IMAGE_QUALITY, method=6)
            return output.getvalue()
    except UnidentifiedImageError:
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid image.")


# ─── Sheikhs ─────────────────────────────────────────────────────────────────


@router.get("/sheikhs")
async def list_sheikhs(
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    result = await db.execute(
        select(Sheikh)
        .options(selectinload(Sheikh.tahfiz))
        .where(
            Sheikh.tahfiz_id == context.tahfiz_id,
            *([Sheikh.id == context.sheikh_id] if context.restricts_sheikh_students else []),
        )
    )
    sheikhs = result.scalars().all()
    return [
        {
            "id": s.id,
            "name": s.name,
            "phone": s.phone,
            "whatsapp_group_id": s.whatsapp_group_id,
            "attendance_all_students_access": s.attendance_all_students_access is True,
            "tahfiz_id": s.tahfiz_id,
            "tahfiz_name": s.tahfiz.name,
            "circle_id": s.tahfiz_id,
            "circle_name": s.tahfiz.name,
            "week_start_day": s.tahfiz.week_start_day,
            "month_start_day": s.tahfiz.month_start_day,
        }
        for s in sheikhs
    ]


@router.post("/sheikhs")
async def create_sheikh(
    body: CreateSheikhRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    sheikh = Sheikh(
        name=body.name,
        phone=body.phone,
        whatsapp_group_id=body.whatsapp_group_id,
        attendance_all_students_access=body.attendance_all_students_access,
        tahfiz_id=context.tahfiz_id,
    )
    db.add(sheikh)
    await db.flush()
    if sheikh.attendance_all_students_access:
        db.add(AuditLog(
            actor_user_id=context.user.id,
            tahfiz_id=context.tahfiz_id,
            action="sheikh.attendance_access_updated",
            details=json.dumps({
                "sheikh_id": sheikh.id,
                "attendance_all_students_access": True,
            }, sort_keys=True),
        ))
    await db.commit()
    return {"id": sheikh.id, "name": sheikh.name, "phone": sheikh.phone, "whatsapp_group_id": sheikh.whatsapp_group_id, "attendance_all_students_access": sheikh.attendance_all_students_access, "tahfiz_id": sheikh.tahfiz_id, "circle_id": sheikh.tahfiz_id}


@router.put("/sheikhs/{sheikh_id}")
async def update_sheikh(
    sheikh_id: int,
    body: UpdateSheikhRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    result = await db.execute(select(Sheikh).where(Sheikh.id == sheikh_id, Sheikh.tahfiz_id == context.tahfiz_id))
    sheikh = result.scalar_one_or_none()
    if not sheikh:
        raise HTTPException(status_code=404, detail="Sheikh not found")
    if body.name is not None:
        sheikh.name = body.name
    if body.phone is not None:
        sheikh.phone = body.phone
    if body.whatsapp_group_id is not None:
        sheikh.whatsapp_group_id = body.whatsapp_group_id
    if (
        body.attendance_all_students_access is not None
        and sheikh.attendance_all_students_access != body.attendance_all_students_access
    ):
        sheikh.attendance_all_students_access = body.attendance_all_students_access
        db.add(AuditLog(
            actor_user_id=context.user.id,
            tahfiz_id=context.tahfiz_id,
            action="sheikh.attendance_access_updated",
            details=json.dumps({
                "sheikh_id": sheikh.id,
                "attendance_all_students_access": body.attendance_all_students_access,
            }, sort_keys=True),
        ))
    await db.commit()
    return {"id": sheikh.id, "name": sheikh.name, "phone": sheikh.phone, "whatsapp_group_id": sheikh.whatsapp_group_id, "attendance_all_students_access": sheikh.attendance_all_students_access, "tahfiz_id": sheikh.tahfiz_id, "circle_id": sheikh.tahfiz_id}


async def sheikh_deletion_students(
    db: AsyncSession,
    tahfiz_id: int,
    sheikh_id: int,
) -> list[Student]:
    return list((await db.execute(
        select(Student)
        .options(
            selectinload(Student.attendance_records),
            selectinload(Student.parent_phones),
            selectinload(Student.warnings),
            selectinload(Student.excused_weekdays),
            selectinload(Student.excused_periods),
        )
        .where(
            Student.tahfiz_id == tahfiz_id,
            Student.sheikh_id == sheikh_id,
        )
        .order_by(Student.name, Student.id)
    )).scalars().all())


async def delete_student_entity(
    db: AsyncSession,
    student: Student,
    tahfiz_id: int,
    *,
    delete_attendance: bool,
) -> None:
    await db.execute(sa_delete(StudentQuranPlan).where(
        StudentQuranPlan.student_id == student.id,
        StudentQuranPlan.tahfiz_id == tahfiz_id,
    ))
    await db.execute(sa_delete(StudentSubscription).where(
        StudentSubscription.student_id == student.id,
        StudentSubscription.tahfiz_id == tahfiz_id,
        StudentSubscription.is_paid.is_(False),
    ))
    await db.execute(sa_update(StudentSubscription).where(
        StudentSubscription.student_id == student.id,
        StudentSubscription.tahfiz_id == tahfiz_id,
    ).values(student_id=None))
    await db.execute(sa_delete(QuranProgressRevision).where(
        QuranProgressRevision.student_id == student.id,
        QuranProgressRevision.tahfiz_id == tahfiz_id,
    ))
    await db.execute(sa_delete(QuranProgressEntry).where(
        QuranProgressEntry.student_id == student.id,
        QuranProgressEntry.tahfiz_id == tahfiz_id,
    ))
    await db.execute(sa_delete(StudentGoal).where(
        StudentGoal.student_id == student.id,
        StudentGoal.tahfiz_id == tahfiz_id,
    ))
    if not delete_attendance:
        for attendance in student.attendance_records:
            attendance.student_id = None
    await db.delete(student)


def validate_sheikh_deletion_plan(
    assigned_ids: set[int],
    body: DeleteSheikhRequest,
    deleted_sheikh_id: int,
    valid_target_ids: set[int],
) -> None:
    submitted_ids = {item.student_id for item in body.student_resolutions}
    if assigned_ids != submitted_ids:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "sheikh_students_changed",
                "message": "تغيرت قائمة طلاب الشيخ. راجع الخيارات ثم أعد المحاولة.",
                "assigned_student_ids": sorted(assigned_ids),
            },
        )
    requested_target_ids = {
        item.sheikh_id
        for item in body.student_resolutions
        if item.action == "reassign" and item.sheikh_id is not None
    }
    if deleted_sheikh_id in requested_target_ids:
        raise HTTPException(status_code=400, detail={"code": "cannot_reassign_to_deleted_sheikh"})
    if valid_target_ids != requested_target_ids:
        raise HTTPException(status_code=404, detail={"code": "destination_sheikh_not_found"})


async def finalize_sheikh_deletion(
    db: AsyncSession,
    context: TenantContext,
    sheikh: Sheikh,
    students: list[Student],
    body: DeleteSheikhRequest,
) -> dict:
    assigned_ids = {student.id for student in students}
    target_ids = {
        item.sheikh_id
        for item in body.student_resolutions
        if item.action == "reassign" and item.sheikh_id is not None
    }
    valid_targets = set((await db.execute(
        select(Sheikh.id).where(
            Sheikh.tahfiz_id == context.tahfiz_id,
            Sheikh.id.in_(target_ids),
        )
    )).scalars().all()) if target_ids else set()
    validate_sheikh_deletion_plan(assigned_ids, body, sheikh.id, valid_targets)

    by_student_id = {student.id: student for student in students}
    reassigned = 0
    deleted = 0
    for resolution in body.student_resolutions:
        student = by_student_id[resolution.student_id]
        if resolution.action == "reassign":
            student.sheikh_id = resolution.sheikh_id
            student.sort_order = 0
            reassigned += 1
            db.add(AuditLog(
                actor_user_id=context.user.id,
                tahfiz_id=context.tahfiz_id,
                action="student.reassigned_before_sheikh_delete",
                details=f"student={student.id}; from_sheikh={sheikh.id}; to_sheikh={resolution.sheikh_id}",
            ))
        else:
            await delete_student_entity(
                db, student, context.tahfiz_id, delete_attendance=True
            )
            deleted += 1
            db.add(AuditLog(
                actor_user_id=context.user.id,
                tahfiz_id=context.tahfiz_id,
                action="student.deleted_before_sheikh_delete",
                details=f"student={student.id}; name={student.name}; sheikh={sheikh.id}; delete_attendance=True",
            ))

    await db.flush()
    await db.execute(sa_update(Attendance).where(
        Attendance.sheikh_id == sheikh.id,
        Attendance.tahfiz_id == context.tahfiz_id,
    ).values(sheikh_id=None))
    await db.execute(sa_update(QuranProgressEntry).where(
        QuranProgressEntry.sheikh_id == sheikh.id,
        QuranProgressEntry.tahfiz_id == context.tahfiz_id,
    ).values(sheikh_id=None))
    await db.execute(sa_update(User).where(
        User.sheikh_id == sheikh.id,
        User.tahfiz_id == context.tahfiz_id,
    ).values(sheikh_id=None))
    await db.execute(sa_update(UserTahfizMembership).where(
        UserTahfizMembership.sheikh_id == sheikh.id,
        UserTahfizMembership.tahfiz_id == context.tahfiz_id,
    ).values(sheikh_id=None))
    now = utcnow()
    await db.execute(sa_update(TahfizInvitation).where(
        TahfizInvitation.sheikh_id == sheikh.id,
        TahfizInvitation.tahfiz_id == context.tahfiz_id,
        TahfizInvitation.used_at.is_(None),
        TahfizInvitation.revoked_at.is_(None),
    ).values(sheikh_id=None, revoked_at=now))
    await db.execute(sa_update(TahfizInvitation).where(
        TahfizInvitation.sheikh_id == sheikh.id,
        TahfizInvitation.tahfiz_id == context.tahfiz_id,
    ).values(sheikh_id=None))
    db.add(AuditLog(
        actor_user_id=context.user.id,
        tahfiz_id=context.tahfiz_id,
        action="sheikh.deleted",
        details=f"sheikh={sheikh.id}; name={sheikh.name}; reassigned_students={reassigned}; deleted_students={deleted}",
    ))
    await db.delete(sheikh)
    await db.commit()
    return {
        "message": "تم حذف الشيخ ومعالجة جميع الطلاب",
        "reassigned_students": reassigned,
        "deleted_students": deleted,
    }


@router.get("/sheikhs/{sheikh_id}/deletion-preview")
async def sheikh_deletion_preview(
    sheikh_id: int,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    sheikh = await db.scalar(select(Sheikh).where(
        Sheikh.id == sheikh_id,
        Sheikh.tahfiz_id == context.tahfiz_id,
    ))
    if not sheikh:
        raise HTTPException(status_code=404, detail="Sheikh not found")
    students = await sheikh_deletion_students(db, context.tahfiz_id, sheikh_id)
    destinations = (await db.execute(select(Sheikh).where(
        Sheikh.tahfiz_id == context.tahfiz_id,
        Sheikh.id != sheikh_id,
    ).order_by(Sheikh.name, Sheikh.id))).scalars().all()
    linked_users = (await db.execute(
        select(User.username)
        .join(UserTahfizMembership, UserTahfizMembership.user_id == User.id)
        .where(
            UserTahfizMembership.tahfiz_id == context.tahfiz_id,
            UserTahfizMembership.sheikh_id == sheikh_id,
            UserTahfizMembership.is_active == True,
        )
        .order_by(User.username)
    )).scalars().all()
    return {
        "sheikh": {"id": sheikh.id, "name": sheikh.name},
        "students": [
            {"id": student.id, "name": student.name, "student_id": student.student_id, "phone": student.phone, "status": student.status.value}
            for student in students
        ],
        "destination_sheikhs": [{"id": target.id, "name": target.name} for target in destinations],
        "linked_usernames": list(linked_users),
    }


@router.post("/sheikhs/{sheikh_id}/delete")
async def delete_sheikh_with_student_resolutions(
    sheikh_id: int,
    body: DeleteSheikhRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    sheikh = await db.scalar(select(Sheikh).where(
        Sheikh.id == sheikh_id,
        Sheikh.tahfiz_id == context.tahfiz_id,
    ))
    if not sheikh:
        raise HTTPException(status_code=404, detail="Sheikh not found")
    students = await sheikh_deletion_students(db, context.tahfiz_id, sheikh_id)
    return await finalize_sheikh_deletion(db, context, sheikh, students, body)


@router.delete("/sheikhs/{sheikh_id}")
async def delete_sheikh(
    sheikh_id: int,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    result = await db.execute(select(Sheikh).where(Sheikh.id == sheikh_id, Sheikh.tahfiz_id == context.tahfiz_id))
    sheikh = result.scalar_one_or_none()
    if not sheikh:
        raise HTTPException(status_code=404, detail="Sheikh not found")
    students = await sheikh_deletion_students(db, context.tahfiz_id, sheikh_id)
    if students:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "sheikh_has_students",
                "message": "يجب اختيار نقل أو حذف كل طالب قبل حذف الشيخ.",
                "assigned_student_ids": [student.id for student in students],
            },
        )
    return await finalize_sheikh_deletion(
        db, context, sheikh, students, DeleteSheikhRequest(student_resolutions=[])
    )


# ─── Sheikh Students ─────────────────────────────────────────────────────────


@router.get("/sheikhs/{sheikh_id}/students")
async def get_sheikh_students(
    sheikh_id: int,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    sheikh = await db.scalar(select(Sheikh).where(Sheikh.id == sheikh_id, Sheikh.tahfiz_id == context.tahfiz_id))
    if not sheikh:
        raise HTTPException(status_code=404, detail="Sheikh not found")
    result = await db.execute(
        select(Student)
        .options(
            selectinload(Student.parent_phones),
            selectinload(Student.warnings),
            selectinload(Student.category_memberships).selectinload(StudentCategoryMembership.category),
        )
        .where(
            Student.sheikh_id == sheikh_id,
            Student.tahfiz_id == context.tahfiz_id,
        )
        .order_by(Student.name)
    )
    records = result.scalars().all()

    # Batch-load excused weekdays for all students
    student_ids = [r.id for r in records]
    ew_result = await db.execute(
        select(ExcusedWeekday).where(ExcusedWeekday.student_id.in_(student_ids))
    )
    ew_map: dict[int, list[dict[str, int | str | None]]] = {}
    for ew in ew_result.scalars().all():
        ew_map.setdefault(ew.student_id, []).append({"id": ew.id, "weekday": ew.weekday, "note": ew.note})

    return [
        {
            "id": r.id,
            "name": r.name,
            "phone": r.phone,
            "student_id": r.student_id,
            "birthday": r.birthday.isoformat() if r.birthday else None,
            "profile_pic": signed_media_url(r.profile_pic, context.tahfiz_id),
            "status": r.status.value,
            "registration_date": r.registration_date.isoformat() if r.registration_date else None,
            "warnings": [
                {"id": w.id, "reason": w.reason, "warning_number": w.warning_number, "sent": w.sent, "sent_at": w.sent_at.isoformat() if w.sent_at else None, "created_at": w.created_at.isoformat()}
                for w in r.warnings
            ],
            "parent_phones": [
                {"id": p.id, "phone_number": p.phone_number, "parent_type": p.parent_type.value, "name": p.name}
                for p in r.parent_phones
            ],
            "excused_weekdays": ew_map.get(r.id, []),
            "categories": serialize_student_categories(r),
            "category_ids": [item["id"] for item in serialize_student_categories(r)],
        }
        for r in records
    ]


@router.put("/sheikhs/{sheikh_id}/students/reorder")
async def reorder_students(
    sheikh_id: int,
    body: ReorderStudentsRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    for i, student_id in enumerate(body.student_ids):
        result = await db.execute(
            select(Student).where(
                Student.id == student_id,
                Student.sheikh_id == sheikh_id,
                Student.tahfiz_id == context.tahfiz_id,
            )
        )
        student = result.scalar_one_or_none()
        if student:
            student.sort_order = i
    await db.commit()
    return {"message": "تم إعادة الترتيب"}


# ─── Students ────────────────────────────────────────────────────────────────


@router.get("/students")
async def list_students(
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    result = await db.execute(
        select(Student)
        .options(
            selectinload(Student.sheikh),
            selectinload(Student.parent_phones),
            selectinload(Student.warnings),
            selectinload(Student.category_memberships).selectinload(StudentCategoryMembership.category),
        )
        .where(Student.tahfiz_id == context.tahfiz_id)
        .order_by(Student.name)
    )
    students = result.scalars().all()

    student_ids = [s.id for s in students]
    custom_value_rows = (await db.execute(select(StudentCustomFieldValue).where(
        StudentCustomFieldValue.tahfiz_id == context.tahfiz_id,
        StudentCustomFieldValue.student_id.in_(student_ids),
    ))).scalars().all() if student_ids else []
    custom_values_by_student: dict[int, dict[str, str]] = {}
    for value_row in custom_value_rows:
        custom_values_by_student.setdefault(value_row.student_id, {})[str(value_row.field_id)] = value_row.value
    ew_result = await db.execute(
        select(ExcusedWeekday).where(ExcusedWeekday.student_id.in_(student_ids))
    )
    ew_map: dict[int, list[dict[str, int | str | None]]] = {}
    for ew in ew_result.scalars().all():
        ew_map.setdefault(ew.student_id, []).append({"id": ew.id, "weekday": ew.weekday, "note": ew.note})

    return [
        {
            "id": s.id,
            "name": s.name,
            "phone": s.phone,
            "student_id": s.student_id,
            "birthday": s.birthday.isoformat() if s.birthday else None,
            "profile_pic": signed_media_url(s.profile_pic, context.tahfiz_id),
            "status": s.status.value,
            "registration_date": s.registration_date.isoformat() if s.registration_date else None,
            "sort_order": s.sort_order,
            "warnings": [
                {"id": w.id, "reason": w.reason, "warning_number": w.warning_number, "sent": w.sent, "sent_at": w.sent_at.isoformat() if w.sent_at else None, "created_at": w.created_at.isoformat()}
                for w in s.warnings
            ],
            "sheikh": {"id": s.sheikh.id, "name": s.sheikh.name} if s.sheikh else None,
            "parent_phones": [
                {"id": p.id, "phone_number": p.phone_number, "parent_type": p.parent_type.value, "name": p.name}
                for p in s.parent_phones
            ],
            "excused_weekdays": ew_map.get(s.id, []),
            "categories": serialize_student_categories(s),
            "category_ids": [item["id"] for item in serialize_student_categories(s)],
            "custom_field_values": custom_values_by_student.get(s.id, {}),
        }
        for s in students
    ]


@router.get("/students/{student_id}/profile")
async def student_profile(
    student_id: int,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    student = await db.scalar(
        select(Student)
        .options(
            selectinload(Student.sheikh),
            selectinload(Student.parent_phones),
            selectinload(Student.category_memberships).selectinload(StudentCategoryMembership.category),
            selectinload(Student.warnings),
            selectinload(Student.excused_weekdays),
            selectinload(Student.excused_periods),
        )
        .where(
            Student.id == student_id,
            student_scope_clause(context),
        )
    )
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    attendance_rows = (await db.execute(
        select(Attendance.status, func.count(Attendance.id))
        .where(
            Attendance.student_id == student.id,
            Attendance.tahfiz_id == context.tahfiz_id,
        )
        .group_by(Attendance.status)
    )).all()
    attendance_counts = {status: count for status, count in attendance_rows}
    progress_count, average_quality = (await db.execute(
        select(
            func.count(QuranProgressEntry.id),
            func.coalesce(func.avg(QuranProgressEntry.quality_score), 0),
        ).where(
            QuranProgressEntry.student_id == student.id,
            QuranProgressEntry.tahfiz_id == context.tahfiz_id,
        )
    )).one()
    active_goals = int(await db.scalar(
        select(func.count(StudentGoal.id)).where(
            StudentGoal.student_id == student.id,
            StudentGoal.tahfiz_id == context.tahfiz_id,
            StudentGoal.status == "active",
        )
    ) or 0)
    custom_value_rows = (await db.execute(select(StudentCustomFieldValue).where(
        StudentCustomFieldValue.tahfiz_id == context.tahfiz_id,
        StudentCustomFieldValue.student_id == student.id,
    ))).scalars().all()

    return {
        "id": student.id,
        "name": student.name,
        "phone": student.phone,
        "student_id": student.student_id,
        "birthday": student.birthday.isoformat() if student.birthday else None,
        "profile_pic": signed_media_url(student.profile_pic, context.tahfiz_id),
        "status": student.status.value,
        "registration_date": student.registration_date.isoformat() if student.registration_date else None,
        "sort_order": student.sort_order,
        "sheikh": {
            "id": student.sheikh.id,
            "name": student.sheikh.name,
        } if student.sheikh else None,
        "parent_phones": [
            {
                "id": phone.id,
                "phone_number": phone.phone_number,
                "parent_type": phone.parent_type.value,
                "name": phone.name,
            }
            for phone in student.parent_phones
        ],
        "categories": serialize_student_categories(student),
        "category_ids": [item["id"] for item in serialize_student_categories(student)],
        "custom_field_values": {str(row.field_id): row.value for row in custom_value_rows},
        "excused_weekdays": [
            {"id": row.id, "weekday": row.weekday, "note": row.note}
            for row in sorted(student.excused_weekdays, key=lambda row: row.weekday)
        ],
        "excused_periods": [
            serialize_excused_period(row)
            for row in sorted(student.excused_periods, key=lambda row: (row.start_date, row.id), reverse=True)
        ],
        "warnings": [
            {
                "id": warning.id,
                "reason": warning.reason,
                "warning_number": warning.warning_number,
                "sent": warning.sent,
                "sent_at": warning.sent_at.isoformat() if warning.sent_at else None,
                "created_at": warning.created_at.isoformat(),
            }
            for warning in student.warnings
        ],
        "attendance": {
            "total": sum(attendance_counts.values()),
            "present": attendance_counts.get(present_status_option(context.tahfiz), 0),
            "present_status": present_status_option(context.tahfiz),
            "absent": attendance_counts.get("غياب", 0),
            "excused": attendance_counts.get("غياب بعذر", 0),
            "not_applicable": attendance_counts.get("لا ينطبق", 0),
            "streak": await attendance_status_streak(db, context.tahfiz, student.id),
            "streak_limit": context.tahfiz.excused_absence_streak_limit,
            "streak_status": attendance_streak_status_option(context.tahfiz),
            "streak_alert_enabled": context.tahfiz.attendance_streak_alert_enabled,
        },
        "progress": {
            "enabled": context.tahfiz.progress_tracking_enabled,
            "entries": int(progress_count),
            "average_quality": round(float(average_quality), 1),
            "active_goals": active_goals,
        },
        "can_manage": context.effective_role in (UserRole.admin, UserRole.super_admin),
    }


@router.post("/students")
async def create_student(
    body: CreateStudentRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    if body.sheikh_id is not None:
        sheikh = await db.scalar(select(Sheikh).where(Sheikh.id == body.sheikh_id, Sheikh.tahfiz_id == context.tahfiz_id))
        if not sheikh:
            raise HTTPException(status_code=404, detail="Sheikh not found")
    student = Student(
        name=body.name,
        phone=body.phone,
        student_id=body.student_id,
        birthday=body.birthday,
        status=StudentStatus(body.status),
        registration_date=body.registration_date or date.today(),
        sheikh_id=body.sheikh_id,
        tahfiz_id=context.tahfiz_id,
    )
    db.add(student)
    await db.flush()
    await set_student_categories(db, context.tahfiz_id, student.id, body.category_ids)
    await apply_student_custom_field_values(db, context, student.id, body.custom_field_values)

    for pp in body.parent_phones:
        if pp.parent_type not in [t.value for t in ParentType]:
            raise HTTPException(status_code=400, detail=f"Invalid parent type: {pp.parent_type}")
        parent_phone = ParentPhone(
            student_id=student.id,
            phone_number=pp.phone_number,
            parent_type=ParentType(pp.parent_type),
            name=pp.name,
        )
        db.add(parent_phone)

    if context.tahfiz.subscriptions_enabled and student.status == StudentStatus.enrolled:
        await ensure_current_subscription_records(db, context)

    await db.commit()
    await db.refresh(student)
    return {"id": student.id, "name": student.name}


@router.put("/students/{student_id}")
async def update_student(
    student_id: int,
    body: UpdateStudentRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    result = await db.execute(
        select(Student)
        .options(
            selectinload(Student.parent_phones),
            selectinload(Student.category_memberships),
        )
        .where(Student.id == student_id, Student.tahfiz_id == context.tahfiz_id)
    )
    student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    if body.name is not None:
        student.name = body.name
    if body.phone is not None:
        student.phone = body.phone
    if body.student_id is not None:
        student.student_id = body.student_id
    if body.birthday is not None:
        student.birthday = body.birthday
    if body.profile_pic is not None:
        clean_profile_pic = body.profile_pic.split("?", 1)[0]
        student.profile_pic = local_upload_name(clean_profile_pic) or body.profile_pic
    if body.status is not None:
        student.status = StudentStatus(body.status)
    if body.registration_date is not None:
        student.registration_date = body.registration_date
    if body.sheikh_id is not None:
        sheikh = await db.scalar(select(Sheikh).where(Sheikh.id == body.sheikh_id, Sheikh.tahfiz_id == context.tahfiz_id))
        if not sheikh:
            raise HTTPException(status_code=404, detail="Sheikh not found")
        student.sheikh_id = body.sheikh_id

    if body.parent_phones is not None:
        await db.execute(sa_delete(ParentPhone).where(ParentPhone.student_id == student_id))
        for pp in body.parent_phones:
            if pp.parent_type not in [t.value for t in ParentType]:
                raise HTTPException(status_code=400, detail=f"Invalid parent type: {pp.parent_type}")
            parent_phone = ParentPhone(
                student_id=student_id,
                phone_number=pp.phone_number,
                parent_type=ParentType(pp.parent_type),
                name=pp.name,
            )
            db.add(parent_phone)

    if body.category_ids is not None:
        await set_student_categories(db, context.tahfiz_id, student_id, body.category_ids)
    if body.custom_field_values is not None:
        await apply_student_custom_field_values(db, context, student_id, body.custom_field_values)

    if context.tahfiz.subscriptions_enabled and student.status == StudentStatus.enrolled:
        await ensure_current_subscription_records(db, context)

    await db.commit()
    return {"id": student.id, "name": student.name}


@router.delete("/students/{student_id}")
async def delete_student(
    student_id: int,
    delete_sessions: bool = False,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    result = await db.execute(
        select(Student)
        .options(
            selectinload(Student.attendance_records),
            selectinload(Student.excused_periods),
        )
        .where(Student.id == student_id, Student.tahfiz_id == context.tahfiz_id)
    )
    student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    await delete_student_entity(
        db, student, context.tahfiz_id, delete_attendance=delete_sessions
    )

    db.add(AuditLog(
        actor_user_id=context.user.id,
        tahfiz_id=context.tahfiz_id,
        action="student.deleted",
        details=f"student={student.id}; name={student.name}; delete_attendance={delete_sessions}",
    ))
    await db.commit()
    return {"message": "تم حذف الطالب"}


@router.post("/students/{student_id}/move-sheikh", response_model=MoveStudentResponse)
async def move_student_sheikh(
    student_id: int,
    body: MoveStudentRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    result = await db.execute(
        select(Student)
        .where(
            Student.id == student_id,
            Student.tahfiz_id == context.tahfiz_id,
        )
        .with_for_update()
    )
    student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    if student.sheikh_id != body.expected_current_sheikh_id:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "student_sheikh_changed",
                "message": "تغير الشيخ الحالي للطالب. حدّث البيانات ثم أعد المحاولة.",
                "current_sheikh_id": student.sheikh_id,
            },
        )

    if student.sheikh_id == body.sheikh_id:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "student_already_assigned",
                "message": "الطالب بالفعل تحت هذا الشيخ",
            },
        )

    result = await db.execute(
        select(Sheikh)
        .where(
            Sheikh.id == body.sheikh_id,
            Sheikh.tahfiz_id == context.tahfiz_id,
        )
        .with_for_update()
    )
    destination_sheikh = result.scalar_one_or_none()
    if not destination_sheikh:
        raise HTTPException(status_code=404, detail="Sheikh not found")

    source_sheikh_id = student.sheikh_id
    student.sheikh_id = body.sheikh_id
    student.sort_order = 0
    db.add(AuditLog(
        actor_user_id=context.user.id,
        tahfiz_id=context.tahfiz_id,
        action="student.sheikh_changed",
        details=(
            f"student={student.id}; from_sheikh={source_sheikh_id}; "
            f"to_sheikh={destination_sheikh.id}"
        ),
    ))
    await db.commit()
    return {
        "message": f"تم نقل الطالب إلى الشيخ {destination_sheikh.name}",
        "student_id": student.id,
        "from_sheikh_id": source_sheikh_id,
        "destination_sheikh": {
            "id": destination_sheikh.id,
            "name": destination_sheikh.name,
        },
    }


@router.post("/students/{student_id}/warnings")
async def add_warning(
    student_id: int,
    body: CreateWarningRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    result = await db.execute(select(Student).where(Student.id == student_id, Student.tahfiz_id == context.tahfiz_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Student not found")

    count_result = await db.execute(
        select(StudentWarning).where(StudentWarning.student_id == student_id)
    )
    existing = count_result.scalars().all()
    warning_number = len(existing) + 1

    warning = StudentWarning(student_id=student_id, reason=body.reason, warning_number=warning_number)
    db.add(warning)
    await db.commit()
    await db.refresh(warning)
    return {"id": warning.id, "reason": warning.reason, "warning_number": warning.warning_number, "sent": warning.sent, "sent_at": warning.sent_at.isoformat() if warning.sent_at else None, "created_at": warning.created_at.isoformat()}


@router.post("/students/{student_id}/warnings/send")
async def add_and_send_warning(
    student_id: int,
    body: SendStudentWarningRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    absent_dates = [d.strip() for d in body.absent_dates if d.strip()]
    if not absent_dates:
        raise HTTPException(status_code=400, detail="اختر جلسة واحدة على الأقل")

    result = await db.execute(
        select(Student)
        .options(selectinload(Student.sheikh))
        .where(Student.id == student_id, Student.tahfiz_id == context.tahfiz_id)
    )
    student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    sheikh = student.sheikh
    if not sheikh:
        raise HTTPException(status_code=400, detail="الطالب غير مرتبط بشيخ")
    if not sheikh.whatsapp_group_id:
        raise HTTPException(status_code=400, detail="شيخ الطالب ليس لديه معرف مجموعة واتساب")

    count_result = await db.execute(
        select(StudentWarning).where(StudentWarning.student_id == student_id)
    )
    warning_number = len(count_result.scalars().all()) + 1

    tahfiz = await db.get(Tahfiz, context.tahfiz_id)
    max_warnings = tahfiz.max_warnings
    remaining = max(max_warnings - warning_number, 0)
    reason = "\n".join(f"* {d}" for d in absent_dates)
    message = build_warning_message(student.name, warning_number, reason, remaining)

    warning = StudentWarning(
        student_id=student_id,
        reason=reason,
        warning_number=warning_number,
    )
    db.add(warning)

    try:
        await send_whatsend_group_message(tahfiz, sheikh.whatsapp_group_id, message)
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=502, detail=f"فشل إرسال الإنذار: {whatsend_error(e)}")

    warning.sent = True
    warning.sent_at = utcnow()
    await db.commit()
    await db.refresh(warning)
    return {
        "id": warning.id,
        "reason": warning.reason,
        "warning_number": warning.warning_number,
        "sent": warning.sent,
        "sent_at": warning.sent_at.isoformat() if warning.sent_at else None,
        "created_at": warning.created_at.isoformat(),
        "message": message,
    }


@router.get("/students/{student_id}/warnings/preview")
async def get_warning_preview_numbers(
    student_id: int,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    result = await db.execute(
        select(Student).options(selectinload(Student.sheikh)).where(Student.id == student_id, Student.tahfiz_id == context.tahfiz_id)
    )
    student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    count_result = await db.execute(
        select(func.count(StudentWarning.id)).where(StudentWarning.student_id == student_id)
    )
    next_warning_number = (count_result.scalar_one() or 0) + 1

    tahfiz = await db.get(Tahfiz, context.tahfiz_id)
    max_warnings = tahfiz.max_warnings

    return {
        "next_warning_number": next_warning_number,
        "remaining_warnings": max(max_warnings - next_warning_number, 0),
    }


@router.put("/warnings/{warning_id}")
async def update_warning(
    warning_id: int,
    body: CreateWarningRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    result = await db.execute(
        select(StudentWarning).where(
            StudentWarning.id == warning_id,
            StudentWarning.student.has(Student.tahfiz_id == context.tahfiz_id),
        )
    )
    warning = result.scalar_one_or_none()
    if not warning:
        raise HTTPException(status_code=404, detail="Warning not found")

    warning.reason = body.reason
    await db.commit()
    await db.refresh(warning)
    return {"id": warning.id, "reason": warning.reason, "warning_number": warning.warning_number, "sent": warning.sent, "sent_at": warning.sent_at.isoformat() if warning.sent_at else None, "created_at": warning.created_at.isoformat()}


@router.delete("/warnings/{warning_id}")
async def delete_warning(
    warning_id: int,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    result = await db.execute(
        select(StudentWarning).where(
            StudentWarning.id == warning_id,
            StudentWarning.student.has(Student.tahfiz_id == context.tahfiz_id),
        )
    )
    warning = result.scalar_one_or_none()
    if not warning:
        raise HTTPException(status_code=404, detail="Warning not found")

    await db.delete(warning)
    await db.commit()
    return {"message": "Warning deleted"}


@router.get("/warnings")
async def list_warnings(
    sheikh_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    query = (
        select(StudentWarning)
        .options(selectinload(StudentWarning.student).selectinload(Student.sheikh))
        .where(StudentWarning.student.has(Student.tahfiz_id == context.tahfiz_id))
        .order_by(StudentWarning.created_at.desc())
    )
    if sheikh_id is not None:
        query = query.where(StudentWarning.student.has(Student.sheikh_id == sheikh_id))
    result = await db.execute(query)
    warnings = result.scalars().all()
    return [
        {
            "id": w.id,
            "student_id": w.student_id,
            "student_name": w.student.name,
            "sheikh_id": w.student.sheikh.id if w.student.sheikh else None,
            "sheikh_name": w.student.sheikh.name if w.student.sheikh else None,
            "reason": w.reason,
            "warning_number": w.warning_number,
            "sent": w.sent,
            "sent_at": w.sent_at.isoformat() if w.sent_at else None,
            "created_at": w.created_at.isoformat(),
        }
        for w in warnings
    ]


@router.post("/warnings/send")
async def send_warnings(
    body: SendWarningsRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    tahfiz = await db.get(Tahfiz, context.tahfiz_id)
    results: list[dict] = []
    for wid in body.warning_ids:
        result = await db.execute(
            select(StudentWarning)
            .options(selectinload(StudentWarning.student).selectinload(Student.sheikh))
            .where(
                StudentWarning.id == wid,
                StudentWarning.student.has(Student.tahfiz_id == context.tahfiz_id),
            )
        )
        warning = result.scalar_one_or_none()
        if not warning:
            results.append({"warning_id": wid, "success": False, "error": "Warning not found"})
            continue

        student = warning.student
        sheikh = student.sheikh
        if not sheikh or not sheikh.whatsapp_group_id:
            results.append({"warning_id": wid, "success": False, "error": "شيخ الطالب ليس لديه معرف مجموعة واتساب"})
            continue

        max_w = tahfiz.max_warnings
        remaining = max_w - warning.warning_number

        message = build_warning_message(student.name, warning.warning_number, warning.reason, remaining)

        try:
            await send_whatsend_group_message(tahfiz, sheikh.whatsapp_group_id, message)
        except Exception as e:
            results.append({"warning_id": wid, "success": False, "error": whatsend_error(e)})
            continue

        warning.sent = True
        warning.sent_at = utcnow()
        await db.commit()
        results.append({"warning_id": wid, "success": True})

    return {"results": results}


@router.get("/students/{student_id}/excused-weekdays")
async def get_excused_weekdays(
    student_id: int,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    student = await db.scalar(select(Student).where(Student.id == student_id, Student.tahfiz_id == context.tahfiz_id))
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    result = await db.execute(
        select(ExcusedWeekday).where(ExcusedWeekday.student_id == student_id)
    )
    return [{"id": e.id, "weekday": e.weekday, "note": e.note} for e in result.scalars().all()]


@router.put("/students/{student_id}/excused-weekdays")
async def update_excused_weekdays(
    student_id: int,
    body: UpdateExcusedWeekdaysRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    result = await db.execute(select(Student).where(Student.id == student_id, Student.tahfiz_id == context.tahfiz_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Student not found")

    await db.execute(sa_delete(ExcusedWeekday).where(ExcusedWeekday.student_id == student_id))
    saved = []
    for item in body.weekdays:
        weekday = item if isinstance(item, int) else item.weekday
        note = None if isinstance(item, int) else item.note
        clean_note = note.strip() if note else None
        db.add(ExcusedWeekday(student_id=student_id, weekday=weekday, note=clean_note))
        saved.append({"weekday": weekday, "note": clean_note})
    await db.commit()
    return {"weekdays": saved}


@router.get("/students/{student_id}/excused-periods")
async def get_excused_periods(
    student_id: int,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
) -> list[ExcusedPeriodOut]:
    student = await db.scalar(select(Student.id).where(
        Student.id == student_id,
        student_scope_clause(context),
    ))
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    periods = (await db.execute(
        select(StudentExcusedPeriod).where(
            StudentExcusedPeriod.student_id == student_id,
            StudentExcusedPeriod.tahfiz_id == context.tahfiz_id,
        ).order_by(StudentExcusedPeriod.start_date.desc(), StudentExcusedPeriod.id.desc())
    )).scalars().all()
    return [serialize_excused_period(period) for period in periods]


@router.post("/students/{student_id}/excused-periods", status_code=201)
async def create_excused_period(
    student_id: int,
    body: CreateExcusedPeriodRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
) -> ExcusedPeriodOut:
    student = await db.scalar(select(Student).where(
        Student.id == student_id,
        Student.tahfiz_id == context.tahfiz_id,
    ))
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    await ensure_no_excused_period_overlap(
        db, context.tahfiz_id, student_id, body.start_date, body.end_date
    )
    now = utcnow()
    period = StudentExcusedPeriod(
        student_id=student_id,
        tahfiz_id=context.tahfiz_id,
        start_date=body.start_date,
        end_date=body.end_date,
        reason=body.reason,
        created_by_id=context.user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(period)
    await db.flush()
    db.add(AuditLog(
        actor_user_id=context.user.id,
        tahfiz_id=context.tahfiz_id,
        action="student.excused_period_created",
        details=f"student={student_id}; period={period.id}; start={body.start_date}; end={body.end_date}; reason={body.reason}",
    ))
    await db.commit()
    await db.refresh(period)
    return serialize_excused_period(period)


@router.put("/students/{student_id}/excused-periods/{period_id}")
async def update_excused_period(
    student_id: int,
    period_id: int,
    body: UpdateExcusedPeriodRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
) -> ExcusedPeriodOut:
    period = await db.scalar(select(StudentExcusedPeriod).where(
        StudentExcusedPeriod.id == period_id,
        StudentExcusedPeriod.student_id == student_id,
        StudentExcusedPeriod.tahfiz_id == context.tahfiz_id,
    ))
    if not period:
        raise HTTPException(status_code=404, detail="Excused period not found")
    if period.cancelled_at is not None:
        raise HTTPException(status_code=409, detail={"code": "excused_period_cancelled"})
    await ensure_no_excused_period_overlap(
        db, context.tahfiz_id, student_id, body.start_date, body.end_date, exclude_id=period.id
    )
    period.start_date = body.start_date
    period.end_date = body.end_date
    period.reason = body.reason
    period.updated_at = utcnow()
    db.add(AuditLog(
        actor_user_id=context.user.id,
        tahfiz_id=context.tahfiz_id,
        action="student.excused_period_updated",
        details=f"student={student_id}; period={period.id}; start={body.start_date}; end={body.end_date}; reason={body.reason}",
    ))
    await db.commit()
    return serialize_excused_period(period)


@router.post("/students/{student_id}/excused-periods/{period_id}/cancel")
async def cancel_excused_period(
    student_id: int,
    period_id: int,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
) -> ExcusedPeriodOut:
    period = await db.scalar(select(StudentExcusedPeriod).where(
        StudentExcusedPeriod.id == period_id,
        StudentExcusedPeriod.student_id == student_id,
        StudentExcusedPeriod.tahfiz_id == context.tahfiz_id,
    ))
    if not period:
        raise HTTPException(status_code=404, detail="Excused period not found")
    if period.cancelled_at is None:
        period.cancelled_at = utcnow()
        period.cancelled_by_id = context.user.id
        period.updated_at = period.cancelled_at
        db.add(AuditLog(
            actor_user_id=context.user.id,
            tahfiz_id=context.tahfiz_id,
            action="student.excused_period_cancelled",
            details=f"student={student_id}; period={period.id}",
        ))
        await db.commit()
    return serialize_excused_period(period)


@router.post("/students/{student_id}/excused-periods/{period_id}/early-return")
async def end_excused_period_early(
    student_id: int,
    period_id: int,
    body: EarlyReturnRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
) -> ExcusedPeriodOut:
    period = await db.scalar(select(StudentExcusedPeriod).where(
        StudentExcusedPeriod.id == period_id,
        StudentExcusedPeriod.student_id == student_id,
        StudentExcusedPeriod.tahfiz_id == context.tahfiz_id,
    ))
    if not period:
        raise HTTPException(status_code=404, detail="Excused period not found")
    if period.cancelled_at is not None:
        raise HTTPException(status_code=409, detail={"code": "excused_period_cancelled"})
    if body.end_date < period.start_date or body.end_date >= period.end_date:
        raise HTTPException(status_code=400, detail={"code": "invalid_early_return_date"})
    previous_end = period.end_date
    period.end_date = body.end_date
    period.updated_at = utcnow()
    db.add(AuditLog(
        actor_user_id=context.user.id,
        tahfiz_id=context.tahfiz_id,
        action="student.excused_period_ended_early",
        details=f"student={student_id}; period={period.id}; previous_end={previous_end}; end={body.end_date}",
    ))
    await db.commit()
    return serialize_excused_period(period)


@router.post("/students/{student_id}/upload-pic")
async def upload_student_pic(
    student_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    result = await db.execute(select(Student).where(Student.id == student_id, Student.tahfiz_id == context.tahfiz_id))
    student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    if file.content_type and not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Uploaded file must be an image.")

    content = await file.read()
    compressed = compress_profile_image(content)
    tenant_dir = UPLOAD_DIR / str(context.tahfiz_id)
    tenant_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{context.tahfiz_id}/{uuid.uuid4()}.webp"
    filepath = UPLOAD_DIR / filename
    with open(filepath, "wb") as f:
        f.write(compressed)

    delete_upload(student.profile_pic)
    student.profile_pic = filename
    await db.commit()
    return {"url": signed_media_url(filename, context.tahfiz_id)}


# ─── Tahfiz settings ─────────────────────────────────────────────────────────


def serialize_tahfiz(tahfiz: Tahfiz) -> dict:
    try:
        session_name_options = json.loads(tahfiz.session_name_options or "[]")
    except (TypeError, json.JSONDecodeError):
        session_name_options = []
    if not isinstance(session_name_options, list):
        session_name_options = []
    return {
        "id": tahfiz.id,
        "name": tahfiz.name,
        "description": tahfiz.description,
        "contact_phone": tahfiz.contact_phone,
        "status": tahfiz.status.value,
        "max_warnings": tahfiz.max_warnings,
        "week_start_day": tahfiz.week_start_day,
        "month_start_day": tahfiz.month_start_day,
        "attendance_statuses": attendance_status_options(tahfiz),
        "attendance_status_colors": attendance_status_color_options(tahfiz),
        "excel_export_templates": excel_export_template_options(tahfiz),
        "excused_absence_streak_limit": tahfiz.excused_absence_streak_limit,
        "excused_absence_reset_statuses": excused_absence_reset_status_options(tahfiz),
        "attendance_streak_alert_enabled": tahfiz.attendance_streak_alert_enabled,
        "attendance_sheikh_selection_enabled": tahfiz.attendance_sheikh_selection_enabled,
        "restrict_sheikh_student_access": tahfiz.restrict_sheikh_student_access is not False,
        "attendance_streak_status": attendance_streak_status_option(tahfiz),
        "attendance_streak_limit": tahfiz.excused_absence_streak_limit,
        "attendance_streak_reset_statuses": excused_absence_reset_status_options(tahfiz),
        "present_status": present_status_option(tahfiz),
        "absent_status": absent_status_option(tahfiz),
        "multiple_sessions_per_day_enabled": tahfiz.multiple_sessions_per_day_enabled is True,
        "session_name_options": [name for name in session_name_options if isinstance(name, str) and name.strip()],
        "sheikh_custom_fields_enabled": tahfiz.sheikh_custom_fields_enabled is True,
        "whatsend_enabled": tahfiz.whatsend_enabled,
        "whatsend_api_url": tahfiz.whatsend_api_url,
        "whatsend_groups_url": tahfiz.whatsend_groups_url,
        "whatsend_api_key_configured": bool(tahfiz.whatsend_api_key_encrypted or settings.WHATSEND_API_KEY),
        "progress_tracking_enabled": tahfiz.progress_tracking_enabled,
        "subscriptions_enabled": tahfiz.subscriptions_enabled,
        "subscription_default_fee_minor": tahfiz.subscription_default_fee_minor,
        "subscription_currency": tahfiz.subscription_currency,
        "expense_categories": expense_category_options(tahfiz),
    }


@router.get("/tahfiz/settings")
async def get_tahfiz_settings(context: TenantContext = Depends(require_tenant_admin)):
    return serialize_tahfiz(context.tahfiz)


@router.put("/tahfiz/settings")
async def update_tahfiz_settings(
    body: UpdateTahfizSettingsRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    tahfiz = context.tahfiz
    changed_fields: list[str] = []
    previous_statuses = attendance_status_options(tahfiz)
    whatsend_enabled = body.whatsend_enabled if body.whatsend_enabled is not None else tahfiz.whatsend_enabled
    for field in ("name", "description", "contact_phone", "max_warnings", "whatsend_api_url", "whatsend_groups_url"):
        value = getattr(body, field)
        if value is not None:
            normalized = value.strip() if isinstance(value, str) else value
            if field in {"whatsend_api_url", "whatsend_groups_url"} and normalized:
                try:
                    await validate_whatsend_setting_url(whatsend_enabled, normalized)
                except (OSError, ValueError) as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
            if getattr(tahfiz, field) != normalized:
                setattr(tahfiz, field, normalized)
                changed_fields.append(field)
    if body.week_start_day is not None:
        if not 0 <= body.week_start_day <= 6:
            raise HTTPException(status_code=400, detail="Invalid week start day")
        if tahfiz.week_start_day != body.week_start_day:
            tahfiz.week_start_day = body.week_start_day
            changed_fields.append("week_start_day")
    if body.month_start_day is not None:
        if not 1 <= body.month_start_day <= 28:
            raise HTTPException(status_code=400, detail="Invalid month start day")
        if tahfiz.month_start_day != body.month_start_day:
            subscription_count = await db.scalar(select(func.count()).select_from(StudentSubscription).where(
                StudentSubscription.tahfiz_id == context.tahfiz_id,
            ))
            expense_count = await db.scalar(select(func.count()).select_from(Expense).where(
                Expense.tahfiz_id == context.tahfiz_id,
            ))
            if subscription_count or expense_count:
                raise HTTPException(status_code=409, detail={
                    "code": "subscription_month_start_locked",
                    "message": "Month start day cannot change after subscription records exist",
                })
            tahfiz.month_start_day = body.month_start_day
            changed_fields.append("month_start_day")
    if body.attendance_statuses is not None:
        normalized_statuses = list(dict.fromkeys(status.strip() for status in body.attendance_statuses if status.strip()))
        if not normalized_statuses:
            raise HTTPException(status_code=400, detail="At least one attendance status is required")
        if len(normalized_statuses) > 20 or any(len(status) > 50 for status in normalized_statuses):
            raise HTTPException(status_code=400, detail="Invalid attendance statuses")
        serialized_statuses = json.dumps(normalized_statuses, ensure_ascii=False)
        if tahfiz.attendance_statuses != serialized_statuses:
            tahfiz.attendance_statuses = serialized_statuses
            changed_fields.append("attendance_statuses")
    final_statuses = attendance_status_options(tahfiz)
    if body.attendance_status_renames:
        normalized_renames = {
            source.strip(): target.strip()
            for source, target in body.attendance_status_renames.items()
            if source.strip() != target.strip()
        }
        if (
            len(normalized_renames) > 20
            or any(source not in previous_statuses for source in normalized_renames)
            or any(not target or len(target) > 50 or target not in final_statuses for target in normalized_renames.values())
        ):
            raise HTTPException(status_code=400, detail="Invalid attendance status renames")
        for source, target in normalized_renames.items():
            await db.execute(
                sa_update(Attendance)
                .where(
                    Attendance.tahfiz_id == context.tahfiz_id,
                    Attendance.status == source,
                )
                .values(status=target, revision=Attendance.revision + 1, updated_at=utcnow())
            )
            if (tahfiz.present_status or "").strip() == source:
                tahfiz.present_status = target
                changed_fields.append("present_status")
            if (tahfiz.absent_status or "").strip() == source:
                tahfiz.absent_status = target
                changed_fields.append("absent_status")
        if normalized_renames:
            changed_fields.append("attendance_status_renames")
    if body.attendance_streak_alert_enabled is not None and tahfiz.attendance_streak_alert_enabled != body.attendance_streak_alert_enabled:
        tahfiz.attendance_streak_alert_enabled = body.attendance_streak_alert_enabled
        changed_fields.append("attendance_streak_alert_enabled")
    if body.attendance_sheikh_selection_enabled is not None and tahfiz.attendance_sheikh_selection_enabled != body.attendance_sheikh_selection_enabled:
        tahfiz.attendance_sheikh_selection_enabled = body.attendance_sheikh_selection_enabled
        changed_fields.append("attendance_sheikh_selection_enabled")
    if body.restrict_sheikh_student_access is not None and tahfiz.restrict_sheikh_student_access != body.restrict_sheikh_student_access:
        tahfiz.restrict_sheikh_student_access = body.restrict_sheikh_student_access
        changed_fields.append("restrict_sheikh_student_access")
    if body.attendance_streak_status is not None:
        tracked_status = body.attendance_streak_status.strip()
        if tracked_status not in final_statuses:
            raise HTTPException(status_code=400, detail="Tracked attendance status must be configured")
        if tahfiz.attendance_streak_status != tracked_status:
            tahfiz.attendance_streak_status = tracked_status
            changed_fields.append("attendance_streak_status")
    if body.present_status is not None:
        requested_present_status = body.present_status.strip()
        if requested_present_status not in final_statuses:
            raise HTTPException(status_code=400, detail="Present attendance status must be configured")
        if (tahfiz.present_status or "").strip() != requested_present_status:
            tahfiz.present_status = requested_present_status
            changed_fields.append("present_status")
    if body.absent_status is not None:
        requested_absent_status = body.absent_status.strip()
        if requested_absent_status not in final_statuses:
            raise HTTPException(status_code=400, detail="Absent attendance status must be configured")
        if (tahfiz.absent_status or "").strip() != requested_absent_status:
            tahfiz.absent_status = requested_absent_status
            changed_fields.append("absent_status")
    if (
        body.multiple_sessions_per_day_enabled is not None
        and tahfiz.multiple_sessions_per_day_enabled != body.multiple_sessions_per_day_enabled
    ):
        tahfiz.multiple_sessions_per_day_enabled = body.multiple_sessions_per_day_enabled
        changed_fields.append("multiple_sessions_per_day_enabled")
    if body.session_name_options is not None:
        normalized_session_names = list(dict.fromkeys(name.strip() for name in body.session_name_options if name.strip()))
        if len(normalized_session_names) > 20 or any(len(name) > 100 for name in normalized_session_names):
            raise HTTPException(status_code=400, detail="Invalid session name options")
        serialized_session_names = json.dumps(normalized_session_names, ensure_ascii=False)
        if tahfiz.session_name_options != serialized_session_names:
            tahfiz.session_name_options = serialized_session_names
            changed_fields.append("session_name_options")
    if body.sheikh_custom_fields_enabled is not None and tahfiz.sheikh_custom_fields_enabled != body.sheikh_custom_fields_enabled:
        tahfiz.sheikh_custom_fields_enabled = body.sheikh_custom_fields_enabled
        changed_fields.append("sheikh_custom_fields_enabled")
    requested_colors = body.attendance_status_colors or attendance_status_color_options(tahfiz)
    invalid_color = next(
        (color for color in requested_colors.values() if color not in ATTENDANCE_STATUS_COLOR_KEYS),
        None,
    )
    if invalid_color:
        raise HTTPException(status_code=400, detail="Invalid attendance status color")
    normalized_colors = {
        status: requested_colors.get(
            status,
            attendance_status_color_options(tahfiz).get(status, "violet"),
        )
        for status in final_statuses
    }
    serialized_colors = json.dumps(normalized_colors, ensure_ascii=False, sort_keys=True)
    if tahfiz.attendance_status_colors != serialized_colors:
        tahfiz.attendance_status_colors = serialized_colors
        changed_fields.append("attendance_status_colors")
    if body.excel_export_templates is not None:
        requested_templates = {
            key: template.model_dump()
            for key, template in body.excel_export_templates.items()
        }
        if set(requested_templates) != set(DEFAULT_EXCEL_EXPORT_TEMPLATES):
            raise HTTPException(status_code=400, detail="Invalid Excel export templates")
        normalized_templates: dict[str, dict] = {}
        for template_key, template in requested_templates.items():
            header_font_family = template["header_font_family"].strip()
            cell_font_family = template["cell_font_family"].strip()
            date_font_family = template["date_font_family"].strip()
            if not header_font_family or not cell_font_family or not date_font_family:
                raise HTTPException(status_code=400, detail="Invalid Excel font")
            allowed_standard_ids = {
                column["id"]
                for column in DEFAULT_EXCEL_EXPORT_TEMPLATES[template_key]["columns"]
            }
            if template_key == "statistics":
                allowed_standard_ids.update({"present", "excused", "absent", "notApplicable"})
            seen_ids: set[str] = set()
            normalized_columns: list[dict] = []
            for column in template["columns"]:
                column_id = column["id"].strip()
                label = column["label"].strip()
                is_custom = column["custom"]
                semantic_subcolumns = template_key == "attendance" and column_id in {"memorization", "revision"}
                if (
                    not label
                    or column_id in seen_ids
                    or (is_custom and not column_id.startswith("custom_"))
                    or (not is_custom and column_id not in allowed_standard_ids)
                    or (column["subcolumns"] and not is_custom and not semantic_subcolumns)
                    or len(column["subcolumns"]) == 1
                ):
                    raise HTTPException(status_code=400, detail="Invalid Excel export template columns")
                subcolumn_ids: set[str] = set()
                normalized_subcolumns: list[dict] = []
                for subcolumn in column["subcolumns"]:
                    subcolumn_id = subcolumn["id"].strip()
                    subcolumn_label = subcolumn["label"].strip()
                    if not subcolumn_label or subcolumn_id in subcolumn_ids:
                        raise HTTPException(status_code=400, detail="Invalid Excel export template subcolumns")
                    subcolumn_ids.add(subcolumn_id)
                    normalized_subcolumns.append({
                        "id": subcolumn_id,
                        "label": subcolumn_label,
                        "width": subcolumn["width"],
                    })
                seen_ids.add(column_id)
                normalized_columns.append({
                    "id": column_id,
                    "label": label,
                    "enabled": column["enabled"],
                    "custom": is_custom,
                    "width": column["width"],
                    "header_font_size": column["header_font_size"],
                    "show_header": column["show_header"],
                    "subcolumns": normalized_subcolumns,
                })
            if not any(column["enabled"] for column in normalized_columns):
                raise HTTPException(status_code=400, detail="At least one Excel column must be enabled")
            normalized_templates[template_key] = {
                "columns": normalized_columns,
                "header_font_family": header_font_family,
                "header_font_size": template["header_font_size"],
                "header_bold": template["header_bold"],
                "header_background_color": template["header_background_color"].upper(),
                "header_font_color": template["header_font_color"].upper(),
                "cell_font_family": cell_font_family,
                "cell_font_size": template["cell_font_size"],
                "cell_bold": template["cell_bold"],
                "cell_font_color": template["cell_font_color"].upper(),
                "date_font_family": date_font_family,
                "date_font_size": template["date_font_size"],
                "date_bold": template["date_bold"],
                "date_font_color": template["date_font_color"].upper(),
                "attendance_date_format": template["attendance_date_format"],
            }
        serialized_templates = json.dumps(normalized_templates, ensure_ascii=False)
        if tahfiz.excel_export_templates != serialized_templates:
            tahfiz.excel_export_templates = serialized_templates
            changed_fields.append("excel_export_templates")
    if body.expense_categories is not None:
        normalized_categories = [category.model_dump() for category in body.expense_categories]
        category_ids = [category["id"] for category in normalized_categories]
        if len(category_ids) != len(set(category_ids)) or not any(category["enabled"] for category in normalized_categories):
            raise HTTPException(status_code=400, detail={"code": "invalid_expense_categories"})
        serialized_categories = json.dumps(normalized_categories, ensure_ascii=False)
        if tahfiz.expense_categories != serialized_categories:
            tahfiz.expense_categories = serialized_categories
            changed_fields.append("expense_categories")
            db.add(AuditLog(
                actor_user_id=context.user.id,
                tahfiz_id=context.tahfiz_id,
                action="finance.categories_updated",
                details=f"categories={len(normalized_categories)}",
            ))
    requested_limit = body.attendance_streak_limit if body.attendance_streak_limit is not None else body.excused_absence_streak_limit
    if requested_limit is not None:
        if tahfiz.excused_absence_streak_limit != requested_limit:
            tahfiz.excused_absence_streak_limit = requested_limit
            changed_fields.append("attendance_streak_limit")
    reset_statuses = (
        body.attendance_streak_reset_statuses
        if body.attendance_streak_reset_statuses is not None
        else body.excused_absence_reset_statuses
        if body.excused_absence_reset_statuses is not None
        else excused_absence_reset_status_options(tahfiz)
    )
    tracked_status = attendance_streak_status_option(tahfiz)
    normalized_reset_statuses = list(dict.fromkeys(
        status.strip()
        for status in reset_statuses
        if status.strip() in final_statuses and status.strip() != tracked_status
    ))
    serialized_reset_statuses = json.dumps(normalized_reset_statuses, ensure_ascii=False)
    if tahfiz.excused_absence_reset_statuses != serialized_reset_statuses:
        tahfiz.excused_absence_reset_statuses = serialized_reset_statuses
        changed_fields.append("attendance_streak_reset_statuses")
    if body.progress_tracking_enabled is not None and tahfiz.progress_tracking_enabled != body.progress_tracking_enabled:
        tahfiz.progress_tracking_enabled = body.progress_tracking_enabled
        changed_fields.append("progress_tracking_enabled")
    next_subscription_fee = (
        body.subscription_default_fee_minor
        if body.subscription_default_fee_minor is not None
        else tahfiz.subscription_default_fee_minor
    )
    if body.subscriptions_enabled is True and not tahfiz.subscriptions_enabled and next_subscription_fee <= 0:
        raise HTTPException(status_code=400, detail={
            "code": "subscription_default_fee_required",
            "message": "A default monthly fee is required before enabling subscriptions",
        })
    if body.subscription_currency is not None:
        next_subscription_currency = body.subscription_currency.upper()
        if next_subscription_currency != tahfiz.subscription_currency:
            subscription_count = await db.scalar(select(func.count()).select_from(StudentSubscription).where(
                StudentSubscription.tahfiz_id == context.tahfiz_id,
            ))
            expense_count = await db.scalar(select(func.count()).select_from(Expense).where(
                Expense.tahfiz_id == context.tahfiz_id,
            ))
            if subscription_count or expense_count:
                raise HTTPException(status_code=409, detail={
                    "code": "subscription_currency_locked",
                    "message": "Currency cannot change after subscription records exist",
                })
            tahfiz.subscription_currency = next_subscription_currency
            changed_fields.append("subscription_currency")
    if (
        body.subscription_default_fee_minor is not None
        and tahfiz.subscription_default_fee_minor != body.subscription_default_fee_minor
    ):
        tahfiz.subscription_default_fee_minor = body.subscription_default_fee_minor
        changed_fields.append("subscription_default_fee_minor")
    if body.subscriptions_enabled is not None and tahfiz.subscriptions_enabled != body.subscriptions_enabled:
        tahfiz.subscriptions_enabled = body.subscriptions_enabled
        changed_fields.append("subscriptions_enabled")
    if body.whatsend_api_key is not None:
        tahfiz.whatsend_api_key_encrypted = encrypt_secret(body.whatsend_api_key.strip()) if body.whatsend_api_key.strip() else None
        changed_fields.append("whatsend_api_key")
    if body.whatsend_enabled is not None and tahfiz.whatsend_enabled != body.whatsend_enabled:
        tahfiz.whatsend_enabled = body.whatsend_enabled
        changed_fields.append("whatsend_enabled")
    if changed_fields:
        db.add(AuditLog(
            actor_user_id=context.user.id,
            tahfiz_id=context.tahfiz_id,
            action="tahfiz.settings_updated",
            details=f"fields={','.join(changed_fields)}",
        ))
    await db.commit()
    return serialize_tahfiz(tahfiz)


# Cached-client compatibility: the former circle is now the current Tahfiz.
@router.get("/circles")
async def list_circles(context: TenantContext = Depends(require_tenant_admin)):
    return [serialize_tahfiz(context.tahfiz)]


@router.post("/circles")
async def create_circle_compat(context: TenantContext = Depends(require_tenant_admin)):
    raise HTTPException(status_code=409, detail="Each account has one Tahfiz workspace")


@router.put("/circles/{circle_id}")
async def update_circle_compat(
    circle_id: int,
    body: UpdateTahfizSettingsRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    if circle_id != context.tahfiz_id:
        raise HTTPException(status_code=404, detail="Tahfiz not found")
    return await update_tahfiz_settings(body, db, context)


@router.delete("/circles/{circle_id}")
async def delete_circle_compat(circle_id: int, context: TenantContext = Depends(require_tenant_admin)):
    raise HTTPException(status_code=403, detail="Tahfiz workspaces can only be suspended by the platform administrator")


# ─── Users ───────────────────────────────────────────────────────────────────


@router.get("/users")
async def list_users(
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    result = await db.execute(
        select(User, UserTahfizMembership)
        .join(UserTahfizMembership, UserTahfizMembership.user_id == User.id)
        .where(
            UserTahfizMembership.tahfiz_id == context.tahfiz_id,
            UserTahfizMembership.is_active == True,
            User.is_active == True,
        )
    )
    rows = result.all()
    return [
        {
            "id": user.id,
            "username": user.username,
            "role": membership.role.value,
            "sheikh_id": membership.sheikh_id,
        }
        for user, membership in rows
    ]


@router.post("/users")
async def create_user(
    body: CreateUserRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    existing = await db.execute(select(User).where(User.username == body.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already exists")

    if body.role not in (UserRole.admin.value, UserRole.sheikh.value):
        raise HTTPException(status_code=400, detail="Invalid tenant role")
    if body.sheikh_id is not None:
        sheikh = await db.scalar(select(Sheikh).where(Sheikh.id == body.sheikh_id, Sheikh.tahfiz_id == context.tahfiz_id))
        if not sheikh:
            raise HTTPException(status_code=404, detail="Sheikh not found")
    user = User(
        username=body.username,
        password_hash=pwd_context.hash(body.password),
        role=UserRole(body.role),
        sheikh_id=body.sheikh_id,
        tahfiz_id=context.tahfiz_id,
        default_tahfiz_id=context.tahfiz_id,
    )
    db.add(user)
    await db.flush()
    db.add(UserTahfizMembership(
        user_id=user.id,
        tahfiz_id=context.tahfiz_id,
        role=UserRole(body.role),
        sheikh_id=body.sheikh_id,
        is_active=True,
        created_by_id=context.user.id,
    ))
    await db.commit()
    return {"id": user.id, "username": user.username, "role": user.role.value, "sheikh_id": user.sheikh_id}


@router.put("/users/{user_id}")
async def update_user(
    user_id: int,
    body: UpdateUserRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    result = await db.execute(
        select(User, UserTahfizMembership)
        .join(UserTahfizMembership, UserTahfizMembership.user_id == User.id)
        .where(
            User.id == user_id,
            UserTahfizMembership.tahfiz_id == context.tahfiz_id,
            UserTahfizMembership.is_active == True,
        )
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    user, membership = row

    if body.username is not None:
        user.username = body.username
    if body.password is not None:
        user.password_hash = pwd_context.hash(body.password)
        user.auth_version += 1
        await db.execute(
            sa_update(DeviceSession)
            .where(DeviceSession.user_id == user.id, DeviceSession.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )
    if body.role is not None:
        if body.role not in (UserRole.admin.value, UserRole.sheikh.value):
            raise HTTPException(status_code=400, detail="Invalid tenant role")
        if user.id == context.tahfiz.owner_user_id and body.role != UserRole.admin.value:
            raise HTTPException(status_code=409, detail="Transfer ownership before demoting the owner")
        if membership.role == UserRole.admin and body.role != UserRole.admin.value:
            admin_count = await db.scalar(select(func.count(UserTahfizMembership.id)).where(
                UserTahfizMembership.tahfiz_id == context.tahfiz_id,
                UserTahfizMembership.role == UserRole.admin,
                UserTahfizMembership.is_active == True,
            ))
            if (admin_count or 0) <= 1:
                raise HTTPException(status_code=409, detail="A Tahfiz must keep at least one admin")
        membership.role = UserRole(body.role)
        if user.tahfiz_id == context.tahfiz_id:
            user.role = UserRole(body.role)
    if "sheikh_id" in body.model_fields_set:
        if body.sheikh_id is not None:
            sheikh = await db.scalar(select(Sheikh).where(Sheikh.id == body.sheikh_id, Sheikh.tahfiz_id == context.tahfiz_id))
            if not sheikh:
                raise HTTPException(status_code=404, detail="Sheikh not found")
        membership.sheikh_id = body.sheikh_id
        if user.tahfiz_id == context.tahfiz_id:
            user.sheikh_id = body.sheikh_id

    db.add(AuditLog(
        actor_user_id=context.user.id,
        tahfiz_id=context.tahfiz_id,
        action="user.updated",
        details=f"user={user.id}",
    ))
    await db.commit()
    return {
        "id": user.id,
        "username": user.username,
        "role": membership.role.value,
        "sheikh_id": membership.sheikh_id,
    }


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    result = await db.execute(
        select(User, UserTahfizMembership)
        .join(UserTahfizMembership, UserTahfizMembership.user_id == User.id)
        .where(
            User.id == user_id,
            UserTahfizMembership.tahfiz_id == context.tahfiz_id,
            UserTahfizMembership.is_active == True,
        )
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    user, membership = row
    if user.id in (context.user.id, context.tahfiz.owner_user_id):
        raise HTTPException(status_code=400, detail="The owner or current user cannot be deleted")
    await db.execute(sa_update(SavedFilter).where(
        SavedFilter.user_id == user.id,
        SavedFilter.tahfiz_id == context.tahfiz_id,
    ).values(user_id=context.user.id))
    db.add(AuditLog(
        actor_user_id=context.user.id,
        tahfiz_id=context.tahfiz_id,
        action="user.access_revoked",
        details=f"user={user.id}; username={user.username}",
    ))
    membership.is_active = False
    next_membership = await db.scalar(select(UserTahfizMembership).where(
        UserTahfizMembership.user_id == user.id,
        UserTahfizMembership.is_active == True,
        UserTahfizMembership.id != membership.id,
    ).order_by(UserTahfizMembership.id))
    if next_membership:
        if user.default_tahfiz_id == context.tahfiz_id:
            user.default_tahfiz_id = next_membership.tahfiz_id
    else:
        user.is_active = False
        user.default_tahfiz_id = None
    if user.tahfiz_id == context.tahfiz_id:
        user.sheikh_id = None
    await db.commit()
    return {"message": "تم إلغاء وصول المستخدم"}


def database_file_path() -> str:
    from urllib.parse import urlparse
    parsed = urlparse(settings.DATABASE_URL)
    db_path = parsed.path[1:] if parsed.path.startswith("/") else parsed.path
    return os.path.abspath(db_path)


def build_full_database(source_path: str) -> str:
    fd, export_path = tempfile.mkstemp(prefix="zamzam-full-", suffix=".db")
    os.close(fd)
    source = sqlite3.connect(source_path)
    destination = sqlite3.connect(export_path)
    try:
        source.backup(destination)
        destination.execute("PRAGMA journal_mode=DELETE")
    except Exception:
        destination.close()
        source.close()
        os.unlink(export_path)
        raise
    destination.close()
    source.close()
    return export_path


@router.get("/export-db")
async def export_db(
    _=Depends(require_super_admin),
):
    db_path = database_file_path()
    if not os.path.isfile(db_path):
        raise HTTPException(status_code=404, detail=f"Database file not found at {db_path}")
    export_path = await asyncio.to_thread(build_full_database, db_path)
    return FileResponse(
        export_path,
        media_type="application/vnd.sqlite3",
        filename="zamzam_full_backup.db",
        background=BackgroundTask(os.unlink, export_path),
    )


@router.get("/tahfiz/export-db")
async def export_tahfiz_database(
    _context: TenantContext = Depends(require_tenant_admin),
):
    raise HTTPException(
        status_code=503,
        detail="Tenant database export is temporarily unavailable",
    )


@router.get("/tahfiz/export")
async def export_tahfiz(
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    tahfiz_id = context.tahfiz_id
    sheikhs = (await db.execute(select(Sheikh).where(Sheikh.tahfiz_id == tahfiz_id))).scalars().all()
    students = (await db.execute(select(Student).where(Student.tahfiz_id == tahfiz_id))).scalars().all()
    sessions = (await db.execute(select(Session).where(Session.tahfiz_id == tahfiz_id))).scalars().all()
    attendance = (await db.execute(select(Attendance).where(Attendance.tahfiz_id == tahfiz_id))).scalars().all()
    user_rows = (await db.execute(
        select(User, UserTahfizMembership)
        .join(UserTahfizMembership, UserTahfizMembership.user_id == User.id)
        .where(UserTahfizMembership.tahfiz_id == tahfiz_id)
    )).all()
    student_ids = [student.id for student in students]
    parent_phones = (await db.execute(select(ParentPhone).where(ParentPhone.student_id.in_(student_ids)))).scalars().all() if student_ids else []
    warnings = (await db.execute(select(StudentWarning).where(StudentWarning.student_id.in_(student_ids)))).scalars().all() if student_ids else []
    excused = (await db.execute(select(ExcusedWeekday).where(ExcusedWeekday.student_id.in_(student_ids)))).scalars().all() if student_ids else []
    excused_periods = (await db.execute(select(StudentExcusedPeriod).where(StudentExcusedPeriod.student_id.in_(student_ids)))).scalars().all() if student_ids else []
    subscriptions = (await db.execute(select(StudentSubscription).where(
        StudentSubscription.tahfiz_id == tahfiz_id,
    ).order_by(StudentSubscription.period_start, StudentSubscription.id))).scalars().all()

    return {
        "format": "zamzam-tahfiz-export-v1",
        "exported_at": utcnow().isoformat(),
        "tahfiz": serialize_tahfiz(context.tahfiz),
        "users": [
            {
                "id": user.id,
                "username": user.username,
                "role": membership.role.value,
                "sheikh_id": membership.sheikh_id,
                "is_active": membership.is_active,
            }
            for user, membership in user_rows
        ],
        "sheikhs": [{"id": row.id, "name": row.name, "phone": row.phone, "whatsapp_group_id": row.whatsapp_group_id} for row in sheikhs],
        "students": [{
            "id": row.id, "name": row.name, "phone": row.phone, "student_id": row.student_id,
            "birthday": row.birthday.isoformat() if row.birthday else None, "profile_pic": row.profile_pic,
            "status": row.status.value, "registration_date": row.registration_date.isoformat() if row.registration_date else None,
            "sheikh_id": row.sheikh_id, "sort_order": row.sort_order,
            "subscription_fee_override_minor": row.subscription_fee_override_minor,
        } for row in students],
        "sessions": [{"id": row.id, "date": row.date.isoformat(), "is_confirmed": row.is_confirmed} for row in sessions],
        "attendance": [{
            "id": row.id, "session_id": row.session_id, "student_id": row.student_id,
            "sheikh_id": row.sheikh_id, "status": row.status, "notes": row.notes,
        } for row in attendance],
        "parent_phones": [{
            "id": row.id, "student_id": row.student_id, "phone_number": row.phone_number,
            "parent_type": row.parent_type.value, "name": row.name,
        } for row in parent_phones],
        "warnings": [{
            "id": row.id, "student_id": row.student_id, "reason": row.reason,
            "warning_number": row.warning_number, "sent": row.sent,
            "sent_at": row.sent_at.isoformat() if row.sent_at else None,
            "created_at": row.created_at.isoformat(),
        } for row in warnings],
        "excused_weekdays": [{"id": row.id, "student_id": row.student_id, "weekday": row.weekday, "note": row.note} for row in excused],
        "excused_periods": [serialize_excused_period(row) for row in excused_periods],
        "subscriptions": [serialize_subscription_record(row) for row in subscriptions],
    }

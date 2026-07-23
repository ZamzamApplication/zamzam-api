import asyncio
import json
import os
import shutil
import sqlite3
import tempfile
import uuid
from datetime import date, datetime
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
from app.database import get_db

from app.integrations import encrypt_secret, tenant_whatsend_config
from app.media import signed_media_url
from app.models import Attendance, AuditLog, ExcusedWeekday, ParentPhone, ParentType, QuranProgressEntry, SavedFilter, Session, Sheikh, Student, StudentGoal, StudentStatus, StudentWarning, Tahfiz, User, UserRole, UserTahfizMembership, attendance_status_options
from app.routers.auth import TenantContext, get_tenant_context, pwd_context, require_super_admin, require_tenant_admin
from app.schemas import (
    CreateParentPhone,
    CreateSheikhRequest,
    CreateStudentRequest,
    CreateUserRequest,
    CreateWarningRequest,
    MoveStudentRequest,
    ReorderStudentsRequest,
    SendStudentWarningRequest,
    SendWarningsRequest,
    UpdateTahfizSettingsRequest,
    UpdateExcusedWeekdaysRequest,
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


async def send_whatsend_group_message(tahfiz: Tahfiz, group_id: str, message: str) -> None:
    api_url, _, api_key = tenant_whatsend_config(tahfiz)
    if not api_key:
        raise RuntimeError("مفتاح WhatSend API غير مضبوط")
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
        .where(Sheikh.tahfiz_id == context.tahfiz_id)
    )
    sheikhs = result.scalars().all()
    return [
        {
            "id": s.id,
            "name": s.name,
            "phone": s.phone,
            "whatsapp_group_id": s.whatsapp_group_id,
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
    sheikh = Sheikh(name=body.name, phone=body.phone, whatsapp_group_id=body.whatsapp_group_id, tahfiz_id=context.tahfiz_id)
    db.add(sheikh)
    await db.commit()
    return {"id": sheikh.id, "name": sheikh.name, "phone": sheikh.phone, "whatsapp_group_id": sheikh.whatsapp_group_id, "tahfiz_id": sheikh.tahfiz_id, "circle_id": sheikh.tahfiz_id}


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
    await db.commit()
    return {"id": sheikh.id, "name": sheikh.name, "phone": sheikh.phone, "whatsapp_group_id": sheikh.whatsapp_group_id, "tahfiz_id": sheikh.tahfiz_id, "circle_id": sheikh.tahfiz_id}


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
    await db.execute(sa_update(Student).where(Student.sheikh_id == sheikh_id, Student.tahfiz_id == context.tahfiz_id).values(sheikh_id=None))
    await db.execute(sa_update(Attendance).where(Attendance.sheikh_id == sheikh_id, Attendance.tahfiz_id == context.tahfiz_id).values(sheikh_id=None))
    await db.execute(sa_update(QuranProgressEntry).where(QuranProgressEntry.sheikh_id == sheikh_id, QuranProgressEntry.tahfiz_id == context.tahfiz_id).values(sheikh_id=None))
    await db.execute(sa_update(User).where(User.sheikh_id == sheikh_id, User.tahfiz_id == context.tahfiz_id).values(sheikh_id=None))
    db.add(AuditLog(
        actor_user_id=context.user.id,
        tahfiz_id=context.tahfiz_id,
        action="sheikh.deleted",
        details=f"sheikh={sheikh.id}; name={sheikh.name}",
    ))
    await db.delete(sheikh)
    await db.commit()
    return {"message": "تم حذف الشيخ"}


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
        )
        .where(
            Student.sheikh_id == sheikh_id,
            Student.tahfiz_id == context.tahfiz_id,
        )
        .order_by(Student.sort_order)
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
        )
        .where(Student.tahfiz_id == context.tahfiz_id)
        .order_by(Student.name)
    )
    students = result.scalars().all()

    student_ids = [s.id for s in students]
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
        }
        for s in students
    ]


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
        )
        .where(Student.id == student_id, Student.tahfiz_id == context.tahfiz_id)
    )
    student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    await db.execute(sa_delete(QuranProgressEntry).where(
        QuranProgressEntry.student_id == student_id,
        QuranProgressEntry.tahfiz_id == context.tahfiz_id,
    ))
    await db.execute(sa_delete(StudentGoal).where(
        StudentGoal.student_id == student_id,
        StudentGoal.tahfiz_id == context.tahfiz_id,
    ))
    if delete_sessions:
        await db.delete(student)
    else:
        for att in student.attendance_records:
            att.student_id = None
        await db.delete(student)

    db.add(AuditLog(
        actor_user_id=context.user.id,
        tahfiz_id=context.tahfiz_id,
        action="student.deleted",
        details=f"student={student.id}; name={student.name}; delete_attendance={delete_sessions}",
    ))
    await db.commit()
    return {"message": "تم حذف الطالب"}


@router.post("/students/{student_id}/move-sheikh")
async def move_student_sheikh(
    student_id: int,
    body: MoveStudentRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(require_tenant_admin),
):
    result = await db.execute(select(Student).where(Student.id == student_id, Student.tahfiz_id == context.tahfiz_id))
    student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    if student.sheikh_id == body.sheikh_id:
        raise HTTPException(status_code=400, detail="الطالب بالفعل تحت هذا الشيخ")

    result = await db.execute(select(Sheikh).where(Sheikh.id == body.sheikh_id, Sheikh.tahfiz_id == context.tahfiz_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Sheikh not found")

    student.sheikh_id = body.sheikh_id
    student.sort_order = 0
    await db.commit()
    return {"message": f"تم نقل الطالب إلى الشيخ {body.sheikh_id}"}


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
    warning.sent_at = datetime.utcnow()
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
        warning.sent_at = datetime.utcnow()
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
        "whatsend_api_url": tahfiz.whatsend_api_url,
        "whatsend_groups_url": tahfiz.whatsend_groups_url,
        "whatsend_api_key_configured": bool(tahfiz.whatsend_api_key_encrypted or settings.WHATSEND_API_KEY),
        "progress_tracking_enabled": tahfiz.progress_tracking_enabled,
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
    for field in ("name", "description", "contact_phone", "max_warnings", "whatsend_api_url", "whatsend_groups_url"):
        value = getattr(body, field)
        if value is not None:
            normalized = value.strip() if isinstance(value, str) else value
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
    if body.progress_tracking_enabled is not None and tahfiz.progress_tracking_enabled != body.progress_tracking_enabled:
        tahfiz.progress_tracking_enabled = body.progress_tracking_enabled
        changed_fields.append("progress_tracking_enabled")
    if body.whatsend_api_key is not None:
        tahfiz.whatsend_api_key_encrypted = encrypt_secret(body.whatsend_api_key.strip()) if body.whatsend_api_key.strip() else None
        changed_fields.append("whatsend_api_key")
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


def build_tenant_database(source_path: str, tahfiz_id: int) -> str:
    fd, export_path = tempfile.mkstemp(prefix=f"zamzam-tahfiz-{tahfiz_id}-", suffix=".db")
    os.close(fd)
    source = sqlite3.connect(source_path)
    destination = sqlite3.connect(export_path)
    try:
        source.backup(destination)
        destination.execute("PRAGMA foreign_keys=OFF")
        tables = {
            row[0]
            for row in destination.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        statements = [
            ("attendance", "DELETE FROM attendance WHERE tahfiz_id IS NULL OR tahfiz_id != ?", (tahfiz_id,)),
            ("sessions", "DELETE FROM sessions WHERE tahfiz_id != ?", (tahfiz_id,)),
            ("saved_filters", "DELETE FROM saved_filters WHERE tahfiz_id != ?", (tahfiz_id,)),
            ("audit_logs", "DELETE FROM audit_logs WHERE tahfiz_id IS NULL OR tahfiz_id != ?", (tahfiz_id,)),
            ("tahfiz_invitations", "DELETE FROM tahfiz_invitations WHERE tahfiz_id != ?", (tahfiz_id,)),
            ("parent_phones", "DELETE FROM parent_phones WHERE student_id NOT IN (SELECT id FROM students WHERE tahfiz_id = ?)", (tahfiz_id,)),
            ("student_warnings", "DELETE FROM student_warnings WHERE student_id NOT IN (SELECT id FROM students WHERE tahfiz_id = ?)", (tahfiz_id,)),
            ("excused_weekdays", "DELETE FROM excused_weekdays WHERE student_id NOT IN (SELECT id FROM students WHERE tahfiz_id = ?)", (tahfiz_id,)),
            ("students", "DELETE FROM students WHERE tahfiz_id != ?", (tahfiz_id,)),
            ("user_tahfiz_memberships", "DELETE FROM user_tahfiz_memberships WHERE tahfiz_id != ?", (tahfiz_id,)),
            (
                "users",
                "DELETE FROM users WHERE id NOT IN "
                "(SELECT user_id FROM user_tahfiz_memberships WHERE tahfiz_id = ?) "
                "AND (tahfiz_id IS NULL OR tahfiz_id != ?)",
                (tahfiz_id, tahfiz_id),
            ),
            ("sheikhs", "DELETE FROM sheikhs WHERE tahfiz_id != ?", (tahfiz_id,)),
            ("tahfiz", "DELETE FROM tahfiz WHERE id != ?", (tahfiz_id,)),
        ]
        for table, statement, parameters in statements:
            if table in tables:
                destination.execute(statement, parameters)
        destination.commit()
        destination.execute("PRAGMA journal_mode=DELETE")
        destination.execute("VACUUM")
    except Exception:
        destination.close()
        source.close()
        os.unlink(export_path)
        raise
    destination.close()
    source.close()
    return export_path


@router.get("/tahfiz/export-db")
async def export_tahfiz_database(
    context: TenantContext = Depends(require_tenant_admin),
):
    db_path = database_file_path()
    if not os.path.isfile(db_path):
        raise HTTPException(status_code=404, detail="Database file not found")
    export_path = await asyncio.to_thread(build_tenant_database, db_path, context.tahfiz_id)
    return FileResponse(
        export_path,
        media_type="application/vnd.sqlite3",
        filename="zamzam_backup.db",
        background=BackgroundTask(os.unlink, export_path),
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

    return {
        "format": "zamzam-tahfiz-export-v1",
        "exported_at": datetime.utcnow().isoformat(),
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
    }

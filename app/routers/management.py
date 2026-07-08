import os
import shutil
import uuid
from datetime import date, datetime
from io import BytesIO
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import delete as sa_delete, select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db

from app.models import Attendance, Circle, ExcusedWeekday, ParentPhone, ParentType, Session, Sheikh, Student, StudentStatus, StudentWarning, User, UserRole
from app.routers.auth import pwd_context, require_admin
from app.schemas import (
    CreateCircleRequest,
    CreateParentPhone,
    CreateSheikhRequest,
    CreateStudentRequest,
    CreateUserRequest,
    CreateWarningRequest,
    MoveStudentRequest,
    ReorderStudentsRequest,
    SendWarningsRequest,
    UpdateCircleRequest,
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


def pic_url(path: str) -> str:
    return f"/uploads/{path}"


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
    _=Depends(require_admin),
):
    result = await db.execute(select(Sheikh).options(selectinload(Sheikh.circle)))
    sheikhs = result.scalars().all()
    return [
        {
            "id": s.id,
            "name": s.name,
            "phone": s.phone,
            "whatsapp_group_id": s.whatsapp_group_id,
            "circle_id": s.circle_id,
            "circle_name": s.circle.name,
        }
        for s in sheikhs
    ]


@router.post("/sheikhs")
async def create_sheikh(
    body: CreateSheikhRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    sheikh = Sheikh(name=body.name, phone=body.phone, whatsapp_group_id=body.whatsapp_group_id, circle_id=body.circle_id)
    db.add(sheikh)
    await db.commit()
    return {"id": sheikh.id, "name": sheikh.name, "phone": sheikh.phone, "whatsapp_group_id": sheikh.whatsapp_group_id, "circle_id": sheikh.circle_id}


@router.put("/sheikhs/{sheikh_id}")
async def update_sheikh(
    sheikh_id: int,
    body: UpdateSheikhRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    result = await db.execute(select(Sheikh).where(Sheikh.id == sheikh_id))
    sheikh = result.scalar_one_or_none()
    if not sheikh:
        raise HTTPException(status_code=404, detail="Sheikh not found")
    if body.name is not None:
        sheikh.name = body.name
    if body.phone is not None:
        sheikh.phone = body.phone
    if body.whatsapp_group_id is not None:
        sheikh.whatsapp_group_id = body.whatsapp_group_id
    if body.circle_id is not None:
        sheikh.circle_id = body.circle_id
    await db.commit()
    return {"id": sheikh.id, "name": sheikh.name, "phone": sheikh.phone, "whatsapp_group_id": sheikh.whatsapp_group_id, "circle_id": sheikh.circle_id}


@router.delete("/sheikhs/{sheikh_id}")
async def delete_sheikh(
    sheikh_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    result = await db.execute(select(Sheikh).where(Sheikh.id == sheikh_id))
    sheikh = result.scalar_one_or_none()
    if not sheikh:
        raise HTTPException(status_code=404, detail="Sheikh not found")
    await db.execute(sa_update(Student).where(Student.sheikh_id == sheikh_id).values(sheikh_id=None))
    await db.delete(sheikh)
    await db.commit()
    return {"message": "تم حذف الشيخ"}


# ─── Sheikh Students ─────────────────────────────────────────────────────────


@router.get("/sheikhs/{sheikh_id}/students")
async def get_sheikh_students(
    sheikh_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    result = await db.execute(
        select(Student)
        .options(
            selectinload(Student.parent_phones),
            selectinload(Student.warnings),
        )
        .where(
            Student.sheikh_id == sheikh_id,
        )
        .order_by(Student.sort_order)
    )
    records = result.scalars().all()

    # Batch-load excused weekdays for all students
    student_ids = [r.id for r in records]
    ew_result = await db.execute(
        select(ExcusedWeekday).where(ExcusedWeekday.student_id.in_(student_ids))
    )
    ew_map: dict[int, list[int]] = {}
    for ew in ew_result.scalars().all():
        ew_map.setdefault(ew.student_id, []).append(ew.weekday)

    return [
        {
            "id": r.id,
            "name": r.name,
            "phone": r.phone,
            "student_id": r.student_id,
            "birthday": r.birthday.isoformat() if r.birthday else None,
            "profile_pic": r.profile_pic,
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
    _=Depends(require_admin),
):
    for i, student_id in enumerate(body.student_ids):
        result = await db.execute(
            select(Student).where(
                Student.id == student_id,
                Student.sheikh_id == sheikh_id,
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
    _=Depends(require_admin),
):
    result = await db.execute(
        select(Student)
        .options(
            selectinload(Student.sheikh),
            selectinload(Student.parent_phones),
            selectinload(Student.warnings),
        )
        .order_by(Student.name)
    )
    students = result.scalars().all()

    student_ids = [s.id for s in students]
    ew_result = await db.execute(
        select(ExcusedWeekday).where(ExcusedWeekday.student_id.in_(student_ids))
    )
    ew_map: dict[int, list[int]] = {}
    for ew in ew_result.scalars().all():
        ew_map.setdefault(ew.student_id, []).append(ew.weekday)

    return [
        {
            "id": s.id,
            "name": s.name,
            "phone": s.phone,
            "student_id": s.student_id,
            "birthday": s.birthday.isoformat() if s.birthday else None,
            "profile_pic": s.profile_pic,
            "status": s.status.value,
            "registration_date": s.registration_date.isoformat() if s.registration_date else None,
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
    _=Depends(require_admin),
):
    student = Student(
        name=body.name,
        phone=body.phone,
        student_id=body.student_id,
        birthday=body.birthday,
        status=StudentStatus(body.status),
        registration_date=body.registration_date or date.today(),
        sheikh_id=body.sheikh_id,
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
    _=Depends(require_admin),
):
    result = await db.execute(
        select(Student)
        .options(
            selectinload(Student.parent_phones),
        )
        .where(Student.id == student_id)
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
        student.profile_pic = body.profile_pic
    if body.status is not None:
        student.status = StudentStatus(body.status)
    if body.registration_date is not None:
        student.registration_date = body.registration_date
    if body.sheikh_id is not None:
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
    _=Depends(require_admin),
):
    result = await db.execute(
        select(Student)
        .options(
            selectinload(Student.attendance_records),
        )
        .where(Student.id == student_id)
    )
    student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    if delete_sessions:
        await db.delete(student)
    else:
        for att in student.attendance_records:
            att.student_id = None
        await db.delete(student)

    await db.commit()
    return {"message": "تم حذف الطالب"}


@router.post("/students/{student_id}/move-sheikh")
async def move_student_sheikh(
    student_id: int,
    body: MoveStudentRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    result = await db.execute(select(Student).where(Student.id == student_id))
    student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    if student.sheikh_id == body.sheikh_id:
        raise HTTPException(status_code=400, detail="الطالب بالفعل تحت هذا الشيخ")

    result = await db.execute(select(Sheikh).where(Sheikh.id == body.sheikh_id))
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
    _=Depends(require_admin),
):
    result = await db.execute(select(Student).where(Student.id == student_id))
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


@router.put("/warnings/{warning_id}")
async def update_warning(
    warning_id: int,
    body: CreateWarningRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    result = await db.execute(select(StudentWarning).where(StudentWarning.id == warning_id))
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
    _=Depends(require_admin),
):
    result = await db.execute(select(StudentWarning).where(StudentWarning.id == warning_id))
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
    _=Depends(require_admin),
):
    query = (
        select(StudentWarning)
        .options(selectinload(StudentWarning.student).selectinload(Student.sheikh))
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
    _=Depends(require_admin),
):
    results: list[dict] = []
    for wid in body.warning_ids:
        result = await db.execute(
            select(StudentWarning)
            .options(selectinload(StudentWarning.student).selectinload(Student.sheikh))
            .where(StudentWarning.id == wid)
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

        circle = await db.execute(select(Circle).where(Circle.id == sheikh.circle_id))
        circle_obj = circle.scalar_one_or_none()
        max_w = circle_obj.max_warnings if circle_obj else 3
        remaining = max_w - warning.warning_number

        message = (
            f"انذار رقم {warning.warning_number} الى الطالب \"{student.name}\"\n"
            f" بسبب غيابه بدون اعتذار عن حلقات:\n"
            f"{warning.reason}\n\n"
            f"عدد الانذارات المتبقية قبل الاستبعاد: {remaining}"
        )

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    settings.WHATSEND_API_URL,
                    headers={"Authorization": f"Bearer {settings.WHATSEND_API_KEY}"},
                    json={"groupid": sheikh.whatsapp_group_id, "message": message},
                )
                resp.raise_for_status()
        except Exception as e:
            results.append({"warning_id": wid, "success": False, "error": str(e)})
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
    _=Depends(require_admin),
):
    result = await db.execute(
        select(ExcusedWeekday).where(ExcusedWeekday.student_id == student_id)
    )
    return [{"id": e.id, "weekday": e.weekday} for e in result.scalars().all()]


@router.put("/students/{student_id}/excused-weekdays")
async def update_excused_weekdays(
    student_id: int,
    body: UpdateExcusedWeekdaysRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    result = await db.execute(select(Student).where(Student.id == student_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Student not found")

    await db.execute(sa_delete(ExcusedWeekday).where(ExcusedWeekday.student_id == student_id))
    for wd in body.weekdays:
        db.add(ExcusedWeekday(student_id=student_id, weekday=wd))
    await db.commit()
    return {"weekdays": body.weekdays}


@router.post("/students/{student_id}/upload-pic")
async def upload_student_pic(
    student_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    result = await db.execute(select(Student).where(Student.id == student_id))
    student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    if file.content_type and not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Uploaded file must be an image.")

    content = await file.read()
    compressed = compress_profile_image(content)
    filename = f"{uuid.uuid4()}.webp"
    filepath = UPLOAD_DIR / filename
    with open(filepath, "wb") as f:
        f.write(compressed)

    delete_upload(student.profile_pic)
    student.profile_pic = filename
    await db.commit()
    return {"url": pic_url(filename)}


# ─── Circles ─────────────────────────────────────────────────────────────────


@router.get("/circles")
async def list_circles(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    result = await db.execute(select(Circle))
    circles = result.scalars().all()
    return [{"id": c.id, "name": c.name, "description": c.description, "max_warnings": c.max_warnings} for c in circles]


@router.post("/circles")
async def create_circle(
    body: CreateCircleRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    circle = Circle(name=body.name, description=body.description, max_warnings=body.max_warnings)
    db.add(circle)
    await db.commit()
    return {"id": circle.id, "name": circle.name, "description": circle.description, "max_warnings": circle.max_warnings}


@router.put("/circles/{circle_id}")
async def update_circle(
    circle_id: int,
    body: UpdateCircleRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    result = await db.execute(select(Circle).where(Circle.id == circle_id))
    circle = result.scalar_one_or_none()
    if not circle:
        raise HTTPException(status_code=404, detail="Circle not found")
    if body.name is not None:
        circle.name = body.name
    if body.description is not None:
        circle.description = body.description
    if body.max_warnings is not None:
        circle.max_warnings = body.max_warnings
    await db.commit()
    return {"id": circle.id, "name": circle.name, "description": circle.description, "max_warnings": circle.max_warnings}


@router.delete("/circles/{circle_id}")
async def delete_circle(
    circle_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    result = await db.execute(select(Circle).where(Circle.id == circle_id))
    circle = result.scalar_one_or_none()
    if not circle:
        raise HTTPException(status_code=404, detail="Circle not found")

    await db.execute(sa_update(Student).where(Student.sheikh.has(Sheikh.circle_id == circle_id)).values(sheikh_id=None))
    await db.delete(circle)
    await db.commit()
    return {"message": "تم حذف الحلقة"}


# ─── Users ───────────────────────────────────────────────────────────────────


@router.get("/users")
async def list_users(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    result = await db.execute(select(User))
    users = result.scalars().all()
    return [
        {"id": u.id, "username": u.username, "role": u.role.value, "sheikh_id": u.sheikh_id}
        for u in users
    ]


@router.post("/users")
async def create_user(
    body: CreateUserRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    existing = await db.execute(select(User).where(User.username == body.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already exists")

    user = User(
        username=body.username,
        password_hash=pwd_context.hash(body.password),
        role=UserRole(body.role),
        sheikh_id=body.sheikh_id,
    )
    db.add(user)
    await db.commit()
    return {"id": user.id, "username": user.username, "role": user.role.value, "sheikh_id": user.sheikh_id}


@router.put("/users/{user_id}")
async def update_user(
    user_id: int,
    body: UpdateUserRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if body.username is not None:
        user.username = body.username
    if body.password is not None:
        user.password_hash = pwd_context.hash(body.password)
    if body.role is not None:
        user.role = UserRole(body.role)
    if body.sheikh_id is not None:
        user.sheikh_id = body.sheikh_id

    await db.commit()
    return {"id": user.id, "username": user.username, "role": user.role.value, "sheikh_id": user.sheikh_id}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await db.delete(user)
    await db.commit()
    return {"message": "تم حذف المستخدم"}


@router.get("/export-db")
async def export_db(
    _=Depends(require_admin),
):
    from urllib.parse import urlparse
    parsed = urlparse(settings.DATABASE_URL)
    db_path = parsed.path[1:] if parsed.path.startswith("/") else parsed.path
    db_path = os.path.abspath(db_path)
    if not os.path.isfile(db_path):
        raise HTTPException(status_code=404, detail=f"Database file not found at {db_path}")
    return FileResponse(
        db_path,
        media_type="application/octet-stream",
        filename="zamzam_backup.db",
    )

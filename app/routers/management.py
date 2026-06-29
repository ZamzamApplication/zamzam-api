import os
import re
import shutil
import uuid
from datetime import date, datetime
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy import delete as sa_delete, select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db

from app.models import Attendance, Circle, ParentPhone, ParentType, Session, Sheikh, Student, StudentStatus, StudentWarning, User, UserRole
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
    UpdateCircleRequest,
    UpdateParentPhone,
    UpdateSheikhRequest,
    UpdateStudentRequest,
    UpdateUserRequest,
)

router = APIRouter(tags=["management"])

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)


def pic_url(path: str) -> str:
    return f"{settings.API_BASE_URL}/uploads/{path}"


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
    sheikh = Sheikh(name=body.name, phone=body.phone, circle_id=body.circle_id)
    db.add(sheikh)
    await db.commit()
    return {"id": sheikh.id, "name": sheikh.name, "phone": sheikh.phone, "circle_id": sheikh.circle_id}


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
    if body.circle_id is not None:
        sheikh.circle_id = body.circle_id
    await db.commit()
    return {"id": sheikh.id, "name": sheikh.name, "phone": sheikh.phone, "circle_id": sheikh.circle_id}


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
                {"id": w.id, "reason": w.reason, "created_at": w.created_at.isoformat()}
                for w in r.warnings
            ],
            "parent_phones": [
                {"id": p.id, "phone_number": p.phone_number, "parent_type": p.parent_type.value, "name": p.name}
                for p in r.parent_phones
            ],
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
                {"id": w.id, "reason": w.reason, "created_at": w.created_at.isoformat()}
                for w in s.warnings
            ],
            "sheikh": {"id": s.sheikh.id, "name": s.sheikh.name} if s.sheikh else None,
            "parent_phones": [
                {"id": p.id, "phone_number": p.phone_number, "parent_type": p.parent_type.value, "name": p.name}
                for p in s.parent_phones
            ],
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

    warning = StudentWarning(student_id=student_id, reason=body.reason)
    db.add(warning)
    await db.commit()
    await db.refresh(warning)
    return {"id": warning.id, "reason": warning.reason, "created_at": warning.created_at.isoformat()}


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
    return {"id": warning.id, "reason": warning.reason, "created_at": warning.created_at.isoformat()}


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

    ext = Path(file.filename or "image.jpg").suffix
    filename = f"{uuid.uuid4()}{ext}"
    filepath = UPLOAD_DIR / filename
    with open(filepath, "wb") as f:
        content = await file.read()
        f.write(content)

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
    return [{"id": c.id, "name": c.name, "description": c.description} for c in circles]


@router.post("/circles")
async def create_circle(
    body: CreateCircleRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    circle = Circle(name=body.name, description=body.description)
    db.add(circle)
    await db.commit()
    return {"id": circle.id, "name": circle.name, "description": circle.description}


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
    await db.commit()
    return {"id": circle.id, "name": circle.name, "description": circle.description}


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
    match = re.match(r"sqlite\+aiosqlite:///(.+)", settings.DATABASE_URL)
    if not match:
        raise HTTPException(status_code=500, detail="Unsupported database URL")
    db_path = match.group(1)
    if not os.path.isfile(db_path):
        raise HTTPException(status_code=404, detail="Database file not found")
    return FileResponse(
        db_path,
        media_type="application/octet-stream",
        filename="zamzam_backup.db",
    )

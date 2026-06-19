import os
import shutil
import uuid
from datetime import date, datetime, time
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import delete as sa_delete, select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db

from app.models import Attendance, Circle, CircleSchedule, ParentPhone, ParentType, Session, Sheikh, Student, StudentSheikh, StudentWarning, User, UserRole
from app.routers.auth import get_current_user_depends, pwd_context
from app.schemas import (
    CreateCircleRequest,
    CreateCircleScheduleRequest,
    CreateParentPhone,
    CreateSheikhRequest,
    CreateStudentRequest,
    CreateUserRequest,
    CreateWarningRequest,
    MoveStudentRequest,
    UpdateCircleRequest,
    UpdateParentPhone,
    UpdateSheikhRequest,
    UpdateStudentRequest,
    UpdateUserRequest,
)

router = APIRouter(tags=["management"])


# ─── Circles ────────────────────────────────────────────────────────────────

@router.post("/circles")
async def create_circle(
    body: CreateCircleRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    circle = Circle(name=body.name, description=body.description)
    db.add(circle)
    await db.commit()
    await db.refresh(circle)
    return {"id": circle.id, "name": circle.name, "description": circle.description}


@router.put("/circles/{circle_id}")
async def update_circle(
    circle_id: int,
    body: UpdateCircleRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
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
    await db.refresh(circle)
    return {"id": circle.id, "name": circle.name, "description": circle.description}


@router.delete("/circles/{circle_id}")
async def delete_circle(
    circle_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    result = await db.execute(select(Circle).where(Circle.id == circle_id))
    circle = result.scalar_one_or_none()
    if not circle:
        raise HTTPException(status_code=404, detail="Circle not found")

    # Nullify user references to sheikhs in this circle
    sheikh_ids_result = await db.execute(select(Sheikh.id).where(Sheikh.circle_id == circle_id))
    sheikh_ids = [row[0] for row in sheikh_ids_result.all()]
    if sheikh_ids:
        await db.execute(sa_update(User).where(User.sheikh_id.in_(sheikh_ids)).values(sheikh_id=None))

    # Delete sessions (cascades to attendance records)
    sessions_result = await db.execute(select(Session.id).where(Session.circle_id == circle_id))
    session_ids = [row[0] for row in sessions_result.all()]
    if session_ids:
        await db.execute(sa_delete(Attendance).where(Attendance.session_id.in_(session_ids)))
        await db.execute(sa_delete(Session).where(Session.circle_id == circle_id))

    # Delete sheikhs (cascades to student_sheikhs)
    if sheikh_ids:
        await db.execute(sa_delete(Sheikh).where(Sheikh.circle_id == circle_id))

    # Delete schedules
    await db.execute(sa_delete(CircleSchedule).where(CircleSchedule.circle_id == circle_id))

    await db.delete(circle)
    await db.commit()
    return {"message": "Circle and all related data deleted"}


# ─── Sheikhs ────────────────────────────────────────────────────────────────

@router.get("/sheikhs")
async def list_sheikhs(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    result = await db.execute(
        select(Sheikh).options(selectinload(Sheikh.circle))
    )
    sheikhs = result.scalars().all()
    return [
        {"id": s.id, "name": s.name, "phone": s.phone, "circle_id": s.circle_id, "circle_name": s.circle.name}
        for s in sheikhs
    ]


@router.post("/sheikhs")
async def create_sheikh(
    body: CreateSheikhRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    circle_id = body.circle_id
    if circle_id:
        result = await db.execute(select(Circle).where(Circle.id == circle_id))
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Circle not found")
    else:
        result = await db.execute(select(Circle))
        first = result.scalar_one_or_none()
        if not first:
            raise HTTPException(status_code=400, detail="No circles exist")
        circle_id = first.id

    sheikh = Sheikh(name=body.name, phone=body.phone, circle_id=circle_id)
    db.add(sheikh)
    await db.commit()
    await db.refresh(sheikh)
    return {"id": sheikh.id, "name": sheikh.name, "phone": sheikh.phone, "circle_id": sheikh.circle_id}


@router.put("/sheikhs/{sheikh_id}")
async def update_sheikh(
    sheikh_id: int,
    body: UpdateSheikhRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
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
        result = await db.execute(select(Circle).where(Circle.id == body.circle_id))
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Circle not found")
        sheikh.circle_id = body.circle_id
    await db.commit()
    await db.refresh(sheikh)
    return {"id": sheikh.id, "name": sheikh.name, "phone": sheikh.phone, "circle_id": sheikh.circle_id}


@router.delete("/sheikhs/{sheikh_id}")
async def delete_sheikh(
    sheikh_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    result = await db.execute(select(Sheikh).where(Sheikh.id == sheikh_id))
    sheikh = result.scalar_one_or_none()
    if not sheikh:
        raise HTTPException(status_code=404, detail="Sheikh not found")
    await db.delete(sheikh)
    await db.commit()
    return {"message": "Sheikh deleted"}


@router.get("/sheikhs/{sheikh_id}/students")
async def get_sheikh_students(
    sheikh_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    result = await db.execute(
        select(StudentSheikh)
        .options(
            selectinload(StudentSheikh.student).selectinload(Student.parent_phones),
            selectinload(StudentSheikh.student).selectinload(Student.warnings),
        )
        .where(
            StudentSheikh.sheikh_id == sheikh_id,
            StudentSheikh.end_date.is_(None),
        )
    )
    records = result.scalars().all()
    return [
        {
            "id": r.student.id,
            "name": r.student.name,
            "phone": r.student.phone,
            "student_id": r.student.student_id,
            "birthday": r.student.birthday.isoformat() if r.student.birthday else None,
            "profile_pic": r.student.profile_pic,
            "is_enrolled": r.student.is_enrolled,
            "registration_date": r.student.registration_date.isoformat() if r.student.registration_date else None,
            "warnings": [
                {"id": w.id, "reason": w.reason, "created_at": w.created_at.isoformat()}
                for w in r.student.warnings
            ],
            "parent_phones": [
                {"id": p.id, "phone_number": p.phone_number, "parent_type": p.parent_type.value, "name": p.name}
                for p in r.student.parent_phones
            ],
        }
        for r in records
    ]


@router.get("/students")
async def list_students(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    result = await db.execute(
        select(Student)
        .options(
            selectinload(Student.sheikhs).selectinload(StudentSheikh.sheikh),
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
            "is_enrolled": s.is_enrolled,
            "registration_date": s.registration_date.isoformat() if s.registration_date else None,
            "warnings": [
                {"id": w.id, "reason": w.reason, "created_at": w.created_at.isoformat()}
                for w in s.warnings
            ],
            "sheikh": {"id": s.sheikhs[0].sheikh.id, "name": s.sheikhs[0].sheikh.name} if s.sheikhs else None,
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
    current_user=Depends(get_current_user_depends),
):
    student = Student(
        name=body.name,
        phone=body.phone,
        student_id=body.student_id,
        birthday=body.birthday,
        is_enrolled=body.is_enrolled,
        registration_date=body.registration_date or date.today(),
    )
    db.add(student)
    await db.flush()

    if body.sheikh_id:
        result = await db.execute(select(Sheikh).where(Sheikh.id == body.sheikh_id))
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Sheikh not found")
        ss = StudentSheikh(
            student_id=student.id,
            sheikh_id=body.sheikh_id,
            start_date=date.today(),
        )
        db.add(ss)

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
    return {
        "id": student.id,
        "name": student.name,
        "phone": student.phone,
        "student_id": student.student_id,
        "birthday": student.birthday.isoformat() if student.birthday else None,
        "profile_pic": student.profile_pic,
        "is_enrolled": student.is_enrolled,
        "registration_date": student.registration_date.isoformat() if student.registration_date else None,
        "warnings": [
            {"id": w.id, "reason": w.reason, "created_at": w.created_at.isoformat()}
            for w in student.warnings
        ],
    }


@router.put("/students/{student_id}")
async def update_student(
    student_id: int,
    body: UpdateStudentRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    result = await db.execute(
        select(Student)
        .options(selectinload(Student.parent_phones), selectinload(Student.warnings))
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
    if body.is_enrolled is not None:
        student.is_enrolled = body.is_enrolled
    if body.registration_date is not None:
        student.registration_date = body.registration_date
    if body.parent_phones is not None:
        for existing in student.parent_phones:
            await db.delete(existing)
        for pp in body.parent_phones:
            if pp.parent_type is not None and pp.parent_type not in [t.value for t in ParentType]:
                raise HTTPException(status_code=400, detail=f"Invalid parent type: {pp.parent_type}")
            parent_phone = ParentPhone(
                student_id=student.id,
                phone_number=pp.phone_number,
                parent_type=ParentType(pp.parent_type) if pp.parent_type else None,
                name=pp.name,
            )
            db.add(parent_phone)
    await db.commit()
    await db.refresh(student)
    return {
        "id": student.id,
        "name": student.name,
        "phone": student.phone,
        "student_id": student.student_id,
        "birthday": student.birthday.isoformat() if student.birthday else None,
        "profile_pic": student.profile_pic,
        "is_enrolled": student.is_enrolled,
        "registration_date": student.registration_date.isoformat() if student.registration_date else None,
        "warnings": [
            {"id": w.id, "reason": w.reason, "created_at": w.created_at.isoformat()}
            for w in student.warnings
        ],
    }


@router.post("/students/{student_id}/upload-pic")
async def upload_student_pic(
    student_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    result = await db.execute(select(Student).where(Student.id == student_id))
    student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    ext = os.path.splitext(file.filename or ".jpg")[1]
    filename = f"{uuid.uuid4().hex}{ext}"
    upload_dir = settings.UPLOAD_DIR
    filepath = os.path.join(upload_dir, filename)

    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)

    student.profile_pic = f"/uploads/{filename}"
    await db.commit()
    return {"profile_pic": student.profile_pic}


@router.post("/students/{student_id}/move-sheikh")
async def move_student_sheikh(
    student_id: int,
    body: MoveStudentRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    result = await db.execute(
        select(StudentSheikh)
        .where(
            StudentSheikh.student_id == student_id,
            StudentSheikh.end_date.is_(None),
        )
    )
    current_ss = result.scalar_one_or_none()
    if current_ss:
        if current_ss.sheikh_id == body.sheikh_id:
            raise HTTPException(status_code=400, detail="الطالب بالفعل تحت هذا الشيخ")
        current_ss.end_date = date.today()

    result = await db.execute(
        select(Student).where(Student.id == student_id)
    )
    student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    result = await db.execute(select(Sheikh).where(Sheikh.id == body.sheikh_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Sheikh not found")

    new_ss = StudentSheikh(
        student_id=student_id,
        sheikh_id=body.sheikh_id,
        start_date=date.today(),
    )
    db.add(new_ss)
    await db.commit()
    return {"message": f"تم نقل الطالب إلى الشيخ {body.sheikh_id}"}


@router.post("/students/{student_id}/warnings")
async def add_student_warning(
    student_id: int,
    body: CreateWarningRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    result = await db.execute(select(Student).where(Student.id == student_id))
    student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    warning = StudentWarning(student_id=student.id, reason=body.reason)
    db.add(warning)
    await db.commit()
    await db.refresh(warning)

    if student.phone and settings.WHATSEND_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                msg = f"تنبيه: الطالب {student.name} حصل على إنذار. السبب: {body.reason}"
                await client.post(
                    settings.WHATSEND_API_URL,
                    headers={"Authorization": f"Bearer {settings.WHATSEND_API_KEY}"},
                    json={"number": student.phone, "message": msg, "provider": "whatsapp"},
                )
        except Exception:
            pass

    return {"id": warning.id, "reason": warning.reason, "created_at": warning.created_at.isoformat()}


# ─── Users ──────────────────────────────────────────────────────────────────

@router.get("/users")
async def list_users(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
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
    current_user=Depends(get_current_user_depends),
):
    result = await db.execute(select(User).where(User.username == body.username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already exists")

    if body.role not in ("admin", "sheikh"):
        raise HTTPException(status_code=400, detail="Role must be 'admin' or 'sheikh'")

    if body.sheikh_id:
        result = await db.execute(select(Sheikh).where(Sheikh.id == body.sheikh_id))
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Sheikh not found")

    user = User(
        username=body.username,
        hashed_password=pwd_context.hash(body.password),
        role=UserRole(body.role),
        sheikh_id=body.sheikh_id,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return {"id": user.id, "username": user.username, "role": user.role.value, "sheikh_id": user.sheikh_id}


@router.put("/users/{user_id}")
async def update_user(
    user_id: int,
    body: UpdateUserRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if body.username is not None:
        result = await db.execute(select(User).where(User.username == body.username, User.id != user_id))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Username already exists")
        user.username = body.username
    if body.password is not None:
        user.hashed_password = pwd_context.hash(body.password)
    if body.role is not None:
        if body.role not in ("admin", "sheikh"):
            raise HTTPException(status_code=400, detail="Role must be 'admin' or 'sheikh'")
        user.role = UserRole(body.role)
    if body.sheikh_id is not None:
        result = await db.execute(select(Sheikh).where(Sheikh.id == body.sheikh_id))
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Sheikh not found")
        user.sheikh_id = body.sheikh_id

    await db.commit()
    await db.refresh(user)
    return {"id": user.id, "username": user.username, "role": user.role.value, "sheikh_id": user.sheikh_id}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await db.delete(user)
    await db.commit()
    return {"message": "User deleted"}


# ─── Circle Schedules ───────────────────────────────────────────────────────

@router.get("/circles/{circle_id}/schedules")
async def list_circle_schedules(
    circle_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    result = await db.execute(
        select(CircleSchedule).where(CircleSchedule.circle_id == circle_id)
    )
    schedules = result.scalars().all()
    return [
        {"id": s.id, "circle_id": s.circle_id, "day_of_week": s.day_of_week, "time": s.time.strftime("%H:%M")}
        for s in schedules
    ]


@router.post("/schedules")
async def create_schedule(
    body: CreateCircleScheduleRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    result = await db.execute(select(Circle).where(Circle.id == body.circle_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Circle not found")

    if body.day_of_week < 0 or body.day_of_week > 6:
        raise HTTPException(status_code=400, detail="day_of_week must be 0-6")

    try:
        parsed_time = time.fromisoformat(body.time)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid time format. Use HH:MM")

    schedule = CircleSchedule(
        circle_id=body.circle_id,
        day_of_week=body.day_of_week,
        time=parsed_time,
    )
    db.add(schedule)
    await db.commit()
    await db.refresh(schedule)
    return {"id": schedule.id, "circle_id": schedule.circle_id, "day_of_week": schedule.day_of_week, "time": schedule.time.strftime("%H:%M")}


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(
    schedule_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    result = await db.execute(select(CircleSchedule).where(CircleSchedule.id == schedule_id))
    schedule = result.scalar_one_or_none()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    await db.delete(schedule)
    await db.commit()
    return {"message": "Schedule deleted"}


# ─── Database ────────────────────────────────────────────────────────────────

@router.post("/reset-db")
async def reset_database(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Admin only")

    # Delete in FK-safe order
    await db.execute(sa_delete(Attendance))
    await db.execute(sa_delete(Session))
    await db.execute(sa_delete(ParentPhone))
    await db.execute(sa_delete(StudentWarning))
    await db.execute(sa_delete(StudentSheikh))
    await db.execute(sa_delete(Student))
    await db.execute(sa_delete(CircleSchedule))
    # Nullify sheikh references before deleting sheikhs/circles
    await db.execute(sa_update(User).values(sheikh_id=None))
    await db.execute(sa_delete(Sheikh))
    await db.execute(sa_delete(Circle))
    # Delete non-admin users
    await db.execute(sa_delete(User).where(User.role != UserRole.admin))

    # Delete uploaded profile pictures
    upload_dir = Path(settings.UPLOAD_DIR)
    if upload_dir.exists():
        for f in upload_dir.iterdir():
            if f.is_file():
                f.unlink()

    await db.commit()
    return {"message": "Database reset complete"}


@router.get("/backup")
async def backup_database():
    db_path = str(settings.DATABASE_URL).replace("sqlite+aiosqlite:///", "")
    backup_dir = Path(settings.BACKUP_DIR)
    backup_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    backup_path = backup_dir / f"quran_tracker_{today}.db"

    shutil.copy2(db_path, backup_path)
    return {"message": "Backup created", "file": str(backup_path)}

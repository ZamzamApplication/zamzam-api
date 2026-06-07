from datetime import date, time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Circle, CircleSchedule, Session, Sheikh, Student, StudentSheikh, User, UserRole
from app.routers.auth import get_current_user_depends, pwd_context
from app.schemas import (
    CreateCircleRequest,
    CreateCircleScheduleRequest,
    CreateSheikhRequest,
    CreateStudentRequest,
    CreateUserRequest,
    UpdateCircleRequest,
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

    result = await db.execute(select(Sheikh).where(Sheikh.circle_id == circle_id).limit(1))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Cannot delete circle with associated sheikhs. Delete the sheikhs first.")

    result = await db.execute(select(Session).where(Session.circle_id == circle_id).limit(1))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Cannot delete circle with associated sessions. Delete the sessions first.")

    await db.delete(circle)
    await db.commit()
    return {"message": "Circle deleted"}


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
        .options(selectinload(StudentSheikh.student))
        .where(
            StudentSheikh.sheikh_id == sheikh_id,
            StudentSheikh.end_date.is_(None),
        )
    )
    records = result.scalars().all()
    return [
        {"id": r.student.id, "name": r.student.name, "phone": r.student.phone}
        for r in records
    ]


# ─── Students ───────────────────────────────────────────────────────────────

@router.get("/students")
async def list_students(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    result = await db.execute(
        select(Student)
        .options(
            selectinload(Student.sheikhs).selectinload(StudentSheikh.sheikh)
        )
        .order_by(Student.name)
    )
    students = result.scalars().all()
    return [
        {
            "id": s.id,
            "name": s.name,
            "phone": s.phone,
            "sheikh": {"id": s.sheikhs[0].sheikh.id, "name": s.sheikhs[0].sheikh.name} if s.sheikhs else None,
        }
        for s in students
    ]


@router.post("/students")
async def create_student(
    body: CreateStudentRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    student = Student(name=body.name, phone=body.phone)
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

    await db.commit()
    await db.refresh(student)
    return {"id": student.id, "name": student.name, "phone": student.phone}


@router.put("/students/{student_id}")
async def update_student(
    student_id: int,
    body: UpdateStudentRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    result = await db.execute(select(Student).where(Student.id == student_id))
    student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    if body.name is not None:
        student.name = body.name
    if body.phone is not None:
        student.phone = body.phone
    await db.commit()
    await db.refresh(student)
    return {"id": student.id, "name": student.name, "phone": student.phone}


@router.delete("/students/{student_id}")
async def delete_student(
    student_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_depends),
):
    result = await db.execute(select(Student).where(Student.id == student_id))
    student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    await db.delete(student)
    await db.commit()
    return {"message": "Student deleted"}


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

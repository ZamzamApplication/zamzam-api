from datetime import date, time

from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models import (
    Attendance,
    AttendanceStatus,
    Circle,
    CircleSchedule,
    Session,
    Sheikh,
    Student,
    StudentSheikh,
    User,
    UserRole,
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def seed_data():
    async with async_session() as db:
        result = await db.execute(select(Circle))
        if result.scalars().first():
            return

        circle = Circle(name="حلقة الفجر", description="حلقة تحفيظ القرآن الكريم بعد صلاة الفجر")
        db.add(circle)
        await db.flush()

        circle_schedule = CircleSchedule(circle_id=circle.id, day_of_week=0, time=time(5, 30))
        circle_schedule2 = CircleSchedule(circle_id=circle.id, day_of_week=2, time=time(5, 30))
        circle_schedule3 = CircleSchedule(circle_id=circle.id, day_of_week=4, time=time(5, 30))
        db.add_all([circle_schedule, circle_schedule2, circle_schedule3])

        admin_user = User(
            username="admin",
            hashed_password=pwd_context.hash("admin123"),
            role=UserRole.admin,
        )
        db.add(admin_user)

        sheikh1 = Sheikh(name="أحمد", circle_id=circle.id)
        db.add(sheikh1)
        await db.flush()

        sheikh1_user = User(
            username="ahmed",
            hashed_password=pwd_context.hash("ahmed123"),
            role=UserRole.sheikh,
            sheikh_id=sheikh1.id,
        )
        db.add(sheikh1_user)

        sheikh2 = Sheikh(name="محمد رزق", circle_id=circle.id)
        db.add(sheikh2)
        await db.flush()

        sheikh2_user = User(
            username="mohamed",
            hashed_password=pwd_context.hash("mohamed123"),
            role=UserRole.sheikh,
            sheikh_id=sheikh2.id,
        )
        db.add(sheikh2_user)

        sheikh3 = Sheikh(name="خالد", circle_id=circle.id)
        db.add(sheikh3)
        await db.flush()

        sheikh3_user = User(
            username="khaled",
            hashed_password=pwd_context.hash("khaled123"),
            role=UserRole.sheikh,
            sheikh_id=sheikh3.id,
        )
        db.add(sheikh3_user)

        students_data = [
            ("عبد الرحمن", "أحمد"),
            ("محمد", "أحمد"),
            ("عمر", "أحمد"),
            ("علي", "أحمد"),
            ("ياسر", "أحمد"),
            ("حسن", "أحمد"),
            ("مصطفى", "محمد رزق"),
            ("إبراهيم", "محمد رزق"),
            ("سليمان", "محمد رزق"),
            ("يوسف", "محمد رزق"),
            ("أيوب", "محمد رزق"),
            ("زكريا", "خالد"),
            ("إسماعيل", "خالد"),
            ("هارون", "خالد"),
            ("صالح", "خالد"),
            ("نوح", "خالد"),
        ]

        student_objects = []
        for name, sheikh_name in students_data:
            student = Student(name=name)
            db.add(student)
            await db.flush()
            student_objects.append((student, sheikh_name))

        for student, sheikh_name in student_objects:
            sheikh_result = await db.execute(select(Sheikh).where(Sheikh.name == sheikh_name))
            sheikh = sheikh_result.scalar_one()
            ss = StudentSheikh(
                student_id=student.id,
                sheikh_id=sheikh.id,
                start_date=date(2026, 1, 1),
            )
            db.add(ss)

        yesterday_session = Session(date=date(2026, 6, 2), circle_id=circle.id, is_confirmed=True)
        db.add(yesterday_session)
        await db.flush()

        for student, _ in student_objects:
            att = Attendance(
                session_id=yesterday_session.id,
                student_id=student.id,
                status=AttendanceStatus.present,
            )
            db.add(att)

        today_session = Session(date=date(2026, 6, 3), circle_id=circle.id)
        db.add(today_session)
        await db.flush()

        for student, _ in student_objects:
            att = Attendance(
                session_id=today_session.id,
                student_id=student.id,
                status=AttendanceStatus.absent,
            )
            db.add(att)

        await db.commit()

import enum
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class StudentStatus(str, enum.Enum):
    enrolled = "مقيد"
    excluded = "مستبعد"
    discontinued = "منقطع"
    guest = "ضيف"
    not_enrolled = "غير مقيد"


class AttendanceStatus(str, enum.Enum):
    present = "حاضر"  # noqa: F821
    absent = "غياب"  # noqa: F821
    excused = "غياب بعذر"  # noqa: F821
    not_applicable = "لا ينطبق"  # noqa: F821


class UserRole(str, enum.Enum):
    admin = "admin"
    sheikh = "sheikh"


class ParentType(str, enum.Enum):
    father = "أب"
    mother = "أم"
    brother = "أخ"
    sister = "أخت"
    grandfather = "جد"
    grandmother = "جدة"
    guardian = "أرضي"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.admin, nullable=False)
    sheikh_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("sheikhs.id"), nullable=True)


class Circle(Base):
    __tablename__ = "circles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    sheikhs: Mapped[list["Sheikh"]] = relationship("Sheikh", back_populates="circle", cascade="all, delete-orphan")


class Sheikh(Base):
    __tablename__ = "sheikhs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    circle_id: Mapped[int] = mapped_column(Integer, ForeignKey("circles.id"), nullable=False)

    circle: Mapped[Circle] = relationship("Circle", back_populates="sheikhs")
    students: Mapped[list["Student"]] = relationship("Student", back_populates="sheikh", foreign_keys="[Student.sheikh_id]")
    user: Mapped[User | None] = relationship("User", uselist=False, backref="sheikh")


class ExcusedWeekday(Base):
    __tablename__ = "excused_weekdays"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(Integer, ForeignKey("students.id"), nullable=False)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)

    student: Mapped["Student"] = relationship("Student", back_populates="excused_weekdays")


class Student(Base):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    student_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    birthday: Mapped[date | None] = mapped_column(Date, nullable=True)
    profile_pic: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[StudentStatus] = mapped_column(Enum(StudentStatus, values_callable=lambda x: [e.value for e in x]), default=StudentStatus.enrolled, nullable=False)
    registration_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    sheikh_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("sheikhs.id"), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    sheikh: Mapped[Sheikh | None] = relationship("Sheikh", back_populates="students")
    attendance_records: Mapped[list["Attendance"]] = relationship("Attendance", back_populates="student", cascade="all, delete-orphan")
    parent_phones: Mapped[list["ParentPhone"]] = relationship("ParentPhone", back_populates="student", cascade="all, delete-orphan")
    warnings: Mapped[list["StudentWarning"]] = relationship("StudentWarning", back_populates="student", cascade="all, delete-orphan", order_by="StudentWarning.created_at.desc()")
    excused_weekdays: Mapped[list["ExcusedWeekday"]] = relationship("ExcusedWeekday", back_populates="student", cascade="all, delete-orphan")


class StudentWarning(Base):
    __tablename__ = "student_warnings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(Integer, ForeignKey("students.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    student: Mapped[Student] = relationship("Student", back_populates="warnings")


class ParentPhone(Base):
    __tablename__ = "parent_phones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(Integer, ForeignKey("students.id"), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False)
    parent_type: Mapped[ParentType] = mapped_column(Enum(ParentType), nullable=False)
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    student: Mapped[Student] = relationship("Student", back_populates="parent_phones")


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    circle_id: Mapped[int] = mapped_column(Integer, ForeignKey("circles.id"), nullable=False, default=1)
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    circle: Mapped[Circle] = relationship("Circle")
    attendance_records: Mapped[list["Attendance"]] = relationship("Attendance", back_populates="session", cascade="all, delete-orphan")


class Attendance(Base):
    __tablename__ = "attendance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("sessions.id"), nullable=False)
    student_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("students.id"), nullable=True)
    sheikh_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("sheikhs.id"), nullable=True)
    status: Mapped[AttendanceStatus] = mapped_column(Enum(AttendanceStatus), default=AttendanceStatus.absent, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    session: Mapped[Session] = relationship("Session", back_populates="attendance_records")
    student: Mapped[Student] = relationship("Student", back_populates="attendance_records")
    session_sheikh: Mapped[Sheikh | None] = relationship("Sheikh")


class SavedFilter(Base):
    __tablename__ = "saved_filters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    data: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

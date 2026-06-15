import enum
from datetime import date, datetime, time

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Integer, String, Time, Text, SmallInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AttendanceStatus(str, enum.Enum):
    present = "حاضر"
    absent = "غياب"
    excused = "غياب بعذر"
    not_applicable = "لا ينطبق"


class ParentType(str, enum.Enum):
    father = "أب"
    mother = "أم"
    brother = "أخ"
    sister = "أخت"
    grandfather = "جد"
    grandmother = "جدة"
    landline = "أرضي"


class UserRole(str, enum.Enum):
    admin = "admin"
    sheikh = "sheikh"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), nullable=False)
    sheikh_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("sheikhs.id"), nullable=True)


class Circle(Base):
    __tablename__ = "circles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    sheikhs: Mapped[list["Sheikh"]] = relationship("Sheikh", back_populates="circle")
    schedules: Mapped[list["CircleSchedule"]] = relationship("CircleSchedule", back_populates="circle", cascade="all, delete-orphan")


class Sheikh(Base):
    __tablename__ = "sheikhs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    circle_id: Mapped[int] = mapped_column(Integer, ForeignKey("circles.id"), nullable=False)

    circle: Mapped[Circle] = relationship("Circle", back_populates="sheikhs")
    students: Mapped[list["StudentSheikh"]] = relationship("StudentSheikh", back_populates="sheikh", cascade="all, delete-orphan")
    user: Mapped[User | None] = relationship("User", uselist=False, backref="sheikh")


class Student(Base):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    student_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    birthday: Mapped[date | None] = mapped_column(Date, nullable=True)
    profile_pic: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_enrolled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    sheikhs: Mapped[list["StudentSheikh"]] = relationship("StudentSheikh", back_populates="student", cascade="all, delete-orphan")
    attendance_records: Mapped[list["Attendance"]] = relationship("Attendance", back_populates="student", cascade="all, delete-orphan")
    parent_phones: Mapped[list["ParentPhone"]] = relationship("ParentPhone", back_populates="student", cascade="all, delete-orphan")
    warnings: Mapped[list["StudentWarning"]] = relationship("StudentWarning", back_populates="student", cascade="all, delete-orphan", order_by="StudentWarning.created_at.desc()")


class StudentWarning(Base):
    __tablename__ = "student_warnings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(Integer, ForeignKey("students.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    student: Mapped[Student] = relationship("Student", back_populates="warnings")


class StudentSheikh(Base):
    __tablename__ = "student_sheikhs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(Integer, ForeignKey("students.id"), nullable=False)
    sheikh_id: Mapped[int] = mapped_column(Integer, ForeignKey("sheikhs.id"), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    student: Mapped[Student] = relationship("Student", back_populates="sheikhs")
    sheikh: Mapped[Sheikh] = relationship("Sheikh", back_populates="students")


class ParentPhone(Base):
    __tablename__ = "parent_phones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(Integer, ForeignKey("students.id"), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False)
    parent_type: Mapped[ParentType] = mapped_column(Enum(ParentType), nullable=False)

    student: Mapped[Student] = relationship("Student", back_populates="parent_phones")


class CircleSchedule(Base):
    __tablename__ = "circle_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    circle_id: Mapped[int] = mapped_column(Integer, ForeignKey("circles.id"), nullable=False)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)
    time: Mapped[time] = mapped_column(Time, nullable=False)

    circle: Mapped[Circle] = relationship("Circle", back_populates="schedules")


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    circle_id: Mapped[int] = mapped_column(Integer, ForeignKey("circles.id"), nullable=False)
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    circle: Mapped[Circle] = relationship("Circle")
    attendance_records: Mapped[list["Attendance"]] = relationship("Attendance", back_populates="session", cascade="all, delete-orphan")


class Attendance(Base):
    __tablename__ = "attendance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("sessions.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(Integer, ForeignKey("students.id"), nullable=False)
    status: Mapped[AttendanceStatus] = mapped_column(Enum(AttendanceStatus), default=AttendanceStatus.absent, nullable=False)

    session: Mapped[Session] = relationship("Session", back_populates="attendance_records")
    student: Mapped[Student] = relationship("Student", back_populates="attendance_records")

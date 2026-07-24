import enum
import json
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
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


DEFAULT_ATTENDANCE_STATUSES = [status.value for status in AttendanceStatus]


def attendance_status_options(tahfiz: "Tahfiz") -> list[str]:
    try:
        values = json.loads(tahfiz.attendance_statuses)
    except (TypeError, ValueError):
        return DEFAULT_ATTENDANCE_STATUSES.copy()
    if not isinstance(values, list):
        return DEFAULT_ATTENDANCE_STATUSES.copy()
    normalized = [value.strip() for value in values if isinstance(value, str) and value.strip()]
    return normalized or DEFAULT_ATTENDANCE_STATUSES.copy()


class UserRole(str, enum.Enum):
    super_admin = "super_admin"
    admin = "admin"
    sheikh = "sheikh"


class FeedbackStatus(str, enum.Enum):
    open = "open"
    in_review = "in_review"
    resolved = "resolved"
    not_an_issue = "not_an_issue"


class FeedbackCategory(str, enum.Enum):
    bug = "bug"
    suggestion = "suggestion"
    other = "other"


class TahfizStatus(str, enum.Enum):
    pending = "pending"
    active = "active"
    rejected = "rejected"
    suspended = "suspended"


class ProgressCategory(str, enum.Enum):
    new_memorization = "new_memorization"
    recent_revision = "recent_revision"
    old_revision = "old_revision"
    test = "test"


class QuranRangeType(str, enum.Enum):
    surah_ayah = "surah_ayah"
    page = "page"


class StudentGoalStatus(str, enum.Enum):
    active = "active"
    completed = "completed"
    cancelled = "cancelled"


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
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sheikh_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("sheikhs.id"), nullable=True)
    tahfiz_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("tahfiz.id"), nullable=True, index=True)
    default_tahfiz_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("tahfiz.id"), nullable=True)

    tahfiz: Mapped["Tahfiz | None"] = relationship("Tahfiz", foreign_keys=[tahfiz_id], back_populates="users")
    memberships: Mapped[list["UserTahfizMembership"]] = relationship(
        "UserTahfizMembership",
        foreign_keys="UserTahfizMembership.user_id",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class Tahfiz(Base):
    __tablename__ = "tahfiz"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[TahfizStatus] = mapped_column(Enum(TahfizStatus), default=TahfizStatus.pending, nullable=False, index=True)
    max_warnings: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    week_start_day: Mapped[int] = mapped_column(Integer, default=6, nullable=False)
    month_start_day: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    attendance_statuses: Mapped[str] = mapped_column(
        Text,
        default=lambda: json.dumps(DEFAULT_ATTENDANCE_STATUSES, ensure_ascii=False),
        nullable=False,
    )
    owner_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    whatsend_api_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    whatsend_groups_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    whatsend_api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress_tracking_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    sheikhs: Mapped[list["Sheikh"]] = relationship("Sheikh", back_populates="tahfiz", cascade="all, delete-orphan")
    users: Mapped[list["User"]] = relationship("User", foreign_keys=[User.tahfiz_id], back_populates="tahfiz")
    memberships: Mapped[list["UserTahfizMembership"]] = relationship(
        "UserTahfizMembership",
        back_populates="tahfiz",
        cascade="all, delete-orphan",
    )


class Sheikh(Base):
    __tablename__ = "sheikhs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    whatsapp_group_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tahfiz_id: Mapped[int] = mapped_column(Integer, ForeignKey("tahfiz.id"), nullable=False, index=True)

    tahfiz: Mapped[Tahfiz] = relationship("Tahfiz", back_populates="sheikhs")
    students: Mapped[list["Student"]] = relationship("Student", back_populates="sheikh", foreign_keys="[Student.sheikh_id]")
    user: Mapped[User | None] = relationship("User", uselist=False, backref="sheikh")


class UserTahfizMembership(Base):
    __tablename__ = "user_tahfiz_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "tahfiz_id", name="uq_user_tahfiz_membership"),
        Index("ix_user_tahfiz_memberships_tahfiz_role", "tahfiz_id", "role", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    tahfiz_id: Mapped[int] = mapped_column(Integer, ForeignKey("tahfiz.id"), nullable=False, index=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), nullable=False)
    sheikh_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("sheikhs.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    user: Mapped[User] = relationship("User", foreign_keys=[user_id], back_populates="memberships")
    tahfiz: Mapped[Tahfiz] = relationship("Tahfiz", back_populates="memberships")
    sheikh: Mapped[Sheikh | None] = relationship("Sheikh")


class TahfizInvitation(Base):
    __tablename__ = "tahfiz_invitations"
    __table_args__ = (
        Index("ix_tahfiz_invitations_tahfiz_status", "tahfiz_id", "used_at", "revoked_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tahfiz_id: Mapped[int] = mapped_column(Integer, ForeignKey("tahfiz.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), nullable=False)
    sheikh_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("sheikhs.id"), nullable=True)
    created_by_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    used_by_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    tahfiz: Mapped[Tahfiz] = relationship("Tahfiz")
    sheikh: Mapped[Sheikh | None] = relationship("Sheikh")


class ExcusedWeekday(Base):
    __tablename__ = "excused_weekdays"
    __table_args__ = (
        UniqueConstraint("student_id", "weekday", name="uq_excused_weekday_student_day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(Integer, ForeignKey("students.id"), nullable=False)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    student: Mapped["Student"] = relationship("Student", back_populates="excused_weekdays")


class Student(Base):
    __tablename__ = "students"
    __table_args__ = (
        Index("ix_students_tahfiz_sheikh_status_order", "tahfiz_id", "sheikh_id", "status", "sort_order"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    student_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    birthday: Mapped[date | None] = mapped_column(Date, nullable=True)
    profile_pic: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[StudentStatus] = mapped_column(Enum(StudentStatus, values_callable=lambda x: [e.value for e in x]), default=StudentStatus.enrolled, nullable=False)
    registration_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    sheikh_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("sheikhs.id"), nullable=True)
    tahfiz_id: Mapped[int] = mapped_column(Integer, ForeignKey("tahfiz.id"), nullable=False, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    sheikh: Mapped[Sheikh | None] = relationship("Sheikh", back_populates="students")
    attendance_records: Mapped[list["Attendance"]] = relationship("Attendance", back_populates="student", cascade="all, delete-orphan")
    parent_phones: Mapped[list["ParentPhone"]] = relationship("ParentPhone", back_populates="student", cascade="all, delete-orphan")
    warnings: Mapped[list["StudentWarning"]] = relationship("StudentWarning", back_populates="student", cascade="all, delete-orphan", order_by="StudentWarning.created_at.desc()")
    excused_weekdays: Mapped[list["ExcusedWeekday"]] = relationship("ExcusedWeekday", back_populates="student", cascade="all, delete-orphan")


class StudentWarning(Base):
    __tablename__ = "student_warnings"
    __table_args__ = (
        Index("ix_student_warnings_student_created", "student_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(Integer, ForeignKey("students.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    warning_number: Mapped[int] = mapped_column(Integer, nullable=False)
    sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
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
    __table_args__ = (
        Index("ix_sessions_tahfiz_confirmed_date", "tahfiz_id", "is_confirmed", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    tahfiz_id: Mapped[int] = mapped_column(Integer, ForeignKey("tahfiz.id"), nullable=False, index=True)
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reopened_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reopened_by_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    tahfiz: Mapped[Tahfiz] = relationship("Tahfiz")
    attendance_records: Mapped[list["Attendance"]] = relationship("Attendance", back_populates="session", cascade="all, delete-orphan")


class Attendance(Base):
    __tablename__ = "attendance"
    __table_args__ = (
        UniqueConstraint("session_id", "student_id", name="uq_attendance_session_student"),
        Index("ix_attendance_tahfiz_session", "tahfiz_id", "session_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("sessions.id"), nullable=False)
    student_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("students.id"), nullable=True)
    sheikh_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("sheikhs.id"), nullable=True)
    tahfiz_id: Mapped[int] = mapped_column(Integer, ForeignKey("tahfiz.id"), nullable=False, index=True)
    # This is intentionally a string: each Tahfiz can configure its own options.
    status: Mapped[str] = mapped_column(String(100), default=AttendanceStatus.absent.value, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    session: Mapped[Session] = relationship("Session", back_populates="attendance_records")
    student: Mapped[Student] = relationship("Student", back_populates="attendance_records")
    session_sheikh: Mapped[Sheikh | None] = relationship("Sheikh")


class SavedFilter(Base):
    __tablename__ = "saved_filters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    tahfiz_id: Mapped[int] = mapped_column(Integer, ForeignKey("tahfiz.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    data: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AttendanceBatchOperation(Base):
    __tablename__ = "attendance_batch_operations"
    __table_args__ = (
        UniqueConstraint("tahfiz_id", "idempotency_key", name="uq_attendance_batch_tenant_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tahfiz_id: Mapped[int] = mapped_column(Integer, ForeignKey("tahfiz.id"), nullable=False, index=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("sessions.id"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    resulting_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class QuranProgressEntry(Base):
    __tablename__ = "quran_progress_entries"
    __table_args__ = (
        UniqueConstraint("session_id", "student_id", "category", name="uq_progress_session_student_category"),
        Index("ix_progress_tahfiz_student_created", "tahfiz_id", "student_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tahfiz_id: Mapped[int] = mapped_column(Integer, ForeignKey("tahfiz.id"), nullable=False, index=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("sessions.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(Integer, ForeignKey("students.id"), nullable=False)
    sheikh_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("sheikhs.id"), nullable=True)
    recorded_by_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    category: Mapped[ProgressCategory] = mapped_column(Enum(ProgressCategory), nullable=False)
    range_type: Mapped[QuranRangeType] = mapped_column(Enum(QuranRangeType), nullable=False)
    from_surah: Mapped[int | None] = mapped_column(Integer, nullable=True)
    from_ayah: Mapped[int | None] = mapped_column(Integer, nullable=True)
    to_surah: Mapped[int | None] = mapped_column(Integer, nullable=True)
    to_ayah: Mapped[int | None] = mapped_column(Integer, nullable=True)
    from_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    to_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quality_score: Mapped[int] = mapped_column(Integer, nullable=False)
    mistakes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_assignment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class QuranProgressRevision(Base):
    __tablename__ = "quran_progress_revisions"
    __table_args__ = (
        Index("ix_progress_revision_tahfiz_student_created", "tahfiz_id", "student_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tahfiz_id: Mapped[int] = mapped_column(Integer, ForeignKey("tahfiz.id"), nullable=False, index=True)
    progress_entry_id: Mapped[int] = mapped_column(Integer, ForeignKey("quran_progress_entries.id"), nullable=False)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("sessions.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(Integer, ForeignKey("students.id"), nullable=False)
    category: Mapped[ProgressCategory] = mapped_column(Enum(ProgressCategory), nullable=False)
    editor_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    before_json: Mapped[str] = mapped_column(Text, nullable=False)
    after_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class StudentGoal(Base):
    __tablename__ = "student_goals"
    __table_args__ = (
        Index("ix_student_goals_tahfiz_student_status", "tahfiz_id", "student_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tahfiz_id: Mapped[int] = mapped_column(Integer, ForeignKey("tahfiz.id"), nullable=False, index=True)
    student_id: Mapped[int] = mapped_column(Integer, ForeignKey("students.id"), nullable=False)
    range_type: Mapped[QuranRangeType] = mapped_column(Enum(QuranRangeType), nullable=False)
    from_surah: Mapped[int | None] = mapped_column(Integer, nullable=True)
    from_ayah: Mapped[int | None] = mapped_column(Integer, nullable=True)
    to_surah: Mapped[int | None] = mapped_column(Integer, nullable=True)
    to_ayah: Mapped[int | None] = mapped_column(Integer, nullable=True)
    from_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    to_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[StudentGoalStatus] = mapped_column(Enum(StudentGoalStatus), default=StudentGoalStatus.active, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    tahfiz_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("tahfiz.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class FeedbackReport(Base):
    __tablename__ = "feedback_reports"
    __table_args__ = (
        Index("ix_feedback_reports_status_created", "status", "created_at"),
        Index("ix_feedback_reports_tahfiz_created", "tahfiz_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reporter_user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reporter_username: Mapped[str] = mapped_column(String(50), nullable=False)
    tahfiz_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("tahfiz.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    category: Mapped[FeedbackCategory] = mapped_column(Enum(FeedbackCategory), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    page_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[FeedbackStatus] = mapped_column(
        Enum(FeedbackStatus),
        default=FeedbackStatus.open,
        nullable=False,
        index=True,
    )
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class DeviceSession(Base):
    __tablename__ = "device_sessions"
    __table_args__ = (
        Index("ix_device_sessions_user_revoked", "user_id", "revoked_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String(100), nullable=False)
    device_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_used_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class SyncChange(Base):
    __tablename__ = "sync_changes"
    __table_args__ = (
        Index("ix_sync_changes_tahfiz_cursor", "tahfiz_id", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tahfiz_id: Mapped[int] = mapped_column(Integer, ForeignKey("tahfiz.id"), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_key: Mapped[str] = mapped_column(String(160), nullable=False)
    operation: Mapped[str] = mapped_column(String(10), nullable=False)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class SyncMutationReceipt(Base):
    __tablename__ = "sync_mutation_receipts"
    __table_args__ = (
        UniqueConstraint("tahfiz_id", "mutation_id", name="uq_sync_mutation_tenant_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tahfiz_id: Mapped[int] = mapped_column(Integer, ForeignKey("tahfiz.id"), nullable=False, index=True)
    mutation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    device_id: Mapped[str] = mapped_column(String(100), nullable=False)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

import enum
import json
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.time import utcnow


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
DEFAULT_PRESENT_STATUS = AttendanceStatus.present.value
DEFAULT_EXCUSED_ABSENCE_STREAK_LIMIT = 3
DEFAULT_EXCUSED_ABSENCE_RESET_STATUSES = [AttendanceStatus.present.value]
DEFAULT_ATTENDANCE_STREAK_STATUS = AttendanceStatus.excused.value
ATTENDANCE_STATUS_COLOR_KEYS = ("green", "slate", "amber", "sky", "violet", "rose")
DEFAULT_ATTENDANCE_STATUS_COLORS = {
    AttendanceStatus.present.value: "green",
    AttendanceStatus.absent.value: "slate",
    AttendanceStatus.excused.value: "amber",
    AttendanceStatus.not_applicable.value: "sky",
}
DEFAULT_EXPENSE_CATEGORIES = [
    {"id": "rent", "label": "إيجار", "enabled": True},
    {"id": "salaries", "label": "رواتب", "enabled": True},
    {"id": "utilities", "label": "مرافق", "enabled": True},
    {"id": "maintenance", "label": "صيانة", "enabled": True},
    {"id": "supplies", "label": "مستلزمات", "enabled": True},
    {"id": "transportation", "label": "انتقالات", "enabled": True},
    {"id": "other", "label": "أخرى", "enabled": True},
]
DEFAULT_EXCEL_EXPORT_TEMPLATES = {
    "attendance": {
        "header_font_family": "Arial",
        "header_font_size": 12,
        "header_bold": True,
        "header_background_color": "#FFFFFF",
        "header_font_color": "#000000",
        "cell_font_family": "Arial",
        "cell_font_size": 11,
        "cell_bold": False,
        "cell_font_color": "#000000",
        "date_font_family": "Arial",
        "date_font_size": 12,
        "date_bold": True,
        "date_font_color": "#000000",
        "attendance_date_format": "weekday_day_month_year",
        "columns": [
            {"id": "serial", "label": "م", "enabled": False, "custom": False, "width": 6, "header_font_family": "Arial"},
            {"id": "student", "label": "الطالب", "enabled": True, "custom": False, "width": 24, "header_font_family": "Arial"},
            {"id": "sheikh", "label": "الشيخ", "enabled": True, "custom": False, "width": 20, "header_font_family": "Arial"},
            {"id": "subscription_amount", "label": "مبلغ الاشتراك", "enabled": True, "custom": False, "width": 16, "header_font_family": "Arial"},
            {
                "id": "memorization", "label": "الحفظ", "enabled": True, "custom": False,
                "width": 18, "header_font_family": "Arial",
                "subcolumns": [
                    {"id": "from", "label": "من", "width": 18},
                    {"id": "to", "label": "إلى", "width": 18},
                ],
            },
            {
                "id": "revision", "label": "المراجعة", "enabled": True, "custom": False,
                "width": 18, "header_font_family": "Arial",
                "subcolumns": [
                    {"id": "from", "label": "من", "width": 18},
                    {"id": "to", "label": "إلى", "width": 18},
                ],
            },
            {"id": "attendance", "label": "الحضور", "enabled": True, "custom": False, "width": 18, "header_font_family": "Arial"},
        ],
    },
    "statistics": {
        "header_font_family": "Arial",
        "header_font_size": 12,
        "header_bold": True,
        "header_background_color": "#FFFFFF",
        "header_font_color": "#000000",
        "cell_font_family": "Arial",
        "cell_font_size": 11,
        "cell_bold": False,
        "cell_font_color": "#000000",
        "date_font_family": "Arial",
        "date_font_size": 12,
        "date_bold": True,
        "date_font_color": "#000000",
        "attendance_date_format": "weekday_day_month_year",
        "columns": [
            {"id": "serial", "label": "م", "enabled": False, "custom": False, "width": 6, "header_font_family": "Arial"},
            {"id": "student", "label": "الطالب", "enabled": True, "custom": False, "width": 24, "header_font_family": "Arial"},
            {"id": "sheikh", "label": "الشيخ", "enabled": True, "custom": False, "width": 20, "header_font_family": "Arial"},
            {"id": "sessions", "label": "إجمالي الحلقات", "enabled": True, "custom": False, "width": 16, "header_font_family": "Arial"},
            {"id": "statuses", "label": "حالات الحضور", "enabled": True, "custom": False, "width": 14, "header_font_family": "Arial"},
            {"id": "rate", "label": "نسبة الحضور", "enabled": True, "custom": False, "width": 16, "header_font_family": "Arial"},
        ],
    },
    "progress": {
        "header_font_family": "Arial",
        "header_font_size": 12,
        "header_bold": True,
        "header_background_color": "#FFFFFF",
        "header_font_color": "#000000",
        "cell_font_family": "Arial",
        "cell_font_size": 11,
        "cell_bold": False,
        "cell_font_color": "#000000",
        "date_font_family": "Arial",
        "date_font_size": 12,
        "date_bold": True,
        "date_font_color": "#000000",
        "attendance_date_format": "weekday_day_month_year",
        "columns": [
            {"id": "serial", "label": "م", "enabled": False, "custom": False, "width": 6, "header_font_family": "Arial"},
            {"id": "student", "label": "الطالب", "enabled": True, "custom": False, "width": 24, "header_font_family": "Arial"},
            {"id": "entries", "label": "عدد سجلات المتابعة", "enabled": True, "custom": False, "width": 20, "header_font_family": "Arial"},
            {"id": "quality", "label": "متوسط التقييم", "enabled": True, "custom": False, "width": 18, "header_font_family": "Arial"},
            {"id": "mistakes", "label": "إجمالي الأخطاء", "enabled": True, "custom": False, "width": 18, "header_font_family": "Arial"},
            {"id": "latestRange", "label": "آخر مقدار", "enabled": True, "custom": False, "width": 28, "header_font_family": "Arial"},
        ],
    },
}


def attendance_status_options(tahfiz: "Tahfiz") -> list[str]:
    try:
        values = json.loads(tahfiz.attendance_statuses)
    except (TypeError, ValueError):
        return DEFAULT_ATTENDANCE_STATUSES.copy()
    if not isinstance(values, list):
        return DEFAULT_ATTENDANCE_STATUSES.copy()
    normalized = [value.strip() for value in values if isinstance(value, str) and value.strip()]
    return normalized or DEFAULT_ATTENDANCE_STATUSES.copy()


def excel_export_template_options(tahfiz: "Tahfiz") -> dict:
    try:
        values = json.loads(tahfiz.excel_export_templates)
    except (AttributeError, TypeError, ValueError):
        values = {}
    if not isinstance(values, dict):
        values = {}
    templates: dict[str, dict] = {}
    for key, default in DEFAULT_EXCEL_EXPORT_TEMPLATES.items():
        configured = values.get(key)
        if not isinstance(configured, dict) or not isinstance(configured.get("columns"), list):
            templates[key] = json.loads(json.dumps(default))
            continue
        template = json.loads(json.dumps(configured))
        for setting, setting_default in default.items():
            if setting != "columns" and setting not in template:
                template[setting] = setting_default
        if key == "attendance":
            semantic_labels = {"الحفظ": "memorization", "المراجعة": "revision"}
            for column in template["columns"]:
                normalized_label = str(column.get("label", "")).strip()
                semantic_id = semantic_labels.get(normalized_label)
                subcolumns = column.get("subcolumns")
                if not semantic_id or not column.get("custom") or not isinstance(subcolumns, list) or len(subcolumns) != 2:
                    continue
                normalized_subcolumn_labels = [str(item.get("label", "")).strip().replace("الي", "إلى") for item in subcolumns]
                if normalized_subcolumn_labels != ["من", "إلى"]:
                    continue
                column["id"] = semantic_id
                column["custom"] = False
                column["subcolumns"] = [
                    {**subcolumns[0], "id": "from", "label": "من"},
                    {**subcolumns[1], "id": "to", "label": "إلى"},
                ]
        fallback_header_font = str(template.get("header_font_family") or default["header_font_family"])
        for column in template["columns"]:
            if isinstance(column, dict) and not str(column.get("header_font_family") or "").strip():
                column["header_font_family"] = fallback_header_font
        configured_ids = {
            column.get("id")
            for column in template["columns"]
            if isinstance(column, dict)
        }
        missing_columns = [
            json.loads(json.dumps(column))
            for column in default["columns"]
            if column["id"] not in configured_ids
        ]
        template["columns"] = missing_columns + template["columns"]
        templates[key] = template
    return templates


def expense_category_options(tahfiz: "Tahfiz") -> list[dict]:
    try:
        values = json.loads(tahfiz.expense_categories)
    except (AttributeError, TypeError, ValueError):
        values = []
    if not isinstance(values, list):
        values = []
    normalized = [
        {"id": value["id"].strip(), "label": value["label"].strip(), "enabled": value.get("enabled", True) is not False}
        for value in values
        if isinstance(value, dict)
        and isinstance(value.get("id"), str)
        and value["id"].strip()
        and isinstance(value.get("label"), str)
        and value["label"].strip()
    ]
    return normalized or json.loads(json.dumps(DEFAULT_EXPENSE_CATEGORIES, ensure_ascii=False))


def excused_absence_reset_status_options(tahfiz: "Tahfiz") -> list[str]:
    try:
        values = json.loads(tahfiz.excused_absence_reset_statuses)
    except (TypeError, ValueError):
        return DEFAULT_EXCUSED_ABSENCE_RESET_STATUSES.copy()
    if not isinstance(values, list):
        return DEFAULT_EXCUSED_ABSENCE_RESET_STATUSES.copy()
    normalized = [
        value.strip()
        for value in values
        if isinstance(value, str)
        and value.strip()
        and value.strip() != attendance_streak_status_option(tahfiz)
    ]
    return list(dict.fromkeys(normalized))


def attendance_streak_status_option(tahfiz: "Tahfiz") -> str:
    statuses = attendance_status_options(tahfiz)
    configured = (tahfiz.attendance_streak_status or "").strip()
    if configured in statuses:
        return configured
    if DEFAULT_ATTENDANCE_STREAK_STATUS in statuses:
        return DEFAULT_ATTENDANCE_STREAK_STATUS
    return statuses[0]


def present_status_option(tahfiz: "Tahfiz") -> str:
    statuses = attendance_status_options(tahfiz)
    configured = (getattr(tahfiz, "present_status", None) or "").strip()
    if configured in statuses:
        return configured
    if DEFAULT_PRESENT_STATUS in statuses:
        return DEFAULT_PRESENT_STATUS
    colors = attendance_status_color_options(tahfiz)
    green_status = next((status for status in statuses if colors.get(status) == "green"), None)
    if green_status:
        return green_status
    return statuses[0]


def attendance_status_color_options(tahfiz: "Tahfiz") -> dict[str, str]:
    statuses = attendance_status_options(tahfiz)
    try:
        values = json.loads(tahfiz.attendance_status_colors)
    except (TypeError, ValueError):
        values = {}
    if not isinstance(values, dict):
        values = {}
    return {
        status: (
            values.get(status)
            if values.get(status) in ATTENDANCE_STATUS_COLOR_KEYS
            else DEFAULT_ATTENDANCE_STATUS_COLORS.get(status, "violet")
        )
        for status in statuses
    }


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


class WardIncrementUnit(str, enum.Enum):
    ayahs = "ayahs"
    lines = "lines"
    pages = "pages"


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
    auth_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

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
    excused_absence_streak_limit: Mapped[int] = mapped_column(
        Integer,
        default=DEFAULT_EXCUSED_ABSENCE_STREAK_LIMIT,
        nullable=False,
    )
    excused_absence_reset_statuses: Mapped[str] = mapped_column(
        Text,
        default=lambda: json.dumps(DEFAULT_EXCUSED_ABSENCE_RESET_STATUSES, ensure_ascii=False),
        nullable=False,
    )
    attendance_status_colors: Mapped[str] = mapped_column(
        Text,
        default=lambda: json.dumps(DEFAULT_ATTENDANCE_STATUS_COLORS, ensure_ascii=False),
        nullable=False,
    )
    excel_export_templates: Mapped[str] = mapped_column(
        Text,
        default=lambda: json.dumps(DEFAULT_EXCEL_EXPORT_TEMPLATES, ensure_ascii=False),
        nullable=False,
    )
    attendance_streak_alert_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    attendance_sheikh_selection_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    restrict_sheikh_student_access: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    attendance_streak_status: Mapped[str] = mapped_column(
        String(50),
        default=DEFAULT_ATTENDANCE_STREAK_STATUS,
        nullable=False,
    )
    present_status: Mapped[str] = mapped_column(
        String(50),
        default=DEFAULT_PRESENT_STATUS,
        nullable=False,
    )
    owner_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    whatsend_api_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    whatsend_groups_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    whatsend_api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    whatsend_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    progress_tracking_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    subscriptions_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    subscription_default_fee_minor: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    subscription_currency: Mapped[str] = mapped_column(String(3), default="EGP", nullable=False)
    expense_categories: Mapped[str] = mapped_column(
        Text,
        default=lambda: json.dumps(DEFAULT_EXPENSE_CATEGORIES, ensure_ascii=False),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

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
    students: Mapped[list["Student"]] = relationship(
        "Student",
        back_populates="sheikh",
        foreign_keys="[Student.sheikh_id]",
        order_by="Student.name",
    )
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
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
    subscription_fee_override_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)

    sheikh: Mapped[Sheikh | None] = relationship("Sheikh", back_populates="students")
    attendance_records: Mapped[list["Attendance"]] = relationship("Attendance", back_populates="student", cascade="all, delete-orphan")
    parent_phones: Mapped[list["ParentPhone"]] = relationship("ParentPhone", back_populates="student", cascade="all, delete-orphan")
    warnings: Mapped[list["StudentWarning"]] = relationship("StudentWarning", back_populates="student", cascade="all, delete-orphan", order_by="StudentWarning.created_at.desc()")
    excused_weekdays: Mapped[list["ExcusedWeekday"]] = relationship("ExcusedWeekday", back_populates="student", cascade="all, delete-orphan")
    excused_periods: Mapped[list["StudentExcusedPeriod"]] = relationship("StudentExcusedPeriod", back_populates="student", cascade="all, delete-orphan")
    quran_plans: Mapped[list["StudentQuranPlan"]] = relationship("StudentQuranPlan", back_populates="student", cascade="all, delete-orphan")


class StudentSubscription(Base):
    __tablename__ = "student_subscriptions"
    __table_args__ = (
        UniqueConstraint(
            "tahfiz_id",
            "student_snapshot_id",
            "period_start",
            name="uq_student_subscriptions_tenant_student_period",
        ),
        Index(
            "ix_student_subscriptions_tenant_period_paid",
            "tahfiz_id",
            "period_start",
            "is_paid",
        ),
        Index(
            "ix_student_subscriptions_tenant_student",
            "tahfiz_id",
            "student_id",
        ),
        CheckConstraint("amount_due_minor >= 0", name="ck_student_subscriptions_amount_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tahfiz_id: Mapped[int] = mapped_column(Integer, ForeignKey("tahfiz.id"), nullable=False, index=True)
    student_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("students.id", ondelete="SET NULL"),
        nullable=True,
    )
    student_snapshot_id: Mapped[int] = mapped_column(Integer, nullable=False)
    student_name: Mapped[str] = mapped_column(String(100), nullable=False)
    student_custom_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    student_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    sheikh_id_snapshot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sheikh_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    amount_due_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    is_paid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    payment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    paid_by_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    payment_method: Mapped[str | None] = mapped_column(String(30), nullable=True)
    payment_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    receipt_number: Mapped[str | None] = mapped_column(String(80), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class Expense(Base):
    __tablename__ = "expenses"
    __table_args__ = (
        Index("ix_expenses_tenant_date_deleted", "tahfiz_id", "expense_date", "deleted_at"),
        Index("ix_expenses_tenant_method_date", "tahfiz_id", "payment_method", "expense_date"),
        CheckConstraint("amount_minor > 0", name="ck_expenses_amount_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tahfiz_id: Mapped[int] = mapped_column(Integer, ForeignKey("tahfiz.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category_id: Mapped[str] = mapped_column(String(80), nullable=False)
    category_label_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    expense_date: Mapped[date] = mapped_column(Date, nullable=False)
    payment_method: Mapped[str] = mapped_column(String(30), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    updated_by_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    deleted_by_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class StudentExcusedPeriod(Base):
    __tablename__ = "student_excused_periods"
    __table_args__ = (
        Index("ix_student_excused_periods_tenant_student_dates", "tahfiz_id", "student_id", "start_date", "end_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(Integer, ForeignKey("students.id"), nullable=False)
    tahfiz_id: Mapped[int] = mapped_column(Integer, ForeignKey("tahfiz.id"), nullable=False, index=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_by_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    student: Mapped["Student"] = relationship("Student", back_populates="excused_periods")


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

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
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class StudentQuranPlan(Base):
    __tablename__ = "student_quran_plans"
    __table_args__ = (
        UniqueConstraint("tahfiz_id", "student_id", "category", name="uq_student_quran_plan_category"),
        Index("ix_student_quran_plans_tenant_student", "tahfiz_id", "student_id"),
        CheckConstraint("increment_amount > 0", name="ck_student_quran_plan_positive_increment"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tahfiz_id: Mapped[int] = mapped_column(Integer, ForeignKey("tahfiz.id"), nullable=False, index=True)
    student_id: Mapped[int] = mapped_column(Integer, ForeignKey("students.id"), nullable=False)
    category: Mapped[ProgressCategory] = mapped_column(Enum(ProgressCategory), nullable=False)
    increment_unit: Mapped[WardIncrementUnit] = mapped_column(Enum(WardIncrementUnit), nullable=False)
    increment_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    next_surah: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_ayah: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_advanced_session_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    student: Mapped[Student] = relationship("Student", back_populates="quran_plans")


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_tahfiz_created", "tahfiz_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    tahfiz_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("tahfiz.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        onupdate=utcnow,
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
    last_used_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class AuthRateLimit(Base):
    __tablename__ = "auth_rate_limits"

    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

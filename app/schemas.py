from datetime import date, datetime, time
import json
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ParentPhoneOut(BaseModel):
    id: int
    phone_number: str
    parent_type: str
    name: str | None = None

    class Config:
        from_attributes = True


class CreateParentPhone(BaseModel):
    phone_number: str = Field(min_length=3, max_length=20)
    parent_type: Literal["أب", "أم", "أخ", "أخت", "جد", "جدة", "أرضي"]
    name: str | None = Field(default=None, max_length=100)


class UpdateParentPhone(BaseModel):
    phone_number: str | None = Field(default=None, min_length=3, max_length=20)
    parent_type: Literal["أب", "أم", "أخ", "أخت", "جد", "جدة", "أرضي"] | None = None
    name: str | None = Field(default=None, max_length=100)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    refresh_token: str | None = None
    expires_in: int | None = None


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=200)
    device_id: str | None = Field(default=None, min_length=8, max_length=100)
    device_name: str | None = Field(default=None, max_length=100)


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(min_length=32, max_length=500)
    device_id: str = Field(min_length=8, max_length=100)


class RevokeDeviceRequest(BaseModel):
    refresh_token: str = Field(min_length=32, max_length=500)


class SignupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=200)
    tahfiz_name: str = Field(min_length=2, max_length=100)
    contact_phone: str | None = Field(default=None, max_length=20)


class TahfizOut(BaseModel):
    id: int
    name: str
    description: str | None = None
    contact_phone: str | None = None
    status: str = "pending"
    max_warnings: int = 3
    week_start_day: int = 6
    month_start_day: int = 1
    attendance_statuses: list[str] = Field(default_factory=lambda: ["حاضر", "غياب", "غياب بعذر", "لا ينطبق"])
    excused_absence_streak_limit: int = 3
    excused_absence_reset_statuses: list[str] = Field(default_factory=lambda: ["حاضر"])
    attendance_streak_alert_enabled: bool = True
    attendance_sheikh_selection_enabled: bool = True
    restrict_sheikh_student_access: bool = True
    attendance_streak_status: str = "غياب بعذر"
    attendance_streak_limit: int = 3
    attendance_streak_reset_statuses: list[str] = Field(default_factory=lambda: ["حاضر"])
    attendance_status_colors: dict[str, str] = Field(default_factory=lambda: {
        "حاضر": "green",
        "غياب": "slate",
        "غياب بعذر": "amber",
        "لا ينطبق": "sky",
    })
    excel_export_templates: dict = Field(default_factory=dict)
    whatsend_enabled: bool = True

    class Config:
        from_attributes = True


class SheikhOut(BaseModel):
    id: int
    name: str
    phone: str | None = None
    whatsapp_group_id: str | None = None

    class Config:
        from_attributes = True


class WarningOut(BaseModel):
    id: int
    reason: str
    warning_number: int
    sent: bool = False
    sent_at: datetime | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class ExcusedWeekdayOut(BaseModel):
    id: int | None = None
    weekday: int
    note: str | None = None

    class Config:
        from_attributes = True


class ExcusedPeriodOut(BaseModel):
    id: int
    student_id: int
    start_date: date
    end_date: date
    reason: str
    status: Literal["upcoming", "active", "completed", "cancelled"]
    cancelled_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class CreateExcusedPeriodRequest(BaseModel):
    start_date: date
    end_date: date
    reason: str = Field(min_length=2, max_length=1000)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_dates(self):
        if self.end_date < self.start_date:
            raise ValueError("End date must be on or after start date")
        return self


class UpdateExcusedPeriodRequest(CreateExcusedPeriodRequest):
    pass


class EarlyReturnRequest(BaseModel):
    end_date: date


class StudentOut(BaseModel):
    id: int
    name: str
    phone: str | None = None
    student_id: str | None = None
    birthday: date | None = None
    profile_pic: str | None = None
    status: str = "مقيد"
    registration_date: date | None = None
    warnings: list[WarningOut] = Field(default_factory=list)
    parent_phones: list[ParentPhoneOut] = Field(default_factory=list)
    excused_weekdays: list[ExcusedWeekdayOut] = Field(default_factory=list)
    excused_periods: list[ExcusedPeriodOut] = Field(default_factory=list)

    class Config:
        from_attributes = True


class AttendanceOut(BaseModel):
    id: int
    session_id: int
    student_id: int
    student_name: str
    status: str
    notes: str | None = None
    sheikh_id: int | None = None

    class Config:
        from_attributes = True


class SheikhWithStudents(BaseModel):
    sheikh: SheikhOut
    students: list[StudentOut]


class SessionAttendanceOut(BaseModel):
    session_id: int
    session_date: date
    is_confirmed: bool
    sheikh_groups: list[SheikhWithStudents]


class SessionOut(BaseModel):
    id: int
    tahfiz_id: int
    session_date: date
    is_confirmed: bool
    created_at: str

    class Config:
        from_attributes = True


class UpdateAttendanceRequest(BaseModel):
    status: str = Field(min_length=1, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)
    sheikh_id: int | None = None


class UpsertAttendanceRequest(BaseModel):
    session_id: int
    student_id: int
    status: str = Field(min_length=1, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)
    sheikh_id: int | None = None


class AttendanceBatchItem(BaseModel):
    student_id: int
    status: str = Field(min_length=1, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)
    sheikh_id: int | None = None


class AttendanceBatchRequest(BaseModel):
    session_id: int
    expected_version: int | None = Field(default=None, ge=0)
    updates: list[AttendanceBatchItem] = Field(min_length=1, max_length=500)


class CreateSessionRequest(BaseModel):
    circle_id: int | None = None  # Legacy cached-client compatibility
    session_date: date
    session_time: time | None = None
    default_status: str = Field(default="غياب", min_length=1, max_length=100)


class UpdateSessionRequest(BaseModel):
    session_date: date


class ReopenSessionRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    expected_version: int | None = Field(default=None, ge=0)


class ConfirmSessionRequest(BaseModel):
    confirm: bool = True
    expected_version: int | None = Field(default=None, ge=0)


class CreateSheikhRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=20)
    whatsapp_group_id: str | None = Field(default=None, max_length=255)
    circle_id: int | None = None  # Legacy cached-client compatibility


class CreateStudentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=20)
    student_id: str | None = Field(default=None, max_length=50)
    birthday: date | None = None
    status: Literal["مقيد", "مستبعد", "منقطع", "ضيف", "غير مقيد"] = "مقيد"
    registration_date: date | None = None
    sheikh_id: int | None = None
    parent_phones: list[CreateParentPhone] = Field(default_factory=list, max_length=20)


class CreateWarningRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class MoveStudentRequest(BaseModel):
    sheikh_id: int


class ReorderStudentsRequest(BaseModel):
    student_ids: list[int] = Field(max_length=1000)


class UpdateTahfizRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=255)
    contact_phone: str | None = Field(default=None, max_length=20)
    max_warnings: int = Field(default=3, ge=1, le=1000)
    week_start_day: int = Field(default=6, ge=0, le=6)
    month_start_day: int = Field(default=1, ge=1, le=28)
    attendance_statuses: list[str] | None = Field(default=None, max_length=20)
    whatsend_api_url: str | None = Field(default=None, max_length=500)
    whatsend_groups_url: str | None = Field(default=None, max_length=500)
    whatsend_api_key: str | None = Field(default=None, max_length=1000)


class UpdateSheikhRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=20)
    whatsapp_group_id: str | None = Field(default=None, max_length=255)
    circle_id: int | None = None  # Legacy cached-client compatibility


class UpdateStudentRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=20)
    student_id: str | None = Field(default=None, max_length=50)
    birthday: date | None = None
    profile_pic: str | None = Field(default=None, max_length=1000)
    status: Literal["مقيد", "مستبعد", "منقطع", "ضيف", "غير مقيد"] | None = None
    registration_date: date | None = None
    sheikh_id: int | None = None
    parent_phones: list[UpdateParentPhone] | None = Field(default=None, max_length=20)


class PlatformTahfizActionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class CreateFeedbackRequest(BaseModel):
    category: Literal["bug", "suggestion", "other"] = "bug"
    title: str = Field(min_length=5, max_length=120)
    description: str = Field(min_length=10, max_length=4000)
    page_url: str | None = Field(default=None, max_length=500)

    @field_validator("title", "description", mode="before")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("page_url")
    @classmethod
    def normalize_page_url(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class UpdateFeedbackStatusRequest(BaseModel):
    status: Literal["open", "in_review", "resolved", "not_an_issue"]
    resolution_note: str | None = Field(default=None, max_length=2000)

    @field_validator("resolution_note")
    @classmethod
    def normalize_resolution_note(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class ExcelExportSubcolumnSettings(BaseModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    label: str = Field(min_length=1, max_length=80)
    width: int = Field(default=18, ge=1, le=60)


class ExcelExportColumnSettings(BaseModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    label: str = Field(min_length=1, max_length=80)
    enabled: bool = True
    custom: bool = False
    width: int = Field(default=18, ge=1, le=60)
    show_header: bool = True
    subcolumns: list[ExcelExportSubcolumnSettings] = Field(default_factory=list, max_length=10)


class ExcelExportTemplateSettings(BaseModel):
    columns: list[ExcelExportColumnSettings] = Field(min_length=1, max_length=30)
    header_font_family: str = Field(default="Arial", min_length=1, max_length=80)
    header_font_size: int = Field(default=12, ge=6, le=72)
    header_bold: bool = True
    header_background_color: str = Field(default="#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    header_font_color: str = Field(default="#000000", pattern=r"^#[0-9A-Fa-f]{6}$")
    cell_font_family: str = Field(default="Arial", min_length=1, max_length=80)
    cell_font_size: int = Field(default=11, ge=6, le=72)
    cell_bold: bool = False
    cell_font_color: str = Field(default="#000000", pattern=r"^#[0-9A-Fa-f]{6}$")
    date_font_family: str = Field(default="Arial", min_length=1, max_length=80)
    date_font_size: int = Field(default=12, ge=6, le=72)
    date_bold: bool = True
    date_font_color: str = Field(default="#000000", pattern=r"^#[0-9A-Fa-f]{6}$")
    attendance_date_format: Literal[
        "day",
        "day_month",
        "day_month_year",
        "weekday",
        "weekday_day",
        "weekday_day_month",
        "weekday_day_month_year",
    ] = "weekday_day_month_year"


class UpdateTahfizSettingsRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=255)
    contact_phone: str | None = Field(default=None, max_length=20)
    max_warnings: int | None = Field(default=None, ge=1, le=1000)
    week_start_day: int | None = Field(default=None, ge=0, le=6)
    month_start_day: int | None = Field(default=None, ge=1, le=28)
    attendance_statuses: list[str] | None = Field(default=None, max_length=20)
    attendance_status_renames: dict[str, str] | None = Field(default=None, max_length=20)
    excused_absence_streak_limit: int | None = Field(default=None, ge=1, le=1000)
    excused_absence_reset_statuses: list[str] | None = None
    attendance_streak_alert_enabled: bool | None = None
    attendance_sheikh_selection_enabled: bool | None = None
    restrict_sheikh_student_access: bool | None = None
    attendance_streak_status: str | None = Field(default=None, min_length=1, max_length=50)
    attendance_streak_limit: int | None = Field(default=None, ge=1, le=1000)
    attendance_streak_reset_statuses: list[str] | None = None
    attendance_status_colors: dict[str, str] | None = None
    excel_export_templates: dict[str, ExcelExportTemplateSettings] | None = None
    whatsend_api_url: str | None = Field(default=None, max_length=500)
    whatsend_groups_url: str | None = Field(default=None, max_length=500)
    whatsend_api_key: str | None = Field(default=None, max_length=1000)
    whatsend_enabled: bool | None = None
    progress_tracking_enabled: bool | None = None


# Temporary request aliases for one cached-client compatibility release.
CreateCircleRequest = UpdateTahfizRequest
UpdateCircleRequest = UpdateTahfizSettingsRequest


class SavedFilterOut(BaseModel):
    id: int
    name: str
    data: str

    class Config:
        from_attributes = True


class CreateSavedFilterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    data: str = Field(min_length=2, max_length=100_000)

    @field_validator("data")
    @classmethod
    def validate_filter_json(cls, value: str) -> str:
        parsed = json.loads(value)
        if not isinstance(parsed, (dict, list)):
            raise ValueError("Saved filter data must be a JSON object or list")
        return value


class UpdateSavedFilterRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    data: str | None = Field(default=None, min_length=2, max_length=100_000)

    @field_validator("data")
    @classmethod
    def validate_filter_json(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = json.loads(value)
        if not isinstance(parsed, (dict, list)):
            raise ValueError("Saved filter data must be a JSON object or list")
        return value


class UpdateExcusedWeekday(BaseModel):
    weekday: int = Field(ge=0, le=6)
    note: str | None = Field(default=None, max_length=1000)


class UpdateExcusedWeekdaysRequest(BaseModel):
    weekdays: list[UpdateExcusedWeekday | int] = Field(max_length=7)

    @field_validator("weekdays")
    @classmethod
    def validate_weekday_values(cls, values):
        normalized = [value if isinstance(value, int) else value.weekday for value in values]
        if any(value < 0 or value > 6 for value in normalized) or len(set(normalized)) != len(normalized):
            raise ValueError("Weekdays must be unique values between 0 and 6")
        return values


class SendWarningsRequest(BaseModel):
    warning_ids: list[int] = Field(min_length=1, max_length=500)


class SendStudentWarningRequest(BaseModel):
    absent_dates: list[str] = Field(min_length=1, max_length=500)


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=200)
    role: Literal["admin", "sheikh"] = "sheikh"
    sheikh_id: int | None = None


class UpdateUserRequest(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=50)
    password: str | None = Field(default=None, min_length=8, max_length=200)
    role: Literal["admin", "sheikh"] | None = None
    sheikh_id: int | None = None


class UpsertUserTahfizMembershipRequest(BaseModel):
    tahfiz_id: int
    role: Literal["admin", "sheikh"] = "admin"
    sheikh_id: int | None = None


class SetDefaultTahfizRequest(BaseModel):
    tahfiz_id: int


class CreateTahfizInvitationRequest(BaseModel):
    role: Literal["admin", "sheikh"] = "sheikh"
    sheikh_id: int | None = None
    expires_hours: int = Field(default=48, ge=1, le=168)


class InvitationRegistrationRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=200)


class QuranRangeInput(BaseModel):
    range_type: Literal["surah_ayah", "page"]
    from_surah: int | None = Field(default=None, ge=1, le=114)
    from_ayah: int | None = Field(default=None, ge=1)
    to_surah: int | None = Field(default=None, ge=1, le=114)
    to_ayah: int | None = Field(default=None, ge=1)
    from_page: int | None = Field(default=None, ge=1, le=604)
    to_page: int | None = Field(default=None, ge=1, le=604)

    @model_validator(mode="after")
    def validate_range(self):
        if self.range_type == "surah_ayah":
            if None in (self.from_surah, self.from_ayah, self.to_surah, self.to_ayah):
                raise ValueError("Surah and ayah range is required")
            if (self.to_surah, self.to_ayah) < (self.from_surah, self.from_ayah):
                raise ValueError("Range end must not precede range start")
        elif self.range_type == "page":
            if self.from_page is None or self.to_page is None:
                raise ValueError("Page range is required")
            if self.to_page < self.from_page:
                raise ValueError("Range end must not precede range start")
        else:
            raise ValueError("Invalid range type")
        return self


class QuranProgressItem(QuranRangeInput):
    student_id: int
    category: Literal["new_memorization", "recent_revision", "old_revision", "test"]
    sheikh_id: int | None = None
    quality_score: int = Field(ge=1, le=5)
    mistakes: int = Field(default=0, ge=0, le=1000)
    notes: str | None = Field(default=None, max_length=4000)
    next_assignment: str | None = Field(default=None, max_length=4000)


class QuranProgressBatchRequest(BaseModel):
    updates: list[QuranProgressItem] = Field(min_length=1, max_length=500)


class CreateStudentGoalRequest(QuranRangeInput):
    target_date: date | None = None
    notes: str | None = Field(default=None, max_length=4000)


class UpdateStudentGoalRequest(BaseModel):
    target_date: date | None = None
    notes: str | None = Field(default=None, max_length=4000)
    status: Literal["active", "completed", "cancelled"] | None = None


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    sheikh_id: int | None = None

    class Config:
        from_attributes = True

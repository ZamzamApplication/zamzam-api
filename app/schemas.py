from datetime import date, datetime, time
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
    phone_number: str
    parent_type: str
    name: str | None = None


class UpdateParentPhone(BaseModel):
    phone_number: str | None = None
    parent_type: str | None = None
    name: str | None = None


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    refresh_token: str | None = None
    expires_in: int | None = None


class LoginRequest(BaseModel):
    username: str
    password: str
    device_id: str | None = Field(default=None, min_length=8, max_length=100)
    device_name: str | None = Field(default=None, max_length=100)


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(min_length=32, max_length=500)
    device_id: str = Field(min_length=8, max_length=100)


class RevokeDeviceRequest(BaseModel):
    refresh_token: str = Field(min_length=32, max_length=500)


class SignupRequest(BaseModel):
    username: str
    password: str
    tahfiz_name: str
    contact_phone: str | None = None


class TahfizOut(BaseModel):
    id: int
    name: str
    description: str | None = None
    contact_phone: str | None = None
    status: str = "pending"
    max_warnings: int = 3
    week_start_day: int = 6
    month_start_day: int = 1
    attendance_statuses: list[str] = ["حاضر", "غياب", "غياب بعذر", "لا ينطبق"]

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


class StudentOut(BaseModel):
    id: int
    name: str
    phone: str | None = None
    student_id: str | None = None
    birthday: date | None = None
    profile_pic: str | None = None
    status: str = "مقيد"
    registration_date: date | None = None
    warnings: list[WarningOut] = []
    parent_phones: list[ParentPhoneOut] = []
    excused_weekdays: list[ExcusedWeekdayOut] = []

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
    status: str
    notes: str | None = None
    sheikh_id: int | None = None


class UpsertAttendanceRequest(BaseModel):
    session_id: int
    student_id: int
    status: str
    notes: str | None = None
    sheikh_id: int | None = None


class AttendanceBatchItem(BaseModel):
    student_id: int
    status: str
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
    default_status: str = "غياب"


class UpdateSessionRequest(BaseModel):
    session_date: date


class ReopenSessionRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    expected_version: int | None = Field(default=None, ge=0)


class ConfirmSessionRequest(BaseModel):
    confirm: bool = True
    expected_version: int | None = Field(default=None, ge=0)


class CreateSheikhRequest(BaseModel):
    name: str
    phone: str | None = None
    whatsapp_group_id: str | None = None
    circle_id: int | None = None  # Legacy cached-client compatibility


class CreateStudentRequest(BaseModel):
    name: str
    phone: str | None = None
    student_id: str | None = None
    birthday: date | None = None
    status: str = "مقيد"
    registration_date: date | None = None
    sheikh_id: int | None = None
    parent_phones: list[CreateParentPhone] = []


class CreateWarningRequest(BaseModel):
    reason: str


class MoveStudentRequest(BaseModel):
    sheikh_id: int


class ReorderStudentsRequest(BaseModel):
    student_ids: list[int]


class UpdateTahfizRequest(BaseModel):
    name: str
    description: str | None = None
    contact_phone: str | None = None
    max_warnings: int = 3
    week_start_day: int = 6
    month_start_day: int = 1
    attendance_statuses: list[str] | None = None
    whatsend_api_url: str | None = None
    whatsend_groups_url: str | None = None
    whatsend_api_key: str | None = None


class UpdateSheikhRequest(BaseModel):
    name: str | None = None
    phone: str | None = None
    whatsapp_group_id: str | None = None
    circle_id: int | None = None  # Legacy cached-client compatibility


class UpdateStudentRequest(BaseModel):
    name: str | None = None
    phone: str | None = None
    student_id: str | None = None
    birthday: date | None = None
    profile_pic: str | None = None
    status: str | None = None
    registration_date: date | None = None
    sheikh_id: int | None = None
    parent_phones: list[UpdateParentPhone] | None = None


class PlatformTahfizActionRequest(BaseModel):
    reason: str | None = None


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


class UpdateTahfizSettingsRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    contact_phone: str | None = None
    max_warnings: int | None = None
    week_start_day: int | None = None
    month_start_day: int | None = None
    attendance_statuses: list[str] | None = None
    whatsend_api_url: str | None = None
    whatsend_groups_url: str | None = None
    whatsend_api_key: str | None = None
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
    name: str
    data: str


class UpdateSavedFilterRequest(BaseModel):
    name: str | None = None
    data: str | None = None


class UpdateExcusedWeekday(BaseModel):
    weekday: int
    note: str | None = None


class UpdateExcusedWeekdaysRequest(BaseModel):
    weekdays: list[UpdateExcusedWeekday | int]


class SendWarningsRequest(BaseModel):
    warning_ids: list[int]


class SendStudentWarningRequest(BaseModel):
    absent_dates: list[str]


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "sheikh"
    sheikh_id: int | None = None


class UpdateUserRequest(BaseModel):
    username: str | None = None
    password: str | None = None
    role: str | None = None
    sheikh_id: int | None = None


class UpsertUserTahfizMembershipRequest(BaseModel):
    tahfiz_id: int
    role: str = "admin"
    sheikh_id: int | None = None


class SetDefaultTahfizRequest(BaseModel):
    tahfiz_id: int


class CreateTahfizInvitationRequest(BaseModel):
    role: str = "sheikh"
    sheikh_id: int | None = None
    expires_hours: int = Field(default=48, ge=1, le=168)


class InvitationRegistrationRequest(BaseModel):
    username: str
    password: str


class QuranRangeInput(BaseModel):
    range_type: str
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
    category: str
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
    status: str | None = None


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    sheikh_id: int | None = None

    class Config:
        from_attributes = True

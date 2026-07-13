from datetime import date, datetime, time
from pydantic import BaseModel


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


class LoginRequest(BaseModel):
    username: str
    password: str


class CircleOut(BaseModel):
    id: int
    name: str
    description: str | None = None
    max_warnings: int = 3
    week_start_day: int = 6

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
    circle_id: int
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


class CreateSessionRequest(BaseModel):
    circle_id: int
    session_date: date
    session_time: time | None = None
    default_status: str = "غياب"


class UpdateSessionRequest(BaseModel):
    session_date: date


class ConfirmSessionRequest(BaseModel):
    confirm: bool = True


class CreateSheikhRequest(BaseModel):
    name: str
    phone: str | None = None
    whatsapp_group_id: str | None = None
    circle_id: int | None = None


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


class CreateCircleRequest(BaseModel):
    name: str
    description: str | None = None
    max_warnings: int = 3
    week_start_day: int = 6


class UpdateSheikhRequest(BaseModel):
    name: str | None = None
    phone: str | None = None
    whatsapp_group_id: str | None = None
    circle_id: int | None = None


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


class UpdateCircleRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    max_warnings: int | None = None
    week_start_day: int | None = None


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


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    sheikh_id: int | None = None

    class Config:
        from_attributes = True

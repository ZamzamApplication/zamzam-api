from datetime import date, time
from pydantic import BaseModel


class ParentPhoneOut(BaseModel):
    id: int
    phone_number: str
    parent_type: str

    class Config:
        from_attributes = True


class CreateParentPhone(BaseModel):
    phone_number: str
    parent_type: str


class UpdateParentPhone(BaseModel):
    phone_number: str | None = None
    parent_type: str | None = None


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

    class Config:
        from_attributes = True


class SheikhOut(BaseModel):
    id: int
    name: str
    phone: str | None = None

    class Config:
        from_attributes = True


class StudentOut(BaseModel):
    id: int
    name: str
    phone: str | None = None
    student_id: str | None = None
    birthday: date | None = None
    profile_pic: str | None = None
    is_enrolled: bool = True
    parent_phones: list[ParentPhoneOut] = []

    class Config:
        from_attributes = True


class AttendanceOut(BaseModel):
    id: int
    session_id: int
    student_id: int
    student_name: str
    status: str

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


class UpsertAttendanceRequest(BaseModel):
    session_id: int
    student_id: int
    status: str


class CreateSessionRequest(BaseModel):
    circle_id: int
    session_date: date
    session_time: time | None = None


class ConfirmSessionRequest(BaseModel):
    confirm: bool = True


class CreateSheikhRequest(BaseModel):
    name: str
    phone: str | None = None
    circle_id: int | None = None


class CreateStudentRequest(BaseModel):
    name: str
    phone: str | None = None
    student_id: str | None = None
    birthday: date | None = None
    is_enrolled: bool = True
    sheikh_id: int | None = None
    parent_phones: list[CreateParentPhone] = []


class CreateCircleRequest(BaseModel):
    name: str
    description: str | None = None


class UpdateSheikhRequest(BaseModel):
    name: str | None = None
    phone: str | None = None
    circle_id: int | None = None


class UpdateStudentRequest(BaseModel):
    name: str | None = None
    phone: str | None = None
    student_id: str | None = None
    birthday: date | None = None
    profile_pic: str | None = None
    is_enrolled: bool | None = None
    parent_phones: list[UpdateParentPhone] | None = None


class UpdateCircleRequest(BaseModel):
    name: str | None = None
    description: str | None = None


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


class CreateCircleScheduleRequest(BaseModel):
    circle_id: int
    day_of_week: int
    time: str


class CircleScheduleOut(BaseModel):
    id: int
    circle_id: int
    day_of_week: int
    time: str

    class Config:
        from_attributes = True

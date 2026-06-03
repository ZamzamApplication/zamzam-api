from datetime import date, time
from pydantic import BaseModel


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


class CreateSessionRequest(BaseModel):
    circle_id: int
    session_date: date
    session_time: time | None = None


class ConfirmSessionRequest(BaseModel):
    confirm: bool = True

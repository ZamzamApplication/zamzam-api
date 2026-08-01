from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AttendanceStatus,
    ExcusedWeekday,
    Student,
    StudentExcusedPeriod,
    Tahfiz,
    attendance_streak_status_option,
)


def excused_period_note(reason: str) -> str:
    return f"عذر مؤقت: {reason}"


async def periods_on_date(
    db: AsyncSession,
    tahfiz_id: int,
    student_ids: list[int] | set[int],
    session_date: date,
) -> dict[int, StudentExcusedPeriod]:
    if not student_ids:
        return {}
    rows = (await db.execute(
        select(StudentExcusedPeriod).where(
            StudentExcusedPeriod.tahfiz_id == tahfiz_id,
            StudentExcusedPeriod.student_id.in_(student_ids),
            StudentExcusedPeriod.cancelled_at.is_(None),
            StudentExcusedPeriod.start_date <= session_date,
            StudentExcusedPeriod.end_date >= session_date,
        )
    )).scalars().all()
    return {row.student_id: row for row in rows}


def automatic_attendance(
    tahfiz: Tahfiz,
    student: Student,
    session_date: date,
    default_status: str,
    *,
    period: StudentExcusedPeriod | None = None,
    weekday: ExcusedWeekday | None = None,
) -> tuple[str, str | None]:
    if student.registration_date and student.registration_date > session_date:
        return AttendanceStatus.not_applicable.value, None
    if period is not None:
        return attendance_streak_status_option(tahfiz), excused_period_note(period.reason)
    if weekday is not None:
        return AttendanceStatus.not_applicable.value, weekday.note
    return default_status, None

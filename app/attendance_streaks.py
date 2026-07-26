from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Attendance,
    AttendanceStatus,
    Session,
    Student,
    Tahfiz,
    excused_absence_reset_status_options,
)


@dataclass(frozen=True)
class ExcusedAbsenceThresholdAlert:
    student_id: int
    student_name: str
    streak: int
    limit: int

    def as_dict(self) -> dict[str, int | str]:
        return {
            "student_id": self.student_id,
            "student_name": self.student_name,
            "streak": self.streak,
            "limit": self.limit,
        }


def calculate_excused_absence_streak(statuses: list[str], reset_statuses: set[str]) -> int:
    streak = 0
    for status in statuses:
        if status == AttendanceStatus.excused.value:
            streak += 1
        elif status in reset_statuses:
            break
    return streak


async def excused_absence_streak(
    db: AsyncSession,
    tahfiz: Tahfiz,
    student_id: int,
) -> int:
    statuses = (await db.execute(
        select(Attendance.status)
        .join(Session, Session.id == Attendance.session_id)
        .where(
            Attendance.tahfiz_id == tahfiz.id,
            Attendance.student_id == student_id,
            Session.tahfiz_id == tahfiz.id,
        )
        .order_by(Session.date.desc(), Session.id.desc(), Attendance.id.desc())
    )).scalars().all()
    reset_statuses = set(excused_absence_reset_status_options(tahfiz))
    return calculate_excused_absence_streak(list(statuses), reset_statuses)


async def threshold_alert_after_change(
    db: AsyncSession,
    tahfiz: Tahfiz,
    student_id: int,
    previous_streak: int,
    student_name: str | None = None,
) -> ExcusedAbsenceThresholdAlert | None:
    current_streak = await excused_absence_streak(db, tahfiz, student_id)
    limit = tahfiz.excused_absence_streak_limit
    if previous_streak <= limit < current_streak:
        if student_name is None:
            student_name = await db.scalar(select(Student.name).where(
                Student.id == student_id,
                Student.tahfiz_id == tahfiz.id,
            ))
        if student_name:
            return ExcusedAbsenceThresholdAlert(
                student_id=student_id,
                student_name=student_name,
                streak=current_streak,
                limit=limit,
            )
    return None

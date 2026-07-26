import json
import unittest

from app.attendance_streaks import calculate_attendance_status_streak
from app.models import (
    Tahfiz,
    attendance_status_color_options,
    excused_absence_reset_status_options,
)


class AttendanceStreakTests(unittest.TestCase):
    def test_excused_streak_ignores_other_statuses_and_stops_at_configured_reset(self):
        newest_first = ["غياب بعذر", "غياب بعذر", "لا ينطبق", "غياب", "غياب بعذر", "حاضر", "غياب بعذر"]
        self.assertEqual(calculate_attendance_status_streak(newest_first, "غياب بعذر", {"حاضر"}), 3)

    def test_an_added_reset_status_stops_the_streak(self):
        newest_first = ["غياب بعذر", "غياب", "غياب بعذر", "حاضر"]
        self.assertEqual(calculate_attendance_status_streak(newest_first, "غياب بعذر", {"حاضر", "غياب"}), 1)

    def test_any_configured_status_can_be_tracked(self):
        newest_first = ["عن بعد", "لا ينطبق", "عن بعد", "حاضر", "عن بعد"]
        self.assertEqual(calculate_attendance_status_streak(newest_first, "عن بعد", {"حاضر"}), 2)


class AttendanceColorSettingsTests(unittest.TestCase):
    def test_defaults_match_existing_frontend_colors_and_custom_status_is_violet(self):
        tahfiz = Tahfiz(
            name="اختبار",
            attendance_statuses=json.dumps(
                ["حاضر", "غياب", "غياب بعذر", "لا ينطبق", "عن بعد"],
                ensure_ascii=False,
            ),
            attendance_status_colors="{}",
        )
        self.assertEqual(attendance_status_color_options(tahfiz), {
            "حاضر": "green",
            "غياب": "slate",
            "غياب بعذر": "amber",
            "لا ينطبق": "sky",
            "عن بعد": "violet",
        })

    def test_reset_statuses_can_be_empty_and_never_include_excused(self):
        tahfiz = Tahfiz(
            name="اختبار",
            excused_absence_reset_statuses=json.dumps(["غياب بعذر", "حاضر", "حاضر"], ensure_ascii=False),
        )
        self.assertEqual(excused_absence_reset_status_options(tahfiz), ["حاضر"])
        tahfiz.excused_absence_reset_statuses = "[]"
        self.assertEqual(excused_absence_reset_status_options(tahfiz), [])

    def test_reset_statuses_never_include_the_generic_tracked_status(self):
        tahfiz = Tahfiz(
            name="اختبار",
            attendance_statuses=json.dumps(["حاضر", "عن بعد", "غياب"], ensure_ascii=False),
            attendance_streak_status="عن بعد",
            excused_absence_reset_statuses=json.dumps(["حاضر", "عن بعد"], ensure_ascii=False),
        )
        self.assertEqual(excused_absence_reset_status_options(tahfiz), ["حاضر"])

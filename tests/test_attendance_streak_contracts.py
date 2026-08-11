import json
import unittest

from app.attendance_streaks import calculate_attendance_status_streak
from app.models import (
    Tahfiz,
    absent_status_option,
    attendance_status_color_options,
    excused_absence_reset_status_options,
    present_status_option,
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


class PresentStatusOptionTests(unittest.TestCase):
    def test_defaults_to_the_present_label(self):
        tahfiz = Tahfiz(name="اختبار")
        self.assertEqual(present_status_option(tahfiz), "حاضر")

    def test_uses_the_configured_present_status(self):
        tahfiz = Tahfiz(
            name="اختبار",
            attendance_statuses=json.dumps(["✓", "غياب", "لا ينطبق"], ensure_ascii=False),
            present_status="✓",
        )
        self.assertEqual(present_status_option(tahfiz), "✓")

    def test_falls_back_to_the_green_status_when_present_is_not_configured(self):
        tahfiz = Tahfiz(
            name="اختبار",
            attendance_statuses=json.dumps(["موجود", "غياب"], ensure_ascii=False),
            attendance_status_colors='{"موجود":"green","غياب":"slate"}',
            present_status="حاضر",
        )
        self.assertEqual(present_status_option(tahfiz), "موجود")

    def test_returns_first_status_when_present_label_and_green_are_absent(self):
        tahfiz = Tahfiz(
            name="اختبار",
            attendance_statuses=json.dumps(["عن بعد", "غياب"], ensure_ascii=False),
            attendance_status_colors='{"عن بعد":"violet","غياب":"slate"}',
            present_status="حاضر",
        )
        self.assertEqual(present_status_option(tahfiz), "عن بعد")


class AbsentStatusOptionTests(unittest.TestCase):
    def test_defaults_to_absent(self):
        self.assertEqual(absent_status_option(Tahfiz(name="اختبار")), "غياب")

    def test_uses_configured_absent_status(self):
        tahfiz = Tahfiz(
            name="اختبار",
            attendance_statuses=json.dumps(["حاضر", "غير موجود"], ensure_ascii=False),
            absent_status="غير موجود",
        )

        self.assertEqual(absent_status_option(tahfiz), "غير موجود")

    def test_falls_back_to_non_present_status(self):
        tahfiz = Tahfiz(
            name="اختبار",
            attendance_statuses=json.dumps(["موجود", "متغيب"], ensure_ascii=False),
            attendance_status_colors='{"موجود":"green","متغيب":"violet"}',
            present_status="موجود",
            absent_status="غياب",
        )

        self.assertEqual(absent_status_option(tahfiz), "متغيب")

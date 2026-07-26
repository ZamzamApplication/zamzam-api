from app.models import Tahfiz, TahfizStatus
from app.routers.management import serialize_tahfiz
from app.schemas import UpdateTahfizSettingsRequest


def test_attendance_sheikh_selector_defaults_to_enabled():
    column = Tahfiz.__table__.c.attendance_sheikh_selection_enabled
    tahfiz = Tahfiz(
        id=1,
        name="اختبار",
        status=TahfizStatus.active,
        attendance_sheikh_selection_enabled=True,
    )

    assert column.default.arg is True
    assert serialize_tahfiz(tahfiz)["attendance_sheikh_selection_enabled"] is True


def test_attendance_sheikh_selector_can_be_disabled_in_settings_request():
    request = UpdateTahfizSettingsRequest(attendance_sheikh_selection_enabled=False)

    assert request.attendance_sheikh_selection_enabled is False

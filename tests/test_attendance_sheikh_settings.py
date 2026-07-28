from app.models import DEFAULT_EXCEL_EXPORT_TEMPLATES, Tahfiz, TahfizStatus
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


def test_attendance_status_renames_are_accepted_in_settings_request():
    request = UpdateTahfizSettingsRequest(
        attendance_statuses=["حاضر", "متغيب"],
        attendance_status_renames={"غياب": "متغيب"},
    )

    assert request.attendance_status_renames == {"غياب": "متغيب"}


def test_excel_export_templates_default_for_existing_tahfiz():
    tahfiz = Tahfiz(id=1, name="اختبار", status=TahfizStatus.active)

    assert serialize_tahfiz(tahfiz)["excel_export_templates"] == DEFAULT_EXCEL_EXPORT_TEMPLATES


def test_excel_export_template_columns_are_validated():
    request = UpdateTahfizSettingsRequest(excel_export_templates=DEFAULT_EXCEL_EXPORT_TEMPLATES)

    assert request.excel_export_templates["attendance"].columns[0].id == "student"

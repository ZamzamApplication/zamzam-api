import json

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

    assert request.excel_export_templates["attendance"].columns[0].id == "serial"
    assert request.excel_export_templates["attendance"].header_font_family == "Arial"
    assert request.excel_export_templates["attendance"].header_background_color == "#FFFFFF"
    assert request.excel_export_templates["attendance"].cell_font_family == "Arial"
    assert request.excel_export_templates["attendance"].cell_bold is False
    assert request.excel_export_templates["attendance"].attendance_date_format == "weekday_day_month_year"


def test_serial_column_is_added_to_existing_saved_templates_without_resetting_them():
    saved = json.loads(json.dumps(DEFAULT_EXCEL_EXPORT_TEMPLATES))
    for template in saved.values():
        template["columns"] = [
            column for column in template["columns"] if column["id"] != "serial"
        ]
        template.pop("header_font_family")
        template.pop("header_font_size")
        template.pop("header_bold")
        template.pop("header_background_color")
        template.pop("header_font_color")
        template.pop("cell_font_family")
        template.pop("cell_font_size")
        template.pop("cell_bold")
        template.pop("cell_font_color")
        template.pop("attendance_date_format")
    saved["attendance"]["columns"][0]["label"] = "اسم الطالب"
    tahfiz = Tahfiz(
        id=1,
        name="اختبار",
        status=TahfizStatus.active,
        excel_export_templates=json.dumps(saved, ensure_ascii=False),
    )

    templates = serialize_tahfiz(tahfiz)["excel_export_templates"]

    assert templates["attendance"]["columns"][0]["id"] == "serial"
    assert templates["attendance"]["columns"][0]["enabled"] is False
    assert templates["attendance"]["columns"][1]["label"] == "اسم الطالب"
    assert templates["attendance"]["header_font_family"] == "Arial"
    assert templates["attendance"]["header_font_size"] == 12
    assert templates["attendance"]["header_background_color"] == "#FFFFFF"
    assert templates["attendance"]["cell_font_family"] == "Arial"
    assert templates["attendance"]["cell_font_size"] == 11
    assert templates["attendance"]["cell_bold"] is False

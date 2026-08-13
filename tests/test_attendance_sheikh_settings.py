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


def test_sheikh_student_access_defaults_to_restricted():
    column = Tahfiz.__table__.c.restrict_sheikh_student_access
    request = UpdateTahfizSettingsRequest(restrict_sheikh_student_access=False)

    assert column.default.arg is True
    assert request.restrict_sheikh_student_access is False


def test_attendance_status_renames_are_accepted_in_settings_request():
    request = UpdateTahfizSettingsRequest(
        attendance_statuses=["حاضر", "متغيب"],
        attendance_status_renames={"غياب": "متغيب"},
    )

    assert request.attendance_status_renames == {"غياب": "متغيب"}


def test_absent_status_defaults_and_can_be_configured():
    tahfiz = Tahfiz(id=1, name="اختبار", status=TahfizStatus.active)
    request = UpdateTahfizSettingsRequest(absent_status="متغيب")

    assert serialize_tahfiz(tahfiz)["absent_status"] == "غياب"
    assert request.absent_status == "متغيب"


def test_multiple_daily_sessions_default_off_and_can_be_enabled():
    tahfiz = Tahfiz(id=1, name="اختبار", status=TahfizStatus.active)
    request = UpdateTahfizSettingsRequest(multiple_sessions_per_day_enabled=True)

    assert serialize_tahfiz(tahfiz)["multiple_sessions_per_day_enabled"] is False
    assert request.multiple_sessions_per_day_enabled is True


def test_session_name_options_are_serialized_and_accepted():
    tahfiz = Tahfiz(
        id=1,
        name="اختبار",
        status=TahfizStatus.active,
        session_name_options='["صباحية", "مسائية"]',
    )
    request = UpdateTahfizSettingsRequest(session_name_options=[" صباحية ", "مسائية"])

    assert serialize_tahfiz(tahfiz)["session_name_options"] == ["صباحية", "مسائية"]
    assert request.session_name_options == [" صباحية ", "مسائية"]


def test_excel_export_templates_default_for_existing_tahfiz():
    tahfiz = Tahfiz(id=1, name="اختبار", status=TahfizStatus.active)

    assert serialize_tahfiz(tahfiz)["excel_export_templates"] == DEFAULT_EXCEL_EXPORT_TEMPLATES


def test_excel_export_template_columns_are_validated():
    request = UpdateTahfizSettingsRequest(excel_export_templates=DEFAULT_EXCEL_EXPORT_TEMPLATES)

    assert request.excel_export_templates["attendance"].columns[0].id == "serial"
    assert request.excel_export_templates["attendance"].columns[0].header_font_size == 12
    memorization = next(column for column in request.excel_export_templates["attendance"].columns if column.id == "memorization")
    assert [subcolumn.id for subcolumn in memorization.subcolumns] == ["from", "to"]
    assert request.excel_export_templates["attendance"].header_font_family == "Arial"
    assert request.excel_export_templates["attendance"].header_background_color == "#FFFFFF"
    assert request.excel_export_templates["attendance"].cell_font_family == "Arial"
    assert request.excel_export_templates["attendance"].cell_bold is False
    assert request.excel_export_templates["attendance"].date_font_family == "Arial"
    assert request.excel_export_templates["attendance"].date_bold is True
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
        template.pop("date_font_family")
        template.pop("date_font_size")
        template.pop("date_bold")
        template.pop("date_font_color")
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
    assert templates["attendance"]["date_font_family"] == "Arial"
    assert templates["attendance"]["date_font_size"] == 12


def test_legacy_quran_custom_columns_are_promoted_without_duplicates():
    saved = json.loads(json.dumps(DEFAULT_EXCEL_EXPORT_TEMPLATES))
    saved["attendance"]["columns"] = [
        column for column in saved["attendance"]["columns"]
        if column["id"] not in {"memorization", "revision"}
    ]
    saved["attendance"]["columns"].extend([
        {
            "id": "custom_memorization", "label": "الحفظ", "enabled": True,
            "custom": True, "width": 20, "subcolumns": [
                {"id": "custom_from", "label": "من", "width": 18},
                {"id": "custom_to", "label": "الي", "width": 18},
            ],
        },
        {
            "id": "custom_revision", "label": "المراجعة", "enabled": True,
            "custom": True, "width": 20, "subcolumns": [
                {"id": "custom_from", "label": "من", "width": 18},
                {"id": "custom_to", "label": "إلى", "width": 18},
            ],
        },
    ])
    tahfiz = Tahfiz(
        id=1, name="اختبار", status=TahfizStatus.active,
        excel_export_templates=json.dumps(saved, ensure_ascii=False),
    )

    columns = serialize_tahfiz(tahfiz)["excel_export_templates"]["attendance"]["columns"]

    assert [column["id"] for column in columns].count("memorization") == 1
    assert [column["id"] for column in columns].count("revision") == 1
    assert next(column for column in columns if column["id"] == "memorization")["header_font_size"] == 12

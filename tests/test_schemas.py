import json
from pathlib import Path


def test_task_schema_defines_check_items_and_category_enum() -> None:
    # ARRANGE
    schema_path = Path("schemas/task-v1.schema.json")

    # ACT
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    # ASSERT
    assert "single_file_bugfix" in schema["properties"]["category"]["enum"]
    assert schema["properties"]["checks"]["items"]["$ref"] == "#/$defs/checkSpec"
    assert "pytest" in schema["$defs"]["checkType"]["enum"]


def test_report_schema_defines_nested_report_models() -> None:
    # ARRANGE
    schema_path = Path("schemas/report-v1.schema.json")

    # ACT
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    # ASSERT
    assert schema["properties"]["suite"]["$ref"] == "#/$defs/suiteRef"
    assert schema["properties"]["runs"]["items"]["$ref"] == "#/$defs/runResult"
    assert schema["properties"]["aggregates"]["items"]["$ref"] == "#/$defs/taskAgentAggregate"
    assert "budget_exceeded" in schema["$defs"]["runErrorKind"]["enum"]

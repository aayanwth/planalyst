"""docs/data_dictionary.md is generated; this fails when the code and the document drift apart."""

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("yaml")

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "generate_data_dictionary.py"


@pytest.fixture(scope="module")
def generator():
    spec = importlib.util.spec_from_file_location("generate_data_dictionary", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_data_dictionary_is_current(generator):
    committed = generator.OUTPUT.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert committed == generator.build(), "run: python scripts/generate_data_dictionary.py"


def test_every_forecast_column_has_a_description(generator):
    for name, (_, columns) in generator.python_tables().items():
        assert [c for c in columns if c not in generator.PYTHON_COLUMNS] == [], name


def test_every_documented_dbt_column_has_a_description(generator):
    text = generator.build()
    assert "|  |" not in text

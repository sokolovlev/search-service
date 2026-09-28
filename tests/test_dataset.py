"""Tests of the CSV parsing (no PostgreSQL or Elasticsearch needed)."""

from datetime import datetime

import pytest

from app.dataset import ReadStats, parse_date, parse_rubrics, parse_text, read_csv


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("['VK-1603736028819866', 'VK-47360980']", ["VK-1603736028819866", "VK-47360980"]),
        ('["VK-1", "VK-2"]', ["VK-1", "VK-2"]),
        ("{VK-1,VK-2}", ["VK-1", "VK-2"]),
        ("VK-1, VK-2", ["VK-1", "VK-2"]),
        ("['VK-1', None, '', 'VK-2']", ["VK-1", "VK-2"]),
        ('["VK-1", null]', ["VK-1"]),
        ("[]", []),
        ("", []),
        (None, []),
    ],
)
def test_parse_rubrics(raw, expected):
    assert parse_rubrics(raw) == expected


@pytest.mark.parametrize("raw", ["['VK-1', 'VK-2'", "[VK-1, VK-2", "['VK-1' 'VK-2' +]"])
def test_parse_rubrics_rejects_broken_lists(raw):
    with pytest.raises(ValueError):
        parse_rubrics(raw)


def test_parse_text_keeps_text_as_is():
    assert parse_text("  Текст\nв две строки ") == "  Текст\nв две строки "


@pytest.mark.parametrize("raw", [None, "", "   ", "\n\t"])
def test_parse_text_rejects_empty_text(raw):
    with pytest.raises(ValueError, match="empty text"):
        parse_text(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2019-11-25 12:34:42", datetime(2019, 11, 25, 12, 34, 42)),
        ("2019-11-25T12:34:42", datetime(2019, 11, 25, 12, 34, 42)),
        ("2019-11-25 12:34:42+03:00", datetime(2019, 11, 25, 9, 34, 42)),
        ("25.11.2019 12:34", datetime(2019, 11, 25, 12, 34)),
    ],
)
def test_parse_date(raw, expected):
    assert parse_date(raw) == expected


@pytest.mark.parametrize("raw", ["", "вчера", "2019-13-45 99:99:99"])
def test_parse_date_rejects_invalid_values(raw):
    with pytest.raises(ValueError):
        parse_date(raw)


def test_read_csv_parses_rows_and_skips_malformed_ones(tmp_path):
    path = tmp_path / "posts.csv"
    path.write_text(
        "text,created_date,rubrics\n"
        '"Текст, с запятой\nи переносом строки",2019-11-25 12:34:42,"[\'VK-1\', \'VK-2\']"\n'
        "Строка с плохой датой,не дата,[]\n"
        "\"   \",2020-01-01 00:00:00,[]\n"
        "Обычный текст,2020-01-01 00:00:00,[]\n",
        encoding="utf-8-sig",  # with BOM, as Excel saves it
    )
    stats = ReadStats()

    rows = list(read_csv(path, stats))

    assert [(row.text, row.created_date, row.rubrics) for row in rows] == [
        ("Текст, с запятой\nи переносом строки", datetime(2019, 11, 25, 12, 34, 42), ["VK-1", "VK-2"]),
        ("Обычный текст", datetime(2020, 1, 1), []),
    ]
    assert (stats.read, stats.skipped) == (2, 2)


def test_read_csv_requires_columns(tmp_path):
    path = tmp_path / "posts.csv"
    path.write_text("body,date\nтекст,2020-01-01\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing CSV columns"):
        list(read_csv(path))

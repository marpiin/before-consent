import csv
import re

import pytest
from seed import seed

from before_consent import store
from before_consent.config import Settings
from before_consent.report import build_report


@pytest.fixture
def seeded(fixture_trackers):
    connection = store.connect(":memory:")
    run_id = seed(connection, fixture_trackers)
    yield connection, run_id
    connection.close()


def test_report_hides_site_names_and_small_categories_by_default(seeded, tmp_path):
    connection, run_id = seeded
    html = build_report(connection, run_id, Settings(), tmp_path).read_text(encoding="utf-8")

    assert "news-a.example" not in html and "gov-b.example" not in html
    # Every seeded category has fewer than 5 sites, so none may be listed.
    assert "No category has 5 or more measured sites" in html
    with (tmp_path / "data" / "site_summary.csv").open(encoding="utf-8") as handle:
        assert list(csv.reader(handle)) == []


def test_report_figures_come_from_the_database(seeded, tmp_path):
    connection, run_id = seeded
    html = build_report(connection, run_id, Settings(min_sites_per_category=1), tmp_path).read_text(
        encoding="utf-8"
    )
    assert "3 of 5 measured home pages (60.0%)" in html
    assert "1 of 5 (20.0%) had a tracker cookie" in html
    assert "1 of 2 (50.0%)" in html


def test_page_content_is_escaped(seeded, tmp_path):
    connection, run_id = seeded
    connection.execute("UPDATE request_log SET tracker_owner = '<script>alert(1)</script>'")
    connection.commit()
    html = build_report(connection, run_id, Settings(), tmp_path).read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_report_has_no_script_and_no_external_resources(seeded, tmp_path):
    connection, run_id = seeded
    html = build_report(connection, run_id, Settings(), tmp_path).read_text(encoding="utf-8")
    assert "<script" not in html
    assert re.findall(r'(?:src|href)="(?:[a-z]+:)?//', html) == []
    assert "@import" not in html and "url(" not in html and "@font-face" not in html

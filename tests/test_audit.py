from pathlib import Path

import pytest
from conftest import FakeWeb
from seed import SNAPSHOT
from test_rules import FakeClock

from before_consent import store
from before_consent.audit import run_audit
from before_consent.cli import main
from before_consent.pacing import Pacer
from before_consent.targets import Target, load_targets

ROBOTS_DENY = (200, "text/plain", "User-agent: *\nDisallow: /\n")
ROBOTS_ALLOW = (404, "text/plain", "not found")
PAGE = (200, "text/html", "<p>hello</p>")


def test_disallowed_site_is_skipped_in_every_round_without_loading_it(make_session):
    web = FakeWeb(
        pages={
            "https://site.example/robots.txt": ROBOTS_DENY,
            "https://site.example/": PAGE,
            "https://other.example/robots.txt": ROBOTS_ALLOW,
            "https://other.example/": PAGE,
        }
    )
    session = make_session(web)
    connection = store.connect(":memory:")
    run_id = store.start_run(connection, "ES", "chromium", "1", SNAPSHOT, "c" * 64)
    clock = FakeClock()
    pacer = Pacer(5, 30, clock=clock, sleep=clock.sleep)
    targets = [Target("https://site.example/", "news"), Target("https://other.example/", "news")]

    run_audit(session, connection, run_id, targets, pacer, progress=lambda line: None)

    assert "https://site.example/" not in web.hits
    assert web.hits.count("https://site.example/robots.txt") == 1
    rows = connection.execute(
        "SELECT s.url, v.round, v.status, v.error FROM visit v JOIN site s USING (site_id)"
        " ORDER BY v.visit_id"
    ).fetchall()
    assert [tuple(r) for r in rows] == [
        ("https://site.example/", 1, "skipped_robots", "disallowed by robots.txt"),
        ("https://other.example/", 1, "ok", None),
        ("https://site.example/", 2, "skipped_robots", "disallowed by robots.txt"),
        ("https://other.example/", 2, "ok", None),
        ("https://site.example/", 3, "skipped_robots", "disallowed by robots.txt"),
        ("https://other.example/", 3, "ok", None),
    ]


def test_targets_file_in_the_repository_is_valid():
    targets = load_targets(Path("targets.csv"))
    assert len(targets) == 40
    counts: dict[str, int] = {}
    for target in targets:
        counts[target.category] = counts.get(target.category, 0) + 1
    assert all(count >= 5 for count in counts.values())


def test_targets_reject_non_http_and_deep_urls(tmp_path):
    bad = tmp_path / "t.csv"
    bad.write_text("url,category\nfile:///etc/passwd,news\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not an http"):
        load_targets(bad)
    bad.write_text("url,category\nhttps://a.example/news/1,news\n", encoding="utf-8")
    with pytest.raises(ValueError, match="only home pages"):
        load_targets(bad)


def test_run_refuses_to_start_without_contact(tmp_path, capsys):
    config = tmp_path / "settings.toml"
    config.write_text('contact = ""\n', encoding="utf-8")
    assert main(["--config", str(config), "run", "--country", "ES"]) == 2
    assert "contact is empty" in capsys.readouterr().err

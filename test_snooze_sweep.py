"""Tests for the snooze-sweep job (#159). The gh boundary is mocked — no live GitHub calls."""

import datetime

import pytest
import snooze_sweep as job

# --- pure logic --------------------------------------------------------------------------------


def test_parse_snooze_date():
    assert job.parse_snooze_date("blah\nsnooze: 2026-06-27\nblah") == datetime.date(2026, 6, 27)
    assert job.parse_snooze_date("Snooze:   2026-01-05") == datetime.date(
        2026, 1, 5
    )  # case + space


def test_parse_snooze_date_last_match_wins():
    # Re-snoozing by appending a newer line should take effect.
    body = "snooze: 2026-06-01\n...later...\nsnooze: 2026-09-09"
    assert job.parse_snooze_date(body) == datetime.date(2026, 9, 9)


def test_parse_snooze_date_missing_or_malformed():
    assert job.parse_snooze_date(None) is None
    assert job.parse_snooze_date("no token here") is None
    assert job.parse_snooze_date("snooze: 2026-13-40") is None  # impossible date -> None, no crash
    assert job.parse_snooze_date("snooze: next week") is None


def test_is_due():
    today = datetime.date(2026, 6, 20)
    assert job.is_due(datetime.date(2026, 6, 19), today) is True  # past
    assert job.is_due(datetime.date(2026, 6, 20), today) is True  # today
    assert job.is_due(datetime.date(2026, 6, 21), today) is False  # future


def test_author_login():
    assert job.author_login({"author": {"login": "lucasklawrence"}}) == "lucasklawrence"
    assert job.author_login({"author": {}}) is None
    assert job.author_login({}) is None


# --- orchestration -----------------------------------------------------------------------------


def _issue(number, date_str, author="lucasklawrence"):
    body = f"Some text\nsnooze: {date_str}\n" if date_str else "no snooze token"
    return {"number": number, "title": f"#{number}", "body": body, "author": {"login": author}}


_TODAY = datetime.date(2026, 6, 20)


def test_main_wakes_only_due_issues(monkeypatch):
    woken: list[tuple] = []
    monkeypatch.setattr(
        job,
        "list_snoozed_issues",
        lambda: [
            _issue(1, "2026-06-19"),  # past -> due
            _issue(2, "2026-06-20"),  # today -> due
            _issue(3, "2026-07-01"),  # future -> not due
            _issue(4, None),  # no valid date -> skipped
        ],
    )
    monkeypatch.setattr(job, "wake_issue", lambda n, a, d: woken.append((n, a, d)))

    assert job.main(today=_TODAY) == 0
    assert [n for n, _, _ in woken] == [1, 2]  # only the due ones; future + dateless skipped


def test_main_one_failure_does_not_sink_the_rest(monkeypatch):
    import subprocess

    woken: list[int] = []
    monkeypatch.setattr(
        job, "list_snoozed_issues", lambda: [_issue(1, "2026-06-01"), _issue(2, "2026-06-01")]
    )

    def flaky(number, author, date):
        if number == 1:
            raise subprocess.CalledProcessError(1, "gh", stderr="boom")
        woken.append(number)

    monkeypatch.setattr(job, "wake_issue", flaky)

    assert job.main(today=_TODAY) == 0  # #1 errored, #2 still woken
    assert woken == [2]


def test_wake_issue_comments_before_removing_label(monkeypatch):
    # Notification first, label-removal second — so a comment failure is self-healing.
    calls: list[list[str]] = []
    monkeypatch.setattr(job, "_run_gh", lambda args: calls.append(args) or "")
    job.wake_issue(7, "lucasklawrence", datetime.date(2026, 6, 20))
    assert calls[0][:2] == ["issue", "comment"]
    assert calls[1][:2] == ["issue", "edit"] and "--remove-label" in calls[1]


def test_wake_issue_comment_failure_leaves_label(monkeypatch):
    import subprocess

    # If the comment (first call) fails, the label-removal must NOT run — the issue stays `snoozed`
    # so the next sweep retries it, rather than being silently un-snoozed and never re-found.
    calls: list[list[str]] = []

    def fail_on_comment(args):
        calls.append(args)
        if args[:2] == ["issue", "comment"]:
            raise subprocess.CalledProcessError(1, "gh", stderr="boom")
        return ""

    monkeypatch.setattr(job, "_run_gh", fail_on_comment)
    with pytest.raises(subprocess.CalledProcessError):
        job.wake_issue(7, "lucasklawrence", datetime.date(2026, 6, 20))
    assert not any("--remove-label" in c for c in calls)  # label untouched

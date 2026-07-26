"""Un-snooze issues whose ``snooze: YYYY-MM-DD`` date has arrived. Stdlib-only.

Shared/org-wide version of the sweep that originated in lucasklawrence/life
(``jobs/snooze_sweep.py``, issue #159; org-wide = life#267). Run daily from a caller repo via the
reusable workflow ``.github/workflows/snooze-sweep.yml``.

Behaviour: find open issues carrying the snooze label with a ``snooze:`` date <= today (UTC), then
wake each — comment @-mention **first** (the durable notification), remove the label **second**, so
a failed comment leaves the issue labelled and retried next run (self-healing). Worst case is a
duplicate ping, never a silent miss. Malformed/absent dates are skipped with a warning.

Auth: ``gh`` reads ``GH_TOKEN`` (the caller workflow's ``GITHUB_TOKEN``); ``GH_REPO`` pins the
target to the caller repo, so it only ever touches that repo's own issues. The snooze label name
defaults to ``snoozed`` and can be overridden with the ``SNOOZE_LABEL`` env var.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import sys

SNOOZE_LABEL = os.environ.get("SNOOZE_LABEL", "snoozed")
# `snooze: 2026-08-04` anywhere in the body (case-insensitive). Last match wins, so re-snoozing by
# appending a fresh line takes effect without editing the old one.
_SNOOZE_RE = re.compile(r"snooze:\s*(\d{4}-\d{2}-\d{2})", re.IGNORECASE)


# --- gh CLI boundary (mocked in tests) -------------------------------------------------------


def _run_gh(args: list[str]) -> str:
    """Run a ``gh`` subcommand and return stdout. Raises CalledProcessError on non-zero exit."""
    return subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=True, encoding="utf-8"
    ).stdout


def list_snoozed_issues() -> list[dict]:
    """Open issues carrying the snooze label, with the fields needed to decide + notify."""
    out = _run_gh(
        [
            "issue",
            "list",
            "--label",
            SNOOZE_LABEL,
            "--state",
            "open",
            "--limit",
            "200",
            "--json",
            "number,title,body,author",
        ]
    )
    return json.loads(out)


def wake_issue(number: int, author: str | None, snooze_date: datetime.date) -> None:
    """Un-snooze a due issue: ping the author (-> GitHub email) first, then drop the label."""
    mention = f"@{author} " if author else ""
    _run_gh(
        [
            "issue",
            "comment",
            str(number),
            "--body",
            f"{mention}⏰ Snooze elapsed (was `snooze: {snooze_date.isoformat()}`) — back on "
            f"your radar. Re-snooze with the `{SNOOZE_LABEL}` label + a new `snooze:` date.",
        ]
    )
    _run_gh(["issue", "edit", str(number), "--remove-label", SNOOZE_LABEL])


# --- pure logic (unit-tested) ----------------------------------------------------------------


def parse_snooze_date(body: str | None) -> datetime.date | None:
    """The ``snooze:`` date from a body, or None if absent/malformed (last match wins)."""
    if not body:
        return None
    matches = _SNOOZE_RE.findall(body)
    if not matches:
        return None
    try:
        return datetime.date.fromisoformat(matches[-1])
    except ValueError:
        return None  # e.g. 2026-13-40 — skip rather than crash


def is_due(snooze_date: datetime.date, today: datetime.date) -> bool:
    """True once the snooze date has arrived (<= today)."""
    return snooze_date <= today


def author_login(issue: dict) -> str | None:
    """The issue author's login, or None (bot/ghost authors have no usable mention)."""
    return (issue.get("author") or {}).get("login") or None


# --- orchestration ---------------------------------------------------------------------------


def main(today: datetime.date | None = None) -> int:
    today = today or datetime.datetime.now(datetime.timezone.utc).date()
    issues = list_snoozed_issues()
    woken = 0
    for issue in issues:
        number = issue.get("number")
        snooze_date = parse_snooze_date(issue.get("body"))
        if snooze_date is None:
            print(f"skip #{number}: snoozed label but no valid `snooze:` date", file=sys.stderr)
            continue
        if not is_due(snooze_date, today):
            continue
        try:
            wake_issue(number, author_login(issue), snooze_date)
            woken += 1
        except subprocess.CalledProcessError as e:
            print(f"skip #{number}: gh error: {(e.stderr or '').strip()}", file=sys.stderr)

    print(f"swept {len(issues)} snoozed issue(s); woke {woken}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

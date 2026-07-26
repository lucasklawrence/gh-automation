# gh-automation

Reusable GitHub Actions "plugins" for my repos. Logic lives here once; each repo adopts a plugin
with a tiny caller workflow that `uses:` it. Public so both public and private repos can call it.

## snooze-sweep

Defer an issue to a date and get pulled back when it's due (originated in
[lucasklawrence/life#159](https://github.com/lucasklawrence/life/issues/159); this is the shared,
org-wide version — [life#267](https://github.com/lucasklawrence/life/issues/267)).

**Use it:**

1. Add a caller workflow to your repo:

   ```yaml
   # .github/workflows/snooze-sweep.yml
   name: snooze-sweep
   on:
     schedule:
       - cron: "0 13 * * *" # daily ~13:00 UTC
     workflow_dispatch: {}
   permissions:
     issues: write
   jobs:
     sweep:
       uses: lucasklawrence/gh-automation/.github/workflows/snooze-sweep.yml@main
       permissions:
         issues: write
   ```

2. That's it. The `snoozed` label is **created automatically** on first run.

**Snooze an issue:** add the **`snoozed`** label and a **`snooze: YYYY-MM-DD`** line in the body.
When that date passes, the daily run drops the label and @-mentions the author (a GitHub
notification email). Re-snooze anytime by appending a new `snooze:` line — the last one wins.

**How it behaves**

- Runs in the caller's context with the caller's `GITHUB_TOKEN` → only ever touches that repo's
  own issues.
- Comments **before** removing the label, so a failed comment leaves the issue labelled and retried
  next run (self-healing). Worst case is a duplicate ping, never a silent miss.
- Malformed/absent `snooze:` dates are skipped with a warning, not a crash.
- Optional `label` input if you want a name other than `snoozed`.

Logic mirrors the unit-tested `jobs/snooze_sweep.py` in `lucasklawrence/life`.

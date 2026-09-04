"""The database migrations, as a set.

Two things go wrong with a pile of migration files that no one tracks.

One: a file that cannot be run twice. Nobody remembers which ones they have
already applied, so the honest instruction is "run them all, in order" - and
that only works if running one again is harmless. Two of them used to fail on
a second run, part-way through, leaving the rest of the file unapplied.

Two: a new migration gets added and check_migrations.sql is not updated, so
the thing that tells you what is missing quietly stops mentioning it.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The order they must be applied in, as README documents it. Later files
# assume tables and functions the earlier ones create.
ORDER = [
    "setup_database.sql",
    "customers_schema.sql",
    "stock_schema.sql",
    "extra_columns_migration.sql",
    "migrate_orders.sql",
    "migrate_audit_log.sql",
    "migrate_media_types.sql",
    "migrate_stock_alerts.sql",
    "migrate_user_management.sql",
    "migrate_catalog.sql",
    "migrate_customer_profiles.sql",
    "migrate_po_inbox.sql",
    "migrate_pricing.sql",
    "migrate_quotes.sql",
    "migrate_quote_portal.sql",
    "migrate_staff_access.sql",
    "migrate_customer_portal.sql",
    "migrate_portal_signin.sql",
    "migrate_supplied_order_numbers.sql",
    "migrate_performance.sql",
    "migrate_scanning.sql",
    "migrate_avatars.sql",
    "migrate_bulk_status.sql",
]


def _sql_files() -> list:
    """Every SQL file meant to be run against the database."""
    return sorted(p.name for p in ROOT.glob("*.sql")
                  if p.name != "check_migrations.sql")


def test_the_documented_order_covers_every_sql_file():
    """A migration nobody lists is a migration nobody runs."""
    on_disk = set(_sql_files())
    listed = set(ORDER)
    assert not (on_disk - listed), f"not in the documented order: {sorted(on_disk - listed)}"
    assert not (listed - on_disk), f"listed but missing from the repo: {sorted(listed - on_disk)}"


def test_every_created_policy_is_dropped_first():
    """CREATE POLICY has no IF NOT EXISTS, so re-running a file that creates
    one fails part-way and leaves the rest of that file unapplied."""
    problems = []
    for name in _sql_files():
        text = (ROOT / name).read_text(encoding="utf-8")
        created = re.findall(r'create\s+policy\s+"([^"]+)"', text, re.I)
        dropped = set(re.findall(r'drop\s+policy\s+if\s+exists\s+"([^"]+)"', text, re.I))
        for policy in created:
            if policy not in dropped:
                problems.append(f"{name}: \"{policy}\" is created without being dropped first")
    assert not problems, "these files cannot be run twice:\n  " + "\n  ".join(problems)


def test_tables_and_indexes_are_created_conditionally():
    """Same reason: a bare CREATE TABLE or CREATE INDEX fails on a re-run."""
    problems = []
    for name in _sql_files():
        text = (ROOT / name).read_text(encoding="utf-8")
        # Strip comments so prose about CREATE TABLE doesn't count.
        code = "\n".join(l.split("--")[0] for l in text.splitlines())
        for kind in ("table", "index", "unique index", "sequence"):
            pattern = rf"create\s+{kind}\s+(?!if\s+not\s+exists)"
            for m in re.finditer(pattern, code, re.I):
                snippet = code[m.start():m.start() + 60].replace("\n", " ")
                problems.append(f"{name}: {snippet.strip()}")
    assert not problems, ("these are not safe to re-run:\n  "
                          + "\n  ".join(problems))


def test_the_checker_asks_about_every_migration():
    """check_migrations.sql is what tells someone what they still need. A file
    missing from it is a file they will never be told about."""
    check = (ROOT / "check_migrations.sql").read_text(encoding="utf-8")
    missing = [name for name in ORDER if name not in check]
    assert not missing, f"check_migrations.sql never mentions: {missing}"


def test_the_checker_only_reads():
    """It gets pasted into a live production database. It must not write."""
    check = (ROOT / "check_migrations.sql").read_text(encoding="utf-8")
    # Strip comments, then the quoted strings — the file describes what each
    # migration does ("Archiving an order, and delete by role"), and prose
    # about deleting is not a DELETE.
    code = "\n".join(l.split("--")[0] for l in check.splitlines())
    code = re.sub(r"'[^']*'", "''", code)
    for verb in ("insert", "update", "delete", "drop", "alter", "grant",
                 "revoke", "truncate", "create"):
        assert not re.search(rf"(?:^|;)\s*{verb}\s", code, re.I | re.M), \
            f"check_migrations.sql runs a {verb.upper()}"


def test_the_security_migration_is_marked_essential():
    """Until it is run, anyone who can register can read and change
    everything. It must not read as one of the optional ones."""
    check = (ROOT / "check_migrations.sql").read_text(encoding="utf-8")
    line = next(l for l in check.splitlines() if "migrate_staff_access.sql" in l)
    assert "ESSENTIAL" in line


def test_the_order_number_sequence_catches_up_rather_than_resetting():
    """Re-running it must not hand out a number that is already on an order."""
    sql = (ROOT / "migrate_supplied_order_numbers.sql").read_text(encoding="utf-8")
    assert "setval" in sql
    assert "GREATEST" in sql or "max(" in sql, \
        "a re-run must start above the numbers already issued, not at 1"

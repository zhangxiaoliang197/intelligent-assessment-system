r"""Runner for the database / data-source test suite.

Usage (from the project root, using the project venv):

    .\.venv\Scripts\python.exe tests\database\run_tests.py             # all tests
    .\.venv\Scripts\python.exe tests\database\run_tests.py -v          # verbose
    .\.venv\Scripts\python.exe tests\database\run_tests.py test_admin_sql_execution
    .\.venv\Scripts\python.exe tests\database\run_tests.py --admin-url http://localhost:10258

Flags:
    --admin-url <url>   admin-service base URL (default http://localhost:10258)
    --qa-url <url>      qa-service base URL      (default http://localhost:10253)

Notes:
  * Unit tests (test_unit_dialect) need only the qa-service sources and run
    offline.
  * Integration tests need the services running and at least one reachable
    database config (MySQL on this machine).
"""

from __future__ import annotations

import argparse
import os
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]
QA_SERVICE_ROOT = PROJECT_ROOT / "python" / "qa-service"

# Make this suite importable and make qa-service's `agents` package importable.
for p in (str(HERE), str(QA_SERVICE_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import base as base_module  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("patterns", nargs="*", help="test module name substrings to filter")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--admin-url", default=None)
    parser.add_argument("--qa-url", default=None)
    args, unknown = parser.parse_known_args()

    if args.admin_url:
        os.environ["ADMIN_URL"] = args.admin_url
    if args.qa_url:
        os.environ["QA_URL"] = args.qa_url
    # Re-read env into the module constants.
    base_module.ADMIN_URL = os.environ.get("ADMIN_URL", "http://localhost:10258").rstrip("/")
    base_module.QA_URL = os.environ.get("QA_URL", "http://localhost:10253").rstrip("/")

    loader = unittest.TestLoader()
    start_dir = str(HERE)
    suite = loader.discover(start_dir, pattern="test_*.py")

    if args.patterns:
        filtered = unittest.TestSuite()
        for test in _flatten(suite):
            id_ = test.id()
            if any(p in id_ for p in args.patterns):
                filtered.addTest(test)
        suite = filtered

    runner = unittest.TextTestRunner(verbosity=2 if args.verbose else 1)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


def _flatten(suite: unittest.TestSuite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from _flatten(test)
        else:
            yield test


if __name__ == "__main__":
    sys.exit(main())

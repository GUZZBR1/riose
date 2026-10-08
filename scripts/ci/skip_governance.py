"""Pytest plugin that makes unexplained and environment-blocked skips visible."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


BLOCKING_SKIP_CLASSES = {
    "ENVIRONMENT_MISSING",
    "EXTERNAL_BLOCKED",
    "TEMPORARY",
    "REGRESSION_RISK",
    "UNEXPLAINED",
}


class SkipGovernance:
    def __init__(self, rules_path: Path) -> None:
        data: dict[str, Any] = json.loads(rules_path.read_text(encoding="utf-8"))
        self.rules = data["rules"]
        self.skips: list[tuple[str, str, str]] = []
        self.blocking: list[tuple[str, str, str]] = []

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if report.skipped:
            self._record_skip(report.nodeid, report.longrepr)

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        # Module-level importorskip and collection skips do not produce a
        # runtest report, so they need the same explicit governance.
        if report.skipped:
            self._record_skip(report.nodeid, report.longrepr)

    def _record_skip(self, nodeid: str, longrepr: object) -> None:
        detail = str(longrepr)
        classification = "UNEXPLAINED"
        for rule in self.rules:
            if rule["pattern"] in detail:
                classification = rule["classification"]
                break
        item = (nodeid, classification, detail)
        self.skips.append(item)
        if classification in BLOCKING_SKIP_CLASSES:
            self.blocking.append(item)

    def pytest_terminal_summary(self, terminalreporter: Any) -> None:
        if self.skips:
            terminalreporter.write_sep("=", "SC-4 skip governance")
            for nodeid, classification, detail in self.skips:
                terminalreporter.write_line(f"{classification}: {nodeid}: {detail}")
        if self.blocking:
            terminalreporter.write_line(
                f"{len(self.blocking)} skip(s) block this gate; classify or repair them."
            )

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        if self.blocking and exitstatus == pytest.ExitCode.OK:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED

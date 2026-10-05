"""Render the reproducible run ledger without upgrading its evidence class."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from riose.simulation_contract.v1 import content_hash


class ReportError(ValueError):
    """A manifest is invalid or cannot support the requested report."""


def verify_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("schema_version") != "riose.beta.campaign-manifest/v1":
        raise ReportError("unsupported campaign manifest")
    expected = manifest.get("manifest_sha256")
    payload = dict(manifest)
    payload.pop("manifest_sha256", None)
    if not isinstance(expected, str) or content_hash(payload) != expected:
        raise ReportError("campaign manifest hash does not match its content")
    if manifest.get("classification") != "SIMULATED":
        raise ReportError("Beta simulation report cannot promote campaign classification")
    runs = manifest.get("runs")
    if not isinstance(runs, list):
        raise ReportError("campaign manifest is missing its complete run list")
    for row in runs:
        if row.get("status") == "COMPLETED" and row.get("classification") != "SIMULATED":
            raise ReportError("completed simulation run has an invalid evidence class")


def render_results(manifest: dict[str, Any]) -> str:
    verify_manifest(manifest)
    denominator = manifest["denominator_policy"]
    lines = [
        "# RIOSE Beta campaign results", "",
        "All campaign observations and solver results are `SIMULATED`. This file records execution evidence; it does not establish hardware, field, clinical, or reproductive validity.", "",
        f"- Campaign: `{manifest['campaign_id']}`",
        f"- RIOSE revision: `{manifest['riose']['revision']}` (clean at execution: `{not manifest['riose']['dirty']}`)",
        f"- FREQUENCIA revision: `{manifest['simulator']['revision']}` (clean: `{not manifest['simulator']['dirty']}`)",
        f"- Classification: `{manifest['classification']}`",
        f"- Manifest SHA-256: `{manifest['manifest_sha256']}`",
        f"- Runs completed / scheduled / failed: {denominator['successful_runs']} / {denominator['scheduled_runs']} / {denominator['failed_runs']}", "",
        "## Per-run ledger", "",
        "| Run | Scenario | Seed | Status | Request SHA-256 | Raw result SHA-256 | Normalized result digest | Workspace |",
        "|---|---|---:|---|---|---|---|---|",
    ]
    for row in manifest["runs"]:
        lines.append("| `{}` | `{}` | {} | `{}` | `{}` | `{}` | `{}` | `{}` |".format(
            row.get("run_key", "UNKNOWN"), row.get("scenario_id", "UNKNOWN"),
            row.get("seed", ""), row.get("status", "UNKNOWN"),
            row.get("request_sha256", "NOT_AVAILABLE"), row.get("output_sha256", "NOT_AVAILABLE"),
            row.get("reproducibility_sha256", "NOT_AVAILABLE"),
            row.get("workspace", "NOT_AVAILABLE").replace("|", "\\|")))
        if row.get("status") != "COMPLETED":
            lines.extend(["", f"Failure `{row.get('run_key', 'UNKNOWN')}`: {row.get('error', 'reason unavailable')}"])
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in manifest["runs"]:
        grouped[row.get("scenario_id", "UNKNOWN")].append(row)
    lines.extend(["", "## Per-scenario denominators and outcomes", "",
                  "Counts below sum every scheduled run, including the same-seed baseline repeat. `Gateway PHY RX` counts packets received by at least one gateway; it is not application delivery. Localization quality counts remain separate from numerical convergence.", "",
                  "| Scenario | Runs C/F | Requested / TX / gateway PHY RX | PDR per TX | Estimator attempts / converged / scored | Quality A / R / NE | Error denominator |",
                  "|---|---:|---:|---:|---:|---:|---:|"])
    for scenario_id, rows in grouped.items():
        completed = sum(row.get("status") == "COMPLETED" for row in rows)
        failed = len(rows) - completed
        def total(path: tuple[str, ...]) -> int:
            values = []
            for row in rows:
                value: Any = row.get("metrics", {})
                for key in path:
                    value = value.get(key, {}) if isinstance(value, dict) else {}
                values.append(value if isinstance(value, (int, float)) else 0)
            return int(sum(values))
        requested, transmitted, phy_rx = (total(("network", key)) for key in
                                           ("requested_packets", "transmitted_packets", "delivered_packets"))
        pdr = f"{phy_rx / transmitted:.1%}" if transmitted else "N/A"
        attempts, converged, scored, error_denominator = (total(("localization", key)) for key in
            ("attempts", "converged", "scored", "error_denominator"))
        quality = [total(("localization", "quality_counts", key)) for key in
                   ("ACCEPTED", "REJECTED", "NOT_EVALUATED")]
        lines.append(f"| `{scenario_id}` | {completed}/{failed} | {requested} / {transmitted} / {phy_rx} | {pdr} | {attempts} / {converged} / {scored} | {quality[0]} / {quality[1]} / {quality[2]} | {error_denominator} |")
    lines.extend(["", "## Reproducibility", ""])
    for repeat in manifest.get("reproducibility", []):
        lines.append(f"- `{repeat['scenario_id']}` seed `{repeat['seed']}`: `{repeat['status']}`; "
                     f"same request: `{repeat['same_request']}`; "
                     f"same normalized simulator result digest: `{repeat['same_output']}`.")
    if not manifest.get("reproducibility"):
        lines.append("- No same-seed repeat was scheduled.")
    lines.extend(["", "## Interpretation boundary", "",
                  "- `TX` is not a PHY reception; PHY reception is not application delivery.",
                  "- Convergence is not accuracy or quality acceptance.",
                  "- Any trajectory ground truth is score-only synthetic input, never estimator input.",
                  "- Hashes support content integrity and do not prove authorship or physical truth.", ""])
    return "\n".join(lines)


def write_results(manifest_path: str | Path, destination: str | Path) -> Path:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    output = Path(destination)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_results(manifest), encoding="utf-8")
    return output

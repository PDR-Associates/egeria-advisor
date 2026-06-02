"""
OutcomeReporter — verifies and documents execution results for Plan Documents.

After a Plan Document has been executed via Dr.Egeria:
  1. Maps the command families used in the plan to relevant report_specs
     (using config/governance_report_map.yaml).
  2. Runs each report via ReportPipeline, filtering with object names extracted
     from the plan.
  3. Uses the LLM to synthesise a narrative outcome summary.
  4. Composes the full Outcome section (markdown).
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from loguru import logger


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

_report_map: Optional[Dict[str, List[str]]] = None


def _load_report_map() -> Dict[str, List[str]]:
    global _report_map
    if _report_map is not None:
        return _report_map

    cfg_path = Path(__file__).parent.parent.parent / "config" / "governance_report_map.yaml"
    try:
        with open(cfg_path) as f:
            _report_map = yaml.safe_load(f) or {}
    except Exception as exc:
        logger.warning(f"OutcomeReporter: could not load report map: {exc}")
        _report_map = {}
    return _report_map


# ---------------------------------------------------------------------------
# OutcomeReporter
# ---------------------------------------------------------------------------

class OutcomeReporter:
    """
    Generates the Outcome section for an executed Plan Document.

    Typical usage:
        reporter = OutcomeReporter()
        outcome_md = reporter.generate(plan_content, execution_output, perspective)
    """

    def generate(
        self,
        plan_content: str,
        execution_output: str,
        perspective: str | None = None,
    ) -> str:
        """
        Generate a markdown Outcome section for the plan document.

        Args:
            plan_content:      Full markdown of the plan that was executed.
            execution_output:  Raw output string returned by Dr.Egeria.
            perspective:       User's role (used to filter reports).

        Returns:
            Markdown string for the Outcome section (ready to append to the plan).
        """
        families = self._extract_families(plan_content)
        object_names = self._extract_display_names(plan_content)
        report_specs = self._select_report_specs(families)

        logger.info(
            f"OutcomeReporter: families={families}, "
            f"report_specs={report_specs}, objects={object_names[:5]}"
        )

        # Run verification reports
        report_results = self._run_reports(report_specs, object_names, perspective)

        # Determine overall status from execution output
        cmd_results = self._parse_command_results(execution_output)
        status = self._infer_status(execution_output)

        # Synthesise narrative
        narrative = self._synthesise_narrative(
            plan_content, execution_output, report_results, status
        )

        # Compose the section
        return self._compose_outcome_section(
            status=status,
            narrative=narrative,
            execution_output=execution_output,
            report_results=report_results,
            cmd_results=cmd_results,
        )

    # ---------------------------------------------------------------------- #
    # Family extraction                                                        #
    # ---------------------------------------------------------------------- #

    def _extract_families(self, plan_content: str) -> List[str]:
        """Extract unique template families referenced in the Command Sequence."""
        families: list[str] = []

        # Look for HTML comments like <!-- Step N: Command Name\n     rationale -->
        # and also plain ## Command headers, then map command name → family.
        command_section = self._extract_command_section(plan_content)
        if not command_section:
            return families

        # Extract H2 command names
        for m in re.finditer(r'^##\s+(.+)$', command_section, re.MULTILINE):
            cmd_name = m.group(1).strip()
            family = self._command_to_family(cmd_name)
            if family and family not in families:
                families.append(family)

        return families

    def _command_to_family(self, command_name: str) -> str | None:
        """Map a Dr.Egeria command name to its template family (best guess)."""
        cn = command_name.lower()
        if "glossary" in cn:
            return "glossary"
        if "actor" in cn or "person" in cn or "team" in cn or "appointment" in cn or "profile" in cn:
            return "actor manager"
        if "collection" in cn or "folder" in cn:
            return "collections"
        if "project" in cn or "campaign" in cn:
            return "projects"
        if "governance" in cn and ("zone" in cn or "definition" in cn or
                                   "policy" in cn or "role" in cn or "driver" in cn):
            return "governance officer"
        if "data" in cn and ("field" in cn or "struct" in cn or "class" in cn or "dict" in cn):
            return "data designer"
        if "digital product" in cn:
            return "digital product manager"
        if "solution" in cn or "blueprint" in cn:
            return "solution architect"
        return None

    # ---------------------------------------------------------------------- #
    # Display name extraction (used as report search filters)                 #
    # ---------------------------------------------------------------------- #

    def _extract_display_names(self, plan_content: str) -> List[str]:
        """
        Extract the values of '### Display Name' attributes from the command sequence.
        These become the search strings for verification reports.
        """
        names: list[str] = []
        command_section = self._extract_command_section(plan_content)
        if not command_section:
            return names

        for m in re.finditer(
            r'###\s+Display Name\s*\n([^\n#<>-][^\n]*)', command_section
        ):
            val = m.group(1).strip()
            if val and "TODO" not in val and val not in names:
                names.append(val)

        return names

    def _extract_command_section(self, plan_content: str) -> str:
        """Return only the '## Command Sequence' section of a plan document.

        Stops at '## Outcome' or end of file — not at ## command-name headers.
        """
        m = re.search(
            r'^##\s+Command Sequence\s*\n(.*?)(?=^##\s+Outcome\b|\Z)',
            plan_content,
            re.MULTILINE | re.DOTALL,
        )
        return m.group(1) if m else ""

    # ---------------------------------------------------------------------- #
    # Report selection                                                         #
    # ---------------------------------------------------------------------- #

    def _select_report_specs(self, families: List[str]) -> List[str]:
        """Return deduplicated list of report_spec names for the given families."""
        report_map = _load_report_map()
        specs: list[str] = []
        for fam in families:
            fam_key = fam.lower().strip()
            for spec in report_map.get(fam_key, []):
                if spec not in specs:
                    specs.append(spec)

        if not specs:
            for spec in report_map.get("_fallback", []):
                if spec not in specs:
                    specs.append(spec)

        return specs

    # ---------------------------------------------------------------------- #
    # Report execution                                                         #
    # ---------------------------------------------------------------------- #

    def _run_reports(
        self,
        report_specs: List[str],
        object_names: List[str],
        perspective: str | None,
    ) -> Dict[str, str]:
        """
        Run each report_spec, using the first object name as a search filter.

        Returns dict: {report_spec_name → markdown_output or error_message}
        """
        results: Dict[str, str] = {}

        if not report_specs:
            return results

        try:
            from advisor.report_pipeline import get_report_pipeline
            pipeline = get_report_pipeline()
        except Exception as exc:
            logger.warning(f"OutcomeReporter: could not load report pipeline: {exc}")
            return results

        # Use first object name as search filter, or "*" for all
        search_filter = object_names[0] if object_names else "*"

        for spec in report_specs:
            try:
                result = pipeline.run_report(
                    spec,
                    search_string=search_filter,
                    page_size=50,
                )
                if result and result.get("response"):
                    results[spec] = result["response"]
                    logger.info(f"OutcomeReporter: ran report {spec!r}")
                else:
                    logger.debug(f"OutcomeReporter: report {spec!r} returned no content")
            except Exception as exc:
                logger.warning(f"OutcomeReporter: report {spec!r} failed: {exc}")

        return results

    # ---------------------------------------------------------------------- #
    # Per-command result parsing                                               #
    # ---------------------------------------------------------------------- #

    _SUCCESS_WORDS = frozenset(("success", "created", "updated", "processed", "completed", "done", "linked", "✓"))
    _FAILURE_WORDS = frozenset(("error", "exception", "failed", "failure", "traceback", "✗"))

    def _parse_command_results(self, execution_output: str) -> List[Dict[str, str]]:
        """
        Try to extract per-command success/failure from Dr.Egeria output.

        Returns a list of {command, status, message} dicts.
        If the output has no recognisable structure, returns an empty list.
        """
        results: List[Dict[str, str]] = []

        # Split on H2-style markers that Dr.Egeria may echo back
        # Pattern: "## CommandName" or "Processing: CommandName" lines
        blocks = re.split(r'(?m)^(?:##\s+|Processing[:\s]+)(.+)$', execution_output)

        if len(blocks) < 3:
            # No recognisable per-command structure
            return results

        # blocks: [pre, cmd1, body1, cmd2, body2, ...]
        for i in range(1, len(blocks) - 1, 2):
            cmd = blocks[i].strip()
            body = blocks[i + 1] if i + 1 < len(blocks) else ""
            body_lower = body.lower()
            has_success = any(w in body_lower for w in self._SUCCESS_WORDS)
            has_failure = any(w in body_lower for w in self._FAILURE_WORDS)
            if has_failure and has_success:
                status = "Partial"
            elif has_failure:
                status = "Failed"
            elif has_success:
                status = "Success"
            else:
                status = "Unknown"
            # Grab first non-empty line of body as a short message
            msg = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
            results.append({"command": cmd, "status": status, "message": msg[:120]})

        return results

    # ---------------------------------------------------------------------- #
    # Status inference                                                         #
    # ---------------------------------------------------------------------- #

    def _infer_status(self, execution_output: str) -> str:
        # If per-command results are available, derive status from them
        cmd_results = self._parse_command_results(execution_output)
        if cmd_results:
            statuses = {r["status"] for r in cmd_results}
            if statuses == {"Success"}:
                return "Success"
            if "Failed" in statuses or "Unknown" in statuses:
                if "Success" in statuses or "Partial" in statuses:
                    return "Partial"
                return "Failed"
            return "Partial"

        # Fall back to keyword scan of the whole output
        out_lower = execution_output.lower()
        if any(w in out_lower for w in self._FAILURE_WORDS):
            if any(w in out_lower for w in self._SUCCESS_WORDS):
                return "Partial"
            return "Failed"
        if any(w in out_lower for w in self._SUCCESS_WORDS):
            return "Success"
        return "Unknown"

    # ---------------------------------------------------------------------- #
    # Narrative synthesis                                                      #
    # ---------------------------------------------------------------------- #

    def _synthesise_narrative(
        self,
        plan_content: str,
        execution_output: str,
        report_results: Dict[str, str],
        status: str,
    ) -> str:
        try:
            from advisor.llm_client import get_ollama_client
            llm = get_ollama_client()

            # Condense report results to avoid context overflow
            report_summary = ""
            for spec, content in list(report_results.items())[:3]:
                snippet = content[:400].replace("\n", " ")
                report_summary += f"\n- {spec}: {snippet}"

            prompt = (
                f"A governance plan was executed against Egeria with status: {status}.\n\n"
                f"Execution output (truncated):\n{execution_output[:600]}\n\n"
                f"Verification report excerpts:{report_summary or ' (none run)'}\n\n"
                f"Write a concise 2-4 sentence outcome narrative for a governance plan document. "
                f"Describe what was created, note any warnings or partial failures, and confirm "
                f"the overall result. Use plain language, no bullet points."
            )
            return llm.generate(prompt, temperature=0.3, max_tokens=300)
        except Exception as exc:
            logger.warning(f"OutcomeReporter: narrative generation failed: {exc}")
            return f"Execution completed with status: {status}."

    # ---------------------------------------------------------------------- #
    # Outcome section composition                                              #
    # ---------------------------------------------------------------------- #

    def _compose_outcome_section(
        self,
        status: str,
        narrative: str,
        execution_output: str,
        report_results: Dict[str, str],
        cmd_results: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines = [
            "## Outcome",
            f"**Executed:** {now}   **Status:** {status}",
            "",
            "### Summary",
            "",
            narrative.strip(),
            "",
        ]

        # Per-command breakdown — shown when Partial or Failed, or when parsed results exist
        if cmd_results and (status in ("Partial", "Failed") or len(cmd_results) > 1):
            lines += ["### Command Results", ""]
            lines += ["| Command | Status | Note |", "|---------|--------|------|"]
            status_icon = {"Success": "✓", "Failed": "✗", "Partial": "~", "Unknown": "?"}
            for r in cmd_results:
                icon = status_icon.get(r["status"], "?")
                lines.append(f"| {r['command']} | {icon} {r['status']} | {r['message']} |")
            lines.append("")

        if execution_output and len(execution_output.strip()) > 10:
            truncated = execution_output.strip()[:2000]
            lines += [
                "### Execution Output",
                "",
                "```",
                truncated,
                "```",
                "",
            ]

        if report_results:
            lines += ["### Verification Reports", ""]
            for spec, content in report_results.items():
                lines += [f"#### {spec}", "", content.strip()[:1500], ""]

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_reporter: Optional[OutcomeReporter] = None


def get_outcome_reporter() -> OutcomeReporter:
    global _reporter
    if _reporter is None:
        _reporter = OutcomeReporter()
    return _reporter

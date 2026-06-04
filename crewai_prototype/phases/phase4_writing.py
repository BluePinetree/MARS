"""phases/phase4_writing.py — Section-by-section paper writing (Phase 4).

Writing order (NOT reading order):
  Experiments → Introduction → Related_Works → Proposed_Method →
  Conclusion → References → Abstract

Experiments is written FIRST so every other section can cite real numbers.
Abstract is written LAST because it summarises everything already written.

Each section goes through:
  1. WriterAgent writes the section draft
  2. SelfVerifier scores it (result grounding, word count, citations, markdown)
  3. If score < SECTION_QUALITY_THRESHOLD: rewrite (up to MAX_SECTION_REVISIONS)
  4. If still below threshold after revisions: mark NEEDS_REVIEW, continue
  5. After all sections: integration check for cross-section coherence
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Callable, Optional

from crewai import Agent, Crew, Task

from core.handoff_models import (
    CodingResult,
    ExecutorResult,
    ExecutorResultSummary,
    PlanBundle,
    SectionResult,
    WriterContext,
    WritingResult,
)
from core.llm_factory import create_llm_for_agent
from crew_tools import WorkspaceReadTool, ReadResultTool, WriteReportTool
from pipeline_config.constants import (
    MAX_SECTION_REVISIONS,
    SECTION_MIN_WORDS,
    SECTION_QUALITY_THRESHOLD,
    WRITER_MAX_ITER,
)

logger = logging.getLogger(__name__)
EmitFn = Callable[[str, str, Optional[dict]], None]


# ── Write order ───────────────────────────────────────────────────────────────

WRITE_ORDER = [
    "Experiments",
    "Introduction",
    "Related_Works",
    "Proposed_Method",
    "Conclusion",
    "References",
    "Abstract",
]


# ── Task templates ────────────────────────────────────────────────────────────

_SECTION_TASK = """\
Write the "{section}" section of the research paper.

Research context:
  Topic: {topic}
  Problem: {problem}
  Success criteria: {criteria}

Experiment results (use these numbers — do NOT fabricate):
{exec_summary}

Previously written sections for context:
{prior_sections}

Requirements for "{section}":
{section_requirements}

Minimum word count: {min_words} words.
Write in English, academic style.
Use [1], [2], ... citation markers where appropriate.
Output ONLY the section content in Markdown — no section title header."""

_REVISE_TASK = """\
Revise the "{section}" section to address these quality issues:
{quality_issues}

Current draft:
{current_draft}

Experiment results to reference:
{exec_summary}

Fix all quality issues. Output ONLY the revised section content in Markdown."""

_INTEGRATION_TASK = """\
You are reviewing a complete research paper for cross-section coherence.

Paper draft (section excerpts):
{paper_excerpt}

Experiment ground truth:
{exec_summary}

Check for these coherence problems:
1. Number inconsistencies — a metric value in one section differs from another
2. Terminology drift — the same concept uses different names across sections
3. Contribution mismatch — contributions listed in Introduction not reflected in Conclusion
4. Abstract completeness — Abstract omits key results that appear in Experiments

Output a JSON object ONLY:
{{
  "overall_coherence": <float 0.0–1.0>,
  "issues": [
    {{
      "section": "<section name>",
      "problem": "<one sentence description>",
      "severity": "high" | "low",
      "fix_instruction": "<concrete instruction for the writer>"
    }}
  ]
}}

If no issues found, output: {{"overall_coherence": 1.0, "issues": []}}"""

_INTEGRATION_REVISE_TASK = """\
Revise the "{section}" section to fix this coherence issue:
{fix_instruction}

Current draft:
{current_draft}

Full paper context (other sections, for reference):
{paper_excerpt}

Output ONLY the revised section content in Markdown."""


# ── Section requirements ──────────────────────────────────────────────────────

_SECTION_REQS: dict[str, str] = {
    "Abstract": (
        "150–250 words. Cover: motivation, method, key results (with numbers), conclusion. "
        "Must include at least one metric value from the experiments."
    ),
    "Introduction": (
        "300–600 words. Motivate the problem, state contributions (2–4 bullet points), "
        "mention the experimental evaluation briefly."
    ),
    "Related_Works": (
        "400–800 words. Survey at least 5 related works. Group by topic. "
        "Contrast with this work's approach."
    ),
    "Proposed_Method": (
        "500–1000 words. Describe the method in detail. Include any equations if relevant. "
        "Reference the code design from the experiment."
    ),
    "Experiments": (
        "600–1200 words. Dataset description, evaluation metrics, baseline comparisons, "
        "results table (Markdown), ablation study if applicable. "
        "Every number must come from the actual experiment results provided."
    ),
    "Conclusion": (
        "200–400 words. Summarise key findings, limitations, and future work directions."
    ),
    "References": (
        "List at least 5 references in [1] Author, Title, Venue, Year format. "
        "Number them sequentially. Include seminal works for this domain."
    ),
}


# ── Self-verifier ─────────────────────────────────────────────────────────────

def _score_section(
    section: str,
    content: str,
    exec_result: ExecutorResult,
) -> tuple[float, list[str]]:
    """Score a section 0.0–1.0. Returns (score, list_of_issues)."""
    issues: list[str] = []
    weights = {"result_grounding": 0.35, "word_count": 0.30, "citations": 0.20, "syntax": 0.15}
    scores: dict[str, float] = {}

    # 1. Result grounding (only for sections that should reference numbers)
    number_sections = {"Experiments", "Abstract", "Conclusion"}
    if section in number_sections and exec_result.success and exec_result.metrics:
        # Check that at least one metric value appears in the text
        has_number = bool(re.search(r"\d+\.?\d*\s*(%|accuracy|loss|f1|auc|precision|recall)",
                                    content, re.IGNORECASE))
        # Also accept any digit sequence
        if not has_number:
            has_number = bool(re.search(r"\b\d{1,3}(\.\d+)?\b", content))
        scores["result_grounding"] = 1.0 if has_number else 0.0
        if not has_number:
            issues.append(
                f"{section} must include actual metric values from the experiment results."
            )
    else:
        scores["result_grounding"] = 1.0  # not applicable

    # 2. Word count
    word_count = len(content.split())
    min_words = SECTION_MIN_WORDS.get(section, 100)
    if word_count >= min_words:
        scores["word_count"] = 1.0
    else:
        ratio = word_count / min_words
        scores["word_count"] = ratio
        issues.append(
            f"{section} is too short ({word_count} words, minimum {min_words})."
        )

    # 3. Citations (for non-References sections)
    if section != "References":
        has_citation = bool(re.search(r"\[\d+\]", content))
        if section in ("Introduction", "Related_Works", "Proposed_Method"):
            scores["citations"] = 1.0 if has_citation else 0.3
            if not has_citation:
                issues.append(f"{section} should include at least one [N] citation.")
        else:
            scores["citations"] = 1.0
    else:
        # References: check at least 3 entries
        entries = re.findall(r"\[\d+\]", content)
        scores["citations"] = min(1.0, len(entries) / 5)
        if len(entries) < 5:
            issues.append(f"References needs at least 5 entries, found {len(entries)}.")

    # 4. Markdown syntax (no broken code blocks)
    open_blocks = content.count("```")
    if open_blocks % 2 != 0:
        scores["syntax"] = 0.0
        issues.append("Unclosed code block (``` count is odd).")
    else:
        scores["syntax"] = 1.0

    total = sum(weights[k] * scores[k] for k in weights)
    return total, issues


# ── Writer agent ──────────────────────────────────────────────────────────────

def _make_writer_agent(llm) -> Agent:
    return Agent(
        role="Research Paper Writer",
        goal=(
            "Write academic-quality paper sections. Include actual metric values from "
            "experiment results. Use proper citation markers. Output Markdown only."
        ),
        backstory=(
            "You are an ML paper writer who communicates experimental results clearly. "
            "You read the provided context and produce self-contained sections. "
            "Every number you write must come from the experiment results given to you."
        ),
        llm=llm,
        tools=[WorkspaceReadTool(), ReadResultTool()],
        verbose=True,
        allow_delegation=False,
        max_iter=WRITER_MAX_ITER,
    )


def _make_checker_agent(llm) -> Agent:
    return Agent(
        role="Research Paper Integration Checker",
        goal=(
            "Detect cross-section coherence problems: number inconsistencies, "
            "terminology drift, contribution mismatches, and incomplete abstracts. "
            "Output structured JSON only."
        ),
        backstory=(
            "You are a senior academic editor who reads full papers and finds subtle "
            "inconsistencies between sections. You never fabricate issues — only report "
            "actual mismatches you observe in the provided text. You output JSON only."
        ),
        llm=llm,
        tools=[],
        verbose=True,
        allow_delegation=False,
        max_iter=3,
    )


def _make_saver_agent(llm) -> Agent:
    return Agent(
        role="Report Saver",
        goal="Save the complete paper to disk using WriteReportTool.",
        backstory="You call WriteReportTool to persist the paper content.",
        llm=llm,
        tools=[WriteReportTool()],
        verbose=False,
        allow_delegation=False,
        max_iter=3,
    )


# ── Integration check ────────────────────────────────────────────────────────

def _build_paper_excerpt(contents: dict[str, str], max_chars_per_section: int = 600) -> str:
    """Build a compact paper excerpt for the integration checker."""
    read_order = [
        "Abstract", "Introduction", "Related_Works",
        "Proposed_Method", "Experiments", "Conclusion",
    ]
    parts = []
    for sec in read_order:
        if sec in contents and contents[sec].strip():
            excerpt = contents[sec][:max_chars_per_section]
            if len(contents[sec]) > max_chars_per_section:
                excerpt += "...[truncated]"
            parts.append(f"### {sec}\n{excerpt}")
    return "\n\n".join(parts)


def _run_integration_check(
    section_contents: dict[str, str],
    exec_result: ExecutorResult,
    llm,
) -> dict[str, list[str]]:
    """Run LLM-based cross-section coherence check.

    Returns:
        dict mapping section name → list of fix instructions for that section.
        Only high-severity issues are returned.
    """
    paper_excerpt = _build_paper_excerpt(section_contents)
    exec_summary = _build_exec_summary(exec_result)

    task = Task(
        description=_INTEGRATION_TASK.format(
            paper_excerpt=paper_excerpt,
            exec_summary=exec_summary,
        ),
        expected_output='JSON object with "overall_coherence" and "issues" list.',
        agent=_make_checker_agent(llm),
    )
    output = Crew(agents=[task.agent], tasks=[task], verbose=False).kickoff()
    raw = getattr(output, "raw", "") or str(output)

    data = _parse_integration_result(raw)
    issues_by_section: dict[str, list[str]] = {}
    for issue in data.get("issues", []):
        if issue.get("severity") != "high":
            continue
        sec = issue.get("section", "")
        fix = issue.get("fix_instruction", "")
        if sec and fix:
            issues_by_section.setdefault(sec, []).append(fix)
    return issues_by_section, data.get("overall_coherence", 1.0)


def _parse_integration_result(raw: str) -> dict:
    from core.json_extractor import extract_json_object as extract_json
    data = extract_json(raw)
    if isinstance(data, list) and data:
        data = data[0]
    if isinstance(data, dict):
        return data
    return {"overall_coherence": 1.0, "issues": []}


# ── Execution summary builder ─────────────────────────────────────────────────

def _build_exec_summary(exec_result: ExecutorResult) -> str:
    """ExecutorResult → integration check 프롬프트용 텍스트."""
    if not exec_result.success:
        return f"Experiment did not complete successfully (return_code={exec_result.return_code})."
    lines = [f"Experiment completed successfully (return_code={exec_result.return_code}, duration={exec_result.duration_s:.1f}s)."]
    if exec_result.metrics:
        lines.append("Metrics:")
        for k, v in exec_result.metrics.items():
            lines.append(f"  {k}: {v}")
    if exec_result.stdout_tail:
        lines.append(f"Output excerpt:\n{exec_result.stdout_tail[:500]}")
    if exec_result.result_json_path:
        lines.append(f"Result file: {exec_result.result_json_path}")
    return "\n".join(lines)


def _build_exec_summary_text(exec_summary: ExecutorResultSummary) -> str:
    """ExecutorResultSummary → Writer 프롬프트용 텍스트 (압축된 입력 사용)."""
    if not exec_summary.success:
        return "Experiment did not complete successfully. Report partial or failed results."
    lines = ["Experiment completed successfully."]
    if exec_summary.metrics:
        lines.append("Metrics:")
        for k, v in exec_summary.metrics.items():
            lines.append(f"  {k}: {v}")
    if exec_summary.stdout_excerpt:
        lines.append(f"Output excerpt:\n{exec_summary.stdout_excerpt}")
    if exec_summary.result_json_path:
        lines.append(f"Result file: {exec_summary.result_json_path}")
    return "\n".join(lines)


# ── Phase 4 main function ─────────────────────────────────────────────────────

def run_writing_phase(
    plan: PlanBundle,
    exec_result: ExecutorResult,
    emit: EmitFn,
    llm=None,
    coding_result: Optional[CodingResult] = None,
    writer_context: Optional[WriterContext] = None,
) -> WritingResult:
    """Write the paper section by section.

    coding_result / writer_context 가 제공되면 ContextCompressor로 압축해
    Writer 프롬프트 크기를 제한한다. 없으면 기존 방식으로 동작한다.

    Returns:
        WritingResult with path to the combined paper and per-section outcomes.
    """
    from orchestration.context_compressor import ContextCompressor

    writer_llm = create_llm_for_agent("paper_writer")
    checker_llm = create_llm_for_agent("result_analyzer")

    paper_dir = Path(plan.workspace.paper_dir)

    # WriterContext 구성: 외부에서 주입됐으면 그대로 사용, 없으면 직접 압축
    if writer_context is None:
        compressor = ContextCompressor()
        exec_summary_obj = compressor.compress_executor_result(exec_result)
        if coding_result is not None:
            writer_context = compressor.build_writer_context(
                plan=plan,
                coding_result=coding_result,
                exec_result=exec_result,
            )
        else:
            writer_context = WriterContext(
                exec_summary=exec_summary_obj,
            )

    exec_summary = _build_exec_summary_text(writer_context.exec_summary)
    topic = plan.planner.problem_statement or "Research experiment"
    criteria_str = "; ".join(plan.planner.success_criteria[:3])

    section_contents: dict[str, str] = {}
    section_results: list[SectionResult] = []

    for section in WRITE_ORDER:
        emit(
            "AGENT_MESSAGE",
            f"[Phase 4] Writing section: {section}",
            {"section": section},
        )

        # Build prior sections context (summaries to avoid context explosion)
        prior_parts = []
        for prev_sec in WRITE_ORDER:
            if prev_sec == section:
                break
            if prev_sec in section_contents:
                preview = section_contents[prev_sec][:400]
                prior_parts.append(f"## {prev_sec} (excerpt)\n{preview}...")
        prior_text = "\n\n".join(prior_parts) if prior_parts else "(none yet)"

        best_content = ""
        best_score = 0.0
        issues: list[str] = []

        for revision in range(MAX_SECTION_REVISIONS + 1):
            if revision == 0:
                # Initial write
                task_desc = _SECTION_TASK.format(
                    section=section,
                    topic=topic,
                    problem=plan.planner.problem_statement[:300],
                    criteria=criteria_str,
                    exec_summary=exec_summary,
                    prior_sections=prior_text,
                    section_requirements=_SECTION_REQS.get(section, ""),
                    min_words=SECTION_MIN_WORDS.get(section, 100),
                )
            else:
                # Revision
                task_desc = _REVISE_TASK.format(
                    section=section,
                    quality_issues="\n".join(f"- {i}" for i in issues),
                    current_draft=best_content,
                    exec_summary=exec_summary,
                )

            task = Task(
                description=task_desc,
                expected_output=f"The {section} section in Markdown.",
                agent=_make_writer_agent(writer_llm),
            )
            output = Crew(agents=[task.agent], tasks=[task], verbose=False).kickoff()
            content = getattr(output, "raw", "") or str(output)

            score, issues = _score_section(section, content, exec_result)

            if score > best_score:
                best_score = score
                best_content = content

            emit(
                "SECTION_DRAFT_DONE",
                f"[Phase 4] {section} draft (revision {revision}): "
                f"score={score:.2f}, words={len(content.split())}",
                {"section": section, "revision": revision, "score": score,
                 "issues": issues, "word_count": len(content.split())},
            )

            if score >= SECTION_QUALITY_THRESHOLD:
                break

            if revision == MAX_SECTION_REVISIONS:
                emit(
                    "AGENT_MESSAGE",
                    f"[Phase 4] {section} below quality threshold after {revision} revision(s) "
                    f"(score={best_score:.2f}). Marking NEEDS_REVIEW.",
                    {"section": section, "needs_review": True, "score": best_score},
                )

        section_contents[section] = best_content
        section_results.append(SectionResult(
            section=section,
            content=best_content,
            quality_score=best_score,
            revisions=min(revision, MAX_SECTION_REVISIONS),
            needs_review=(best_score < SECTION_QUALITY_THRESHOLD),
        ))

        # Save section draft to disk
        section_file = paper_dir / f"{section.lower()}.md"
        section_file.write_text(best_content, encoding="utf-8")

    # ── Integration check ─────────────────────────────────────────────────────
    emit(
        "AGENT_MESSAGE",
        "[Phase 4] Running cross-section coherence check...",
        {"phase": "integration_check"},
    )
    issues_by_section, coherence_score = _run_integration_check(
        section_contents, exec_result, checker_llm
    )

    if issues_by_section:
        emit(
            "AGENT_MESSAGE",
            f"[Phase 4] Coherence score: {coherence_score:.2f}. "
            f"High-severity issues in: {list(issues_by_section.keys())}. Revising...",
            {"coherence_score": coherence_score, "sections_to_fix": list(issues_by_section.keys())},
        )
        paper_excerpt = _build_paper_excerpt(section_contents)
        for sec, fix_instructions in issues_by_section.items():
            if sec not in section_contents:
                continue
            task = Task(
                description=_INTEGRATION_REVISE_TASK.format(
                    section=sec,
                    fix_instruction="\n".join(f"- {fi}" for fi in fix_instructions),
                    current_draft=section_contents[sec],
                    paper_excerpt=paper_excerpt,
                ),
                expected_output=f"The revised {sec} section in Markdown.",
                agent=_make_writer_agent(writer_llm),
            )
            output = Crew(agents=[task.agent], tasks=[task], verbose=False).kickoff()
            revised = getattr(output, "raw", "") or str(output)
            if revised.strip():
                section_contents[sec] = revised
                # Update the matching SectionResult
                for sr in section_results:
                    if sr.section == sec:
                        sr.content = revised
                        break
                section_file = paper_dir / f"{sec.lower()}.md"
                section_file.write_text(revised, encoding="utf-8")
            emit(
                "AGENT_MESSAGE",
                f"[Phase 4] Integration revision done: {sec}",
                {"section": sec, "fixes": fix_instructions},
            )
    else:
        emit(
            "AGENT_MESSAGE",
            f"[Phase 4] Coherence check passed (score={coherence_score:.2f}). No revisions needed.",
            {"coherence_score": coherence_score},
        )

    # ── Assemble final paper ──────────────────────────────────────────────────
    paper_path = _assemble_paper(plan, section_contents, section_results, paper_dir)

    overall = (
        sum(s.quality_score for s in section_results) / len(section_results)
        if section_results else 0.0
    )

    emit(
        "PHASE_COMPLETE",
        f"[Phase 4] Paper written. Overall quality: {overall:.2f}, "
        f"coherence: {coherence_score:.2f}. Path: {paper_path}",
        {"paper_path": str(paper_path), "overall_quality": overall,
         "coherence_score": coherence_score},
    )

    return WritingResult(
        paper_path=str(paper_path),
        sections=section_results,
        overall_quality=overall,
    )


def _assemble_paper(
    plan: PlanBundle,
    contents: dict[str, str],
    results: list[SectionResult],
    paper_dir: Path,
) -> Path:
    """Combine all sections into a single paper.md in reading order."""
    read_order = [
        "Abstract",
        "Introduction",
        "Related_Works",
        "Proposed_Method",
        "Experiments",
        "Conclusion",
        "References",
    ]

    needs_review = [s.section for s in results if s.needs_review]
    header = (
        f"# {plan.planner.problem_statement[:120]}\n\n"
        f"> **Generated by Research System V4**  \n"
        f"> Overall quality score: "
        f"{sum(s.quality_score for s in results)/max(len(results),1):.2f}\n"
    )
    if needs_review:
        header += f"> Sections needing review: {', '.join(needs_review)}\n"
    header += "\n---\n\n"

    body_parts = [header]
    for sec in read_order:
        if sec in contents and contents[sec].strip():
            display_name = sec.replace("_", " ")
            body_parts.append(f"## {display_name}\n\n{contents[sec].strip()}\n\n")

    paper_path = paper_dir / "paper.md"
    paper_path.write_text("".join(body_parts), encoding="utf-8")
    return paper_path

"""
Documentation Conformance, ID Traceability & Link Integrity Tests.
==================================================================
Validates that:
1. docs/LIMITATIONS.md contains all required sections and M2-L1 to M2-L15 with all 6 required fields + evidence.
2. docs/month3_planning.md contains required sections, candidates C1 to C5 with 7-field templates and measurable criteria, and that all cited M2-L IDs exist.
3. docs/month2_ai_track_summary.md contains all 6 required sections, walkthrough agenda, and valid cross-references.
4. All relative and file:/// links pointing into the repository resolve to existing filesystem paths.
"""

import re
import urllib.parse
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LIMITATIONS_MD = REPO_ROOT / "docs" / "LIMITATIONS.md"
PLANNING_MD = REPO_ROOT / "docs" / "month3_planning.md"
SUMMARY_MD = REPO_ROOT / "docs" / "month2_ai_track_summary.md"


def test_limitations_md_structure_and_m2_entries():
    """Validates structure and completeness of docs/LIMITATIONS.md Section 8."""
    assert LIMITATIONS_MD.exists()
    content = LIMITATIONS_MD.read_text(encoding="utf-8")

    # Header and append-only baseline checks
    assert "Week 4 baseline + Month 2 addendum" in content
    assert "## 6. Month 2 Debate-Layer Design Implications Summary" in content
    assert "## 7. Open Gaps and Month 2/3 Tasks" in content
    assert "## 8. Month 2 Findings & Limitations Profile (M2-L1 to M2-L15)" in content

    # Assert all 15 limitation IDs are present
    for i in range(1, 16):
        lim_id = f"M2-L{i}"
        assert lim_id in content, f"Missing limitation ID {lim_id} in LIMITATIONS.md"

    # Assert required 6 attributes + Evidence exist in each profile table
    required_attrs = [
        "Failure mode",
        "Root cause",
        "Observed behaviour",
        "Current mitigation",
        "Residual risk",
        "Debate-layer",
        "Evidence",
    ]
    for attr in required_attrs:
        matches = len(re.findall(re.escape(attr), content, re.IGNORECASE))
        # There should be at least 15 occurrences of each attribute in section 8
        assert matches >= 15, f"Attribute '{attr}' occurs only {matches} times in LIMITATIONS.md"


def test_month3_planning_structure_and_traceability():
    """Validates docs/month3_planning.md structure, candidates C1-C5, and M2-L traceability."""
    assert PLANNING_MD.exists()
    content = PLANNING_MD.read_text(encoding="utf-8")

    # Required section headings
    assert "## 1. Executive Context" in content
    assert "## 2. Candidate Priorities for Month 3" in content
    assert "## 3. Prioritisation Matrix" in content
    assert "## 4. Proposed Week-by-Week Month 3 Roadmap" in content
    assert "## 5. Architectural Decisions Needed from the Team" in content
    assert "## 6. Non-Goals for Month 3" in content

    # All candidates C1 to C5 present
    for c in ["Candidate C1:", "Candidate C2:", "Candidate C3:", "Candidate C4:", "Candidate C5:"]:
        assert c in content, f"Missing {c} in month3_planning.md"

    # Template fields for candidates
    for field in ["Motivation:", "Proposed Scope:", "Deliverables:", "Measurable Success Criteria:", "Effort:", "Risks:", "Owner Track(s):"]:
        count = len(re.findall(re.escape(field), content))
        assert count >= 5, f"Field '{field}' missing from some candidates (found {count})"

    # Traceability: extract all M2-L IDs cited in planning doc and assert they exist in LIMITATIONS.md
    lim_content = LIMITATIONS_MD.read_text(encoding="utf-8")
    cited_ids = set(re.findall(r"\bM2-L\d+\b", content))
    assert len(cited_ids) > 0, "No M2-L IDs cited in planning doc"
    for cid in cited_ids:
        assert cid in lim_content, f"Planning doc cites {cid} which does not exist in LIMITATIONS.md"

    # Measurable criteria contain numerical thresholds
    criteria_blocks = re.findall(r"Measurable Success Criteria:\s*(.*?)(?=\*\s*\*\*Effort:|\Z)", content, re.DOTALL)
    for block in criteria_blocks:
        assert re.search(r"\d+%|\d+\.\d+|\b\d+\b", block), f"Criteria block missing numeric threshold: {block}"


def test_summary_doc_structure_and_walkthrough():
    """Validates docs/month2_ai_track_summary.md structure and content."""
    assert SUMMARY_MD.exists()
    content = SUMMARY_MD.read_text(encoding="utf-8")

    # Header and Agenda
    assert "10-Minute Milestone Walkthrough Agenda" in content
    assert "## 1. What Month 2 Shipped" in content
    assert "## 2. Benchmark Results: Both Paths (Audited Evaluation)" in content
    assert "## 3. What the AI Track Actually Learned" in content
    assert "## 4. Biggest Open Reliability & Latency Concerns" in content
    assert "## 5. Open Questions for Month 3" in content
    assert "## 6. Bottom Line for the Team" in content

    # All 5 findings present
    for f_idx in range(1, 6):
        assert f"Finding {f_idx}:" in content

    # All 5 questions present
    for q_idx in range(1, 6):
        assert f"Q{q_idx}" in content

    # Cross references to M2-L IDs and C1-C5
    for i in range(1, 16):
        assert f"M2-L{i}" in content
    for c_idx in range(1, 6):
        assert f"C{c_idx}" in content


def test_markdown_file_links_resolve_on_disk():
    """
    Scans all three docs for internal file links (both relative and file:/// links)
    and verifies that the target files exist in the repository workspace.
    """
    docs = [LIMITATIONS_MD, PLANNING_MD, SUMMARY_MD]
    for doc in docs:
        content = doc.read_text(encoding="utf-8")
        # Find markdown links: [text](link)
        links = re.findall(r"\[([^\]]+)\]\(([^)]+)\)", content)
        for text, link in links:
            # Skip external web URLs, mailto, and pure in-page anchors (#anchor)
            if link.startswith(("http://", "https://", "mailto:")) or link.startswith("#"):
                continue

            # Strip in-page anchors if present: file.md#anchor -> file.md
            clean_link = link.split("#")[0]
            if not clean_link:
                continue

            # Handle file:/// absolute paths
            if clean_link.startswith("file:///"):
                # Strip file:/// and normalize Windows drive letter
                path_str = urllib.parse.unquote(clean_link.replace("file:///", ""))
                # e.g. d:/Grad Projectt eccuuuuu/docs/...
                target_path = Path(path_str)
            else:
                # Relative link relative to current doc directory
                clean_rel = urllib.parse.unquote(clean_link)
                target_path = (doc.parent / clean_rel).resolve()

            # Assert existence
            assert target_path.exists(), f"Broken link in {doc.name}: [{text}]({link}) -> {target_path} not found"

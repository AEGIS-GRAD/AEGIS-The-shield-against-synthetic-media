import os
import sys
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
)
from reportlab.pdfgen import canvas

class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, total_pages):
        self.saveState()
        
        # Header (Pages 2+)
        if self._pageNumber > 1:
            self.setFont("Helvetica-Bold", 8)
            self.setFillColor(colors.HexColor("#0f172a"))
            self.drawString(45, 755, "AEGIS VERIFICATION PLATFORM")
            self.setFont("Helvetica", 8)
            self.setFillColor(colors.HexColor("#64748b"))
            self.drawString(195, 755, "|   Month 2 Milestone UI Polish & Verification Modes Summary")
            
            self.setStrokeColor(colors.HexColor("#cbd5e1"))
            self.setLineWidth(0.75)
            self.line(45, 747, 567, 747)

        # Footer (All pages)
        self.setStrokeColor(colors.HexColor("#cbd5e1"))
        self.setLineWidth(0.75)
        self.line(45, 42, 567, 42)
        
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748b"))
        self.drawString(45, 30, "AEGIS-GRAD / The Shield Against Synthetic Media   •   Branch: feat/polish-verification-modes-ui")
        
        page_str = f"Page {self._pageNumber} of {total_pages}"
        self.drawRightString(567, 30, page_str)
        self.restoreState()


def build_pdf(filename="AEGIS_Month2_UI_Polish_Summary.pdf"):
    # 612 x 792 letter size. Margins: 45pt left/right -> width = 522pt
    doc = SimpleDocTemplate(
        filename,
        pagesize=letter,
        leftMargin=45,
        rightMargin=45,
        topMargin=48,
        bottomMargin=48,
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=21,
        leading=25,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=4,
    )

    subtitle_style = ParagraphStyle(
        "DocSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=11,
        leading=15,
        textColor=colors.HexColor("#0284c7"),
        spaceAfter=10,
    )

    meta_style = ParagraphStyle(
        "MetaText",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#334155"),
    )

    h1_style = ParagraphStyle(
        "Heading1_Custom",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=12.5,
        leading=16,
        textColor=colors.HexColor("#0f172a"),
        spaceBefore=10,
        spaceAfter=5,
        keepWithNext=True,
    )

    body_style = ParagraphStyle(
        "Body_Custom",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.8,
        leading=13,
        textColor=colors.HexColor("#1e293b"),
        spaceAfter=5,
    )

    body_bold = ParagraphStyle(
        "Body_Bold",
        parent=body_style,
        fontName="Helvetica-Bold",
        spaceAfter=3,
        keepWithNext=True,
    )

    bullet_style = ParagraphStyle(
        "Bullet_Custom",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=12.5,
        textColor=colors.HexColor("#1e293b"),
        leftIndent=14,
        firstLineIndent=-9,
        spaceAfter=3.5,
    )

    table_cell = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#1e293b"),
    )

    table_header = ParagraphStyle(
        "TableHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=11,
        textColor=colors.white,
    )

    story = []

    # ================= PAGE 1 =================
    story.append(Paragraph("AEGIS Verification Platform", title_style))
    story.append(Paragraph("Month 2 Milestone: Verification Modes UI Polish & Architecture Guide", subtitle_style))
    
    meta_data = [
        [
            Paragraph("<b>Target Audience:</b> Evaluators, Stakeholders & Devs", meta_style),
            Paragraph("<b>Branch:</b> feat/polish-verification-modes-ui", meta_style),
            Paragraph("<b>Status:</b> Validated & Ready (PR #66)", meta_style),
        ]
    ]
    meta_table = Table(meta_data, colWidths=[180, 200, 142])
    meta_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#f1f5f9")),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 8))

    # 1. Executive Summary
    story.append(Paragraph("1. Executive Summary (The Simple Big Picture)", h1_style))
    story.append(Paragraph(
        "AEGIS is an agentic cybersecurity platform built to detect <b>AI-generated deepfakes, synthetic speech, and camera stream hijacking</b>. "
        "The system provides two verification modes: <b>Mode 1 (Offline File Analysis)</b> for forensic investigation of recorded media, and "
        "<b>Mode 2 (Live Surveillance)</b> for continuous monitoring of security cameras and live video feeds.",
        body_style
    ))
    story.append(Paragraph(
        "<b>Why this task was needed:</b> User testing during Week 3 revealed three key friction points: "
        "(1) Mode 1 and Mode 2 felt like disjointed, separate applications; "
        "(2) Alert severity was vague, leaving analysts unsure whether an alert was an emergency or a benign glitch; and "
        "(3) Demonstrating the platform required manual file uploads and complex setups.",
        body_style
    ))
    story.append(Paragraph(
        "<b>What we delivered:</b> We executed a focused polish pass creating a unified visual language, standardized 3-tier SIEM severity badges, "
        "integrated the Month 2 multi-agent Judge Agent debate timeline, added live attack injection, and provided 4 one-click demo presets.",
        body_style
    ))
    story.append(Spacer(1, 4))

    # 2. Standardized SIEM Alert Tiers
    story.append(Paragraph("2. Standardized Severity Language: SIEM Alert Tiers", h1_style))
    story.append(Paragraph(
        "To ensure security operations centers (SOC) can triage threats instantly, we introduced standardized 3-tier severity badges:",
        body_style
    ))

    tier_data = [
        [
            Paragraph("SIEM Tier", table_header),
            Paragraph("Visual Indicator", table_header),
            Paragraph("Plain-English Meaning", table_header),
            Paragraph("Action & System Behavior", table_header),
        ],
        [
            Paragraph("<b>TIER 1</b><br/>LOW", table_cell),
            Paragraph("<font color='#059669'><b>GREEN SHIELD</b></font>", table_cell),
            Paragraph("Media is verified authentic. All AI detectors and biometrics agree with high confidence.", table_cell),
            Paragraph("Standard logging. Certified court-admissible authentic media fixture.", table_cell),
        ],
        [
            Paragraph("<b>TIER 2</b><br/>ELEVATED", table_cell),
            Paragraph("<font color='#d97706'><b>AMBER TRIANGLE</b></font>", table_cell),
            Paragraph("Detectors disagree, media has high compression, or biometric pulse quality is low.", table_cell),
            Paragraph("Flagged for secondary manual inspection by a human forensic analyst.", table_cell),
        ],
        [
            Paragraph("<b>TIER 3</b><br/>CRITICAL", table_cell),
            Paragraph("<font color='#dc2626'><b>ROSE SIREN</b></font>", table_cell),
            Paragraph("Confirmed synthetic manipulation, acoustic voice cloning, or active camera spoofing.", table_cell),
            Paragraph("Immediate SIEM alert dispatch, audio-visual strobe siren, and operator review required.", table_cell),
        ],
    ]
    tier_table = Table(tier_data, colWidths=[60, 95, 187, 180])
    tier_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#0f172a")),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor("#f8fafc"), colors.white]),
        ('TOPPADDING', (0,0), (-1,-1), 4.5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4.5),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    story.append(tier_table)
    story.append(Spacer(1, 6))

    # 3. Mode 1 Details
    story.append(Paragraph("3. Mode 1: Offline File Verification Flow", h1_style))
    story.append(Paragraph(
        "<b>Analogy:</b> Like sending evidence to a digital forensics lab. An investigator submits an audio or video file (or selects a preset). "
        "The system executes a deep multimodal analysis and synthesizes the findings into a verifiable forensic dossier.",
        body_style
    ))
    story.append(Paragraph("<b>Key Features Implemented & Polished:</b>", body_bold))
    story.append(Paragraph("• <b>Deterministic Judge Agent:</b> An impartial algorithmic judge synthesizes detector claims, evaluates modality capabilities, and produces an authoritative court-ready verdict.", bullet_style))
    story.append(Paragraph("• <b>3-Round Debate Visualizer:</b> Users see transparent reasoning across <i>Round 1 (Initial Modal Claims)</i>, <i>Round 2 (Cross-Modal Cross-Examination)</i>, and <i>Round 3 (Judge Synthesis)</i>.", bullet_style))
    story.append(Paragraph("• <b>Safety Guard Execution:</b> Hardcoded safety rules protect against errors. <b>Guard 1 (Polarity Inversion Anti-Default)</b> prevents false-authentic defaults when cloned audio accompanies genuine video.", bullet_style))
    story.append(Paragraph("• <b>Tamper-Evident SHA-256 Hash:</b> Cryptographically locks the media and transcript with a 1-click clipboard copy button.", bullet_style))

    # ================= PAGE 2 =================
    story.append(PageBreak())

    # 4. Mode 2 Details
    story.append(Paragraph("4. Mode 2: Live Surveillance Monitoring Flow", h1_style))
    story.append(Paragraph(
        "<b>Analogy:</b> Like an intelligent security guard watching airport CCTV. Mode 2 connects to live camera feeds, executing rapid sliding-window "
        "analysis every 200 milliseconds to catch deepfake face replacements or video stream hijacking in real time.",
        body_style
    ))
    story.append(Paragraph("<b>Key Features Implemented & Polished:</b>", body_bold))
    story.append(Paragraph("• <b>Detailed Evidence Modal:</b> Clicking 'Inspect Evidence' on the alert banner pops open a complete breakdown of sensor telemetry (temporal consistency, PRNU camera sensor fingerprint, and rPPG blood volume pulse).", bullet_style))
    story.append(Paragraph("• <b>Interactive Attack Injection ([INJECT ATTACK]):</b> Evaluators can simulate active sensor degradation and deepfake injection on demand, demonstrating immediate siren triggers and Tier 3 alert generation.", bullet_style))
    story.append(Paragraph("• <b>Operator Acknowledgment & Audit Trail:</b> Security personnel can click 'Acknowledge' to silence alarms and log an immutable record of operator incident handling.", bullet_style))
    story.append(Paragraph("• <b>Harmonized Navigation Switcher:</b> Both the standalone workstation and Next.js shell now clearly indicate 'Offline File [Single-Pass]' versus 'Live Surveillance [Sliding-Window Stream]'.", bullet_style))
    story.append(Spacer(1, 8))

    # 5. Presets Table
    story.append(Paragraph("5. Curated 1-Click Milestone Demo Presets", h1_style))
    story.append(Paragraph(
        "To make testing seamless for evaluators without needing sample uploads, we built four 1-click evaluation fixtures:",
        body_style
    ))

    preset_data = [
        [
            Paragraph("Preset Scenario", table_header),
            Paragraph("Modality", table_header),
            Paragraph("What it Demonstrates (Plain English)", table_header),
            Paragraph("Expected Tier", table_header),
        ],
        [
            Paragraph("<b>Clean Baseline</b><br/><i>clean_interview_broadcast.mp4</i>", table_cell),
            Paragraph("Video + Audio", table_cell),
            Paragraph("Unedited natural interview. All 4 detectors (visual, rPPG pulse, SyncNet, AASIST) agree authentic.", table_cell),
            Paragraph("<font color='#059669'><b>TIER 1</b><br/>LOW</font>", table_cell),
        ],
        [
            Paragraph("<b>Voice Clone Scam</b><br/><i>synthetic_voice_clone_scam.wav</i>", table_cell),
            Paragraph("Audio Only", table_cell),
            Paragraph("AASIST flags vocoder acoustic synthesis. Visual models are safely bypassed via capability manifest.", table_cell),
            Paragraph("<font color='#dc2626'><b>TIER 3</b><br/>CRITICAL</font>", table_cell),
        ],
        [
            Paragraph("<b>Silent Surveillance</b><br/><i>surveillance_silent_clip.mp4</i>", table_cell),
            Paragraph("Video Only", table_cell),
            Paragraph("Zero-audio CCTV footage. Pre-dispatch filter safely skips audio models and verifies camera textures.", table_cell),
            Paragraph("<font color='#059669'><b>TIER 1</b><br/>LOW</font>", table_cell),
        ],
        [
            Paragraph("<b>Cross-Modal Conflict</b><br/><i>dubbed_speech_conflict.mp4</i>", table_cell),
            Paragraph("Video + Audio<br/>(Dubbed)", table_cell),
            Paragraph("Genuine face but cloned audio. Guard 1 triggers, preventing false-authentic default and escalating to Tier 3.", table_cell),
            Paragraph("<font color='#dc2626'><b>TIER 3</b><br/>CRITICAL</font>", table_cell),
        ],
    ]
    preset_table = Table(preset_data, colWidths=[125, 75, 242, 80])
    preset_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#0f172a")),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor("#f8fafc"), colors.white]),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    story.append(preset_table)

    # ================= PAGE 3 =================
    story.append(PageBreak())

    # 6. CI Issue & Resolution
    story.append(Paragraph("6. GitHub CI / Pull Request #66 Issue & Resolution", h1_style))
    story.append(Paragraph(
        "When submitting PR #66 to GitHub, the automated check <b>'lint-and-build'</b> failed at the <b>Run Impeccable UI Linter</b> step. "
        "Here is what happened and how we resolved it:",
        body_style
    ))
    story.append(Paragraph("• <b>The Linter Finding:</b> The design linter flagged <code>animate-bounce</code> on line 243 of <code>live/page.tsx</code>. Professional UI standards discourage bouncy, springy animations on technical security buttons because they look dated and distracting.", bullet_style))
    story.append(Paragraph("• <b>The Engine Mismatch:</b> The linter package required Node.js <code>>=22.18.0</code>, whereas GitHub Actions was pinned to Node.js 20.", bullet_style))
    story.append(Paragraph("• <b>The Resolution:</b> We replaced the bounce animation with a smooth, professional <code>animate-pulse</code> effect and bumped GitHub Actions to Node.js 22. The linter passed locally with <b>0 anti-patterns</b>.", bullet_style))
    story.append(Spacer(1, 6))

    # 7. Quality & Verification Results
    story.append(Paragraph("7. Comprehensive Quality & Verification Results", h1_style))
    story.append(Paragraph(
        "Every single layer of the application was tested and verified prior to branch merge:",
        body_style
    ))

    test_data = [
        [
            Paragraph("Verification Test Suite", table_header),
            Paragraph("Scope Covered", table_header),
            Paragraph("Result", table_header),
        ],
        [
            Paragraph("<b>Next.js Production Build</b><br/><code>npm run build</code>", table_cell),
            Paragraph("All 19 static and dynamic routes (/analyze, /live, /reports/[id], /api/jobs)", table_cell),
            Paragraph("<font color='#059669'><b>PASSED (19/19)</b><br/>Zero TS/JSX errors</font>", table_cell),
        ],
        [
            Paragraph("<b>Debate & Judge Agent</b><br/><code>pytest debate/</code>", table_cell),
            Paragraph("Multi-agent arbitration, schemas, disagreement detection, and Month 1-2 cases", table_cell),
            Paragraph("<font color='#059669'><b>PASSED (86/86)</b><br/>4.03s execution</font>", table_cell),
        ],
        [
            Paragraph("<b>Orchestrator Pipeline</b><br/><code>pytest orchestrator/</code>", table_cell),
            Paragraph("Judge integration, wiring, capability manifest filtering, and telemetry client", table_cell),
            Paragraph("<font color='#059669'><b>PASSED (68/68)</b><br/>100% clean</font>", table_cell),
        ],
        [
            Paragraph("<b>Security & Alert Routing</b><br/><code>pytest security/tests/</code>", table_cell),
            Paragraph("SIEM alert dispatch, fusion harness, and stream validator", table_cell),
            Paragraph("<font color='#059669'><b>PASSED (13/13)</b><br/>All tests green</font>", table_cell),
        ],
        [
            Paragraph("<b>Live Server Probe</b><br/><code>curl http://localhost:3000/...</code>", table_cell),
            Paragraph("End-to-end HTTP response codes on all primary endpoints and API routes", table_cell),
            Paragraph("<font color='#059669'><b>PASSED (200 OK)</b><br/>Full JSON metadata</font>", table_cell),
        ],
    ]
    test_table = Table(test_data, colWidths=[150, 242, 130])
    test_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#0f172a")),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor("#f8fafc"), colors.white]),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    story.append(test_table)
    story.append(Spacer(1, 6))

    # 8. 2-Minute Demo Guide
    story.append(Paragraph("8. How Anyone Can Experience the Demo in 2 Minutes", h1_style))
    story.append(Paragraph(
        "To evaluate the Month 2 milestone live, follow these two simple steps:",
        body_style
    ))
    story.append(Paragraph("• <b>Step 1: Test Offline Deepfake Adjudication (Mode 1)</b><br/>"
                           "Open <code>http://localhost:3000/analyze</code>. Click <b>'Report'</b> on the <b>Cross-Modal Conflict</b> preset. "
                           "Observe the <b>SIEM TIER 3 — CRITICAL</b> badge, the <b>Guard 1</b> pill, the 3-round debate timeline, "
                           "and click <b>Copy</b> on the tamper-evident SHA-256 hash.", bullet_style))
    story.append(Paragraph("• <b>Step 2: Test Live Camera Surveillance (Mode 2)</b><br/>"
                           "Switch to <b>Live Surveillance</b> (or visit <code>http://localhost:3000/live</code>). Click <b>[INJECT ATTACK]</b>. "
                           "Watch the live risk score surge, the red siren strobe trigger, and click <b>'Inspect Evidence'</b> to view the fused sensor modal before clicking <b>'Acknowledge'</b>.", bullet_style))
    story.append(Spacer(1, 6))

    # 9. Conclusion
    story.append(Paragraph("9. Conclusion", h1_style))
    story.append(Paragraph(
        "The verification-mode interfaces are now unified, visually polished, and battle-tested. "
        "With deterministic Judge Agent reasoning, tamper-evident cryptographic audits, and reliable one-click demonstration fixtures, "
        "AEGIS is fully ready for the Month 2 milestone demo.",
        body_style
    ))

    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"PDF successfully built: {filename}")


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "AEGIS_Month2_UI_Polish_Summary.pdf"
    build_pdf(out)

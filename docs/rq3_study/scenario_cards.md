# Scenario cards (researcher copy — contains expected answers, do not show to participants)

All cases are invented. Participants see the story plus the result in one of two formats (the toggle in `/study?facilitator=1`). The baseline score is the mean of the detectors that ran, with the orchestrator thresholds (≥ 0.65 synthetic, ≤ 0.35 authentic, otherwise uncertain). Data lives in `web/src/lib/study.ts`.

| # | Title | Type | What the detectors say | Baseline shows | Expected decision | What the case tests |
|---|-------|------|------------------------|----------------|-------------------|---------------------|
| S1 | Spokesperson briefing | Agreement | All four say synthetic (0.71–0.94) | 0.84 Likely synthetic | Manipulated | Does the report add trust when the score is already clear? |
| S2 | Dashcam footage | Agreement | Three say authentic; voice check cannot run (no audio) | 0.11 Likely authentic | Authentic | Is a "did not run" check understood rather than read as a problem? |
| S3 | Interview with an official | **Conflicting modality** | Video 0.91 and lip-sync 0.84 synthetic; voice 0.12 authentic | 0.56 Uncertain | Manipulated | Real voice under a swapped face: can the report resolve a conflict the score hides? |
| S4 | Executive video call | **Conflicting modality** | Voice 0.92 synthetic; video 0.14 and pulse 0.12 authentic | 0.41 Uncertain | Manipulated | Cloned voice over real video, the mirror of S3 |
| S5 | Compressed protest footage | **Conflicting modality** | Video 0.72 synthetic (flagged heavy compression); other three authentic | 0.29 Likely authentic | Authentic | Does the report stop over-reaction to one unreliable detector? Is the baseline "correct" by luck? |
| S6 | Night-time security clip | **Conflicting modality** | Video, lip-sync, voice synthetic; pulse 0.36 with poor signal quality (0.31) | 0.71 Likely synthetic | Manipulated | Do people see that the lone dissent is low quality, or does it lower their trust needlessly? |
| S7 | Camera clip with a broken record | Integrity | All four authentic (≤ 0.15) but frame hash chain broken at frame 412, no capture signature | 0.11 Likely authentic | Can't decide without further checks | Core RQ3 case: does the report prevent "authentic" when integrity is unknown? The baseline cannot show it. |
| S8 | Very short night clip | Limits | Only the video check ran (0.58, unreliable); other three could not run | 0.58 Uncertain | Can't decide without further checks | Does the report make "not enough evidence" visible and acceptable? |

Counterbalancing: each participant sees 4 cases in each format, with 1 agreement, 2 conflict and 1 limits case per format. The format for a case flips between P01 and P02, P03 and P04, and so on. Case order is a seeded shuffle per participant code.

Decision accuracy (`correct` in the export) is computed against the "Expected decision" column. S5 and S6 are the judgement-heavy ones; if a pilot participant gives a defensible different answer, record it in the pilot findings rather than changing the key silently.

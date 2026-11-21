# RQ3 trust and usability study kit

Study kit for RQ3: *does a full chain-of-evidence report give users better-calibrated trust and a better experience than a single score?*

Status: **kit built; pilot not yet run.** See `pilot_protocol.md` and `pilot_findings.md`.

## Contents
| File | Purpose |
|------|---------|
| `consent_sheet.md` | Information and consent sheet to print (fill in researcher contact and ethics reference first) |
| `instructions.md` | Participant instructions and researcher script |
| `questionnaire.md` | All questions: background, per-case items, final Likert blocks, forced choice |
| `scenario_cards.md` | The 8 cases with expected answers (researcher only) |
| `pilot_protocol.md` | How to run the 3-person pilot |
| `pilot_findings.md` | Template for pilot findings and wording fixes |
| `web/src/app/study/page.tsx` | The study app at `/study` |
| `web/src/lib/study.ts` | Source of truth for scenarios and wording |

## Running a session
```bash
cd web && npm install && npm run dev
```
Open `http://localhost:3000/study?facilitator=1` (add `&pilot=1` for pilots). Enter a participant code such as `P01`. The code decides case order, which cases use which format, and which format block comes first in the final questionnaire. The participant sees no AEGIS navigation on this page.

- **Toggle** (`?facilitator=1`): switches the *same* result between the full evidence report and the single score. It is for demonstration, practice and the pilot. Using it during a real session is logged (`facilitator_toggles`, `condition_at_submit`), so those cases can be excluded.
- **Pilot mode** (`?pilot=1`): adds an "anything unclear?" box on each screen.
- **Export**: on the last screen (with `?facilitator=1`) download JSON and two CSVs. The session is also backed up in the browser's localStorage.

## Design
Within-subjects. Every participant sees all 8 cases, 4 in each format, balanced by case type (see `scenario_cards.md`). Per case: decision, then trust / understanding / confidence on a 7-point scale, with time on task. After the cases: the same 7 statements about each format, then a forced choice between the two.

Suggested analysis (decide before collecting data): paired comparison of trust and understanding per format (Wilcoxon signed-rank, since Likert data is ordinal); decision accuracy by format, split by case type; the forced-choice split with a binomial test; and a descriptive look at S7 (how often "authentic" was chosen per format) because it is the case the single score cannot represent.

## Decisions for you to confirm
1. **The baseline cannot show broken integrity (S7).** It is deliberately just a score and a label. That is a strong comparator for the integrity case, and a reviewer may call it a straw man. Alternative: add an "integrity unknown" label to the baseline and treat S7 as a test of understanding rather than detection. Currently implemented as the pure score.
2. **Sample size.** Not set here. A within-subjects design with a forced-choice test is workable with 12 to 20 participants but has little power; set the target with your supervisor.
3. **Ethics approval and contact details** in the consent sheet are placeholders.
4. **Expected answers for S5 and S6** are my judgement; check them against your own view of the detectors' reliability (`docs/LIMITATIONS.md`).

## Known limitations of the kit
- The evidence view is a study-specific rendering, not the production report page. It reuses `AgreementMatrix` and the shared UI parts but not `DebateLog` or `HashChain`: `HashChain` hard-codes a green "VERIFIED" badge on the file hash and `DebateLog` carries internal labels ("MONTH 2 ADJUDICATION"). Either would mislead participants in S7. The production `HashChain` should probably show real verification state; I did not change it (outside this task).
- Scenario data is hand-written, not produced by the detectors.
- Detector scores are shown to two decimals; participants are told what a score means but not how it is calculated.

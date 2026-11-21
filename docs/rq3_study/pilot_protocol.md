# Pilot protocol (3 participants)

Goal: find confusing wording, broken flow and timing problems before the main study. Not to estimate effects.

## Who
Three people who have not seen the materials, with a spread: for example one with no media-verification experience, one with some, one technical. Do not use team members who built the kit.

## Before
1. Fill in researcher name/contact and ethics reference in `consent_sheet.md`; print three copies.
2. Start the app and open `/study?facilitator=1&pilot=1`.
3. Use codes `PILOT1`, `PILOT2`, `PILOT3`. The numbers in the codes drive counterbalancing: PILOT1 and PILOT2 get opposite formats.

## During (about 40 minutes each)
1. Consent sheet, then the on-screen consent.
2. Ask the participant to **think aloud** and sit beside them. Do not explain or hint. Note every pause, re-read, question about a word, or misreading.
3. They answer the on-screen "was any wording unclear?" boxes as they go. Prompt once if they skip them.
4. After the final questionnaire ask: *What did you think the single score was based on? What did "chain of evidence" mean to you? Which question was hardest to answer? Was anything in the evidence report missing, or too much?*
5. Record total time.

## After
Download the three exports. Fill in `pilot_findings.md`: one row per problem with the screen, what happened, the fix, and whether it was applied. Wording lives in `web/src/lib/study.ts`; update the matching text in `docs/rq3_study/` (a test checks they agree). Re-run one session yourself after fixing.

## Ready-to-run checklist
- [ ] No problem rated Major is left open.
- [ ] Median session time is within the 25 to 30 minutes promised in the consent sheet (change the sheet if not).
- [ ] The export opens correctly in a spreadsheet.
- [ ] Every participant could tell what "I can't decide without further checks" meant.

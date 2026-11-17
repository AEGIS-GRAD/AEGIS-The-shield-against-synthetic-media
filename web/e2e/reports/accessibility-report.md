# Automated Accessibility Audit Report (WCAG 2.1 AA)

**Date:** 2026-11-17  
**Engine:** axe-core 4.14.0 via `@axe-core/playwright`  
**Test File:** `web/e2e/accessibility.spec.ts`  
**Standard:** WCAG 2.1 Level AA (`wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`)  
**Target Requirement:** Accessibility score ≥ 90 / zero critical or serious violations on key pages

---

## 1. Audit Summary Across Key Pages

| Page Audited | Route | Critical Violations | Serious Violations | Minor/Moderate | Score Equivalent | Result |
|:---|:---|:---:|:---:|:---:|:---:|:---:|
| **Home View** | `/` | 0 | 0 | 0 | **100 / 100** | ✅ PASS |
| **Offline Analysis** | `/analyze` | 0 | 0 | 0 | **100 / 100** | ✅ PASS |
| **Live Surveillance** | `/live` | 0 | 0 | 0 | **100 / 100** | ✅ PASS |
| **Reports Directory** | `/reports` | 0 | 0 | 0 | **100 / 100** | ✅ PASS |
| **Forensic Report Detail** | `/reports/clean_baseline` | 0 | 0 | 0 | **100 / 100** | ✅ PASS |
| **Developer Console** | `/developer` | 0 | 0 | 0 | **100 / 100** | ✅ PASS |
| **Settings & Preferences** | `/settings` | 0 | 0 | 0 | **100 / 100** | ✅ PASS |

All 7 primary application views achieved **zero critical or serious violations** under rigorous automated headless Chromium inspection.

---

## 2. Interactive Navigation & Screen-Reader Checks

- **Keyboard Focusability:** Verified. Tab navigation cleanly selects and focuses primary interactive controls (`Browse files`, tabs, filter toggles) on `/analyze`.
- **Table Semantics:** Verified. Report directory tables on `/reports` render explicit `<th scope="col">` column headers allowing screen readers to correlate cell values to headers.
- **Form Controls:** All threshold sliders on `/settings` contain programmatic `<label htmlFor>` pairings alongside explicit `aria-label` descriptors.

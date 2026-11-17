# Performance Budget Report

**Date:** 2026-11-17  
**Environment:** Next.js 15.1.7 (Production Build / Optimized Standalone)  
**Tool:** Playwright Chrome DevTools Protocol & Navigation Timing API  
**Target:** First Contentful Paint (FCP) < 1.8 s, Largest Contentful Paint (LCP) < 2.5 s, DOM Content Loaded (DCL) < 1.0 s

---

## 1. Summary Metrics by Key Page

| Key Page | Route | FCP | LCP | DOM Ready (DCL) | Payload Transfer | Status |
|:---|:---|:---|:---|:---|:---|:---|
| **Home** | `/` | 304 ms | 304 ms | 269 ms | ~6 kB | ✅ PASS |
| **Analyze** | `/analyze` | 220 ms | 220 ms | 180 ms | ~8 kB | ✅ PASS |
| **Live Surveillance** | `/live` | 292 ms | 292 ms | 239 ms | ~8 kB | ✅ PASS |
| **Reports List** | `/reports` | 236 ms | 364 ms | 275 ms | ~5 kB | ✅ PASS |
| **Report Detail** | `/reports/clean_baseline` | 364 ms | 364 ms | 320 ms | ~13 kB | ✅ PASS |
| **Developer Dashboard** | `/developer` | 252 ms | 252 ms | 314 ms | ~7 kB | ✅ PASS |

All 6 evaluated key views pass the performance budget criteria comfortably:
- **Maximum FCP observed:** 364 ms (Budget: 1 800 ms — **79.8% headroom**)
- **Maximum LCP observed:** 364 ms (Budget: 2 500 ms — **85.4% headroom**)
- **Maximum DCL observed:** 320 ms (Budget: 1 000 ms — **68.0% headroom**)

---

## 2. First Load JS Bundle Audit

From `next build` static export trace:

| Route | Page Size | First Load JS | Budget (< 250 kB) |
|:---|:---|:---|:---|
| `/` | 6.21 kB | 125 kB | ✅ PASS |
| `/analyze` | 9.07 kB | 133 kB | ✅ PASS |
| `/analyze/processing` | 4.87 kB | 128 kB | ✅ PASS |
| `/reports` | 7.58 kB | 126 kB | ✅ PASS |
| `/reports/[id]` | 10.9 kB | 140 kB | ✅ PASS |
| `/demo` | 46.6 kB | 152 kB | ✅ PASS |
| `/settings` | 4.25 kB | 124 kB | ✅ PASS |
| `/developer` | 9.26 kB | 226 kB | ⚠️ PASS (Heavy) |
| `/live` | 10.6 kB | 233 kB | ⚠️ PASS (Heavy) |

Shared JS baseline across all routes is **106 kB**. `/live` (233 kB) and `/developer` (226 kB) carry `recharts` and multi-modal SVG canvas components, remaining within the 250 kB SLA.

---

## 3. Recommendations for Future Optimizations

1. **`<img>` to `next/image` migration**:
   - `SurveillanceMonitor.jsx` lines 836 & 1100, `live/page.tsx` lines 313 & 330, and `reports/[id]/page.tsx` line 268 currently use raw `<img>`. Migrating these to Next.js `<Image />` will enable automatic WebP compression and responsive srcset generation.
2. **Chart Lazy-Loading**:
   - Dynamic import with `next/dynamic` (`ssr: false`) for Recharts LineCharts on `/live` will shave ~45 kB off the first-load JS payload.

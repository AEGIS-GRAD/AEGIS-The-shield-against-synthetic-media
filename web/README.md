# AEGIS Web Application — Tech Stack Decision Note

> **Document Type**: Architecture & Tech Stack Decision Record (ADR)  
> **Project**: AEGIS — Agentic, Edge-optimized, explainable deepfake verIfication System  
> **Author**: Mohand Mohsen (AI / UI Track)  
> **Sprint**: Sprint 1 / Week 1 — Task 1: Decide Web App Tech Stack  
> **Status**: **ACCEPTED & LOCKED**  
> **Target Container**: `aegis_web` (Port `3000`) on `aegis_net`

---

## 1. Executive Summary

This document establishes the official frontend architecture and technology stack for the **AEGIS Web Application**. Following evaluation of system requirements, user stories (specifically **UC-07: Chain-of-Evidence Report Sharing** and **UC-02: Live RTSP Stream Monitoring**), and edge-to-cloud operational constraints, the team has selected:

| Layer | Selected Technology | Version / Specification | Rationale Summary |
|---|---|---|---|
| **Core Framework** | **Next.js (App Router)** | `15.x` with **TypeScript 5.x** | SSR/OG metadata for shareable reports, Route Handlers to proxy internal microservices, file-based routing |
| **Package Manager** | **pnpm** | `9.x`+ | Strict dependency isolation, fastest CI install times, no phantom dependencies |
| **Styling & Design System** | **Tailwind CSS + Shadcn UI** | Tailwind `v4` / Radix Primitives | Rapid utility-first styling, dark forensic aesthetic, accessible and copy-paste component ownership |
| **Design Quality & Anti-Slop** | **Impeccable** (`pbakaus/impeccable`) | `.impeccable` Skill + Deterministic Rules | Enforces bespoke forensic design vocabulary, bans generic AI tropes, provides 24 design commands (`/polish`, `/critique`, `/audit`), and CI anti-pattern detection |
| **Typography** | **Inter** (Google Fonts) | Variable font | Clean, legible sans-serif optimized for dense forensic data and telemetry tables |
| **State Management** | **Zustand** | `4.x` / `5.x` | Minimal boilerplate, lightweight client-side state for UI controls and active session filters |
| **Server State / Polling** | **TanStack Query** | `v5` (React Query) | Declarative caching, deduplication, automatic refetching for async detector microservice jobs |
| **Live Media Playback** | **HLS.js** | Latest | Hardware-accelerated HLS playback from MediaMTX (`http://mediamtx:8888`) |
| **Data Visualization** | **Recharts** | `2.x`+ | Composable, responsive charts for detector confidence scores, latency graphs, and debate outcomes |
| **Deployment Target** | **Vercel** + **Docker** | Node.js 20 LTS runtime | Zero-config preview deployments for PRs; containerized in `docker-compose.yml` for local unified dev |

---

## 2. Core Functional Requirements & Constraints

The AEGIS Web Application serves as the primary visual interface for non-technical stakeholders (journalists, legal professionals, enterprise security teams) as well as internal system engineers. It must support three foundational views:

1. **Upload & Ingestion View**:
   - Multi-modal drag-and-drop ingestion (MP4, MKV, WAV, MP3, JPEG, PNG, TXT).
   - Real-time RTSP/RTMP stream URL submission.
   - Immediate schema validation against [`shared/json-api-contracts-schema/`](../shared/json-api-contracts-schema/).

2. **Real-Time Telemetry & Status View**:
   - Per-detector pipeline progress (`video_classifier`, `rPPG`, `AASIST`, `SyncNet`, `DIRE`, `Binoculars`).
   - Hardware telemetry telemetry indicators (latency, RAM, Jetson Orin VRAM allocation).
   - Low-latency live video stream playback powered by the MediaMTX streaming server.

3. **Forensic Chain-of-Evidence Report View (Flagship)**:
   - Multi-agent debate resolution output.
   - Transparent, explainable verdict (Authentic, Synthetic, Inconclusive) with per-detector confidence breakdowns.
   - Shareable, permanent, tamper-evident URLs (`/report/[job_id]`) suitable for external legal review or publication.

---

## 3. Framework Evaluation: Next.js vs. React + Vite

| Evaluation Criterion | React + Vite (SPA) | Next.js 15 (App Router) | AEGIS Decision Driver |
|---|---|---|---|
| **Public Report Sharing (UC-07)** | ❌ Client-rendered only. Shared URLs lack server-generated Open Graph (`og:image`, `og:title`) metadata, making link previews in Slack, X/Twitter, or legal emails blank or generic. | ✅ Built-in SSR and dynamic `generateMetadata()`. Each `/report/[job_id]` renders instant server-side previews with verdict badges and cryptographic hashes. | **CRITICAL**: Forensic reports are meant to be shared with external third parties. Next.js is mandatory for rich link previews and instantaneous document loading. |
| **Backend API Security & Proxying** | ⚠️ Browser directly talks to backend FastAPI orchestrator. Requires public CORS headers and exposes internal API keys to client JavaScript. | ✅ Next.js Route Handlers (`/api/*`) act as a secure backend-for-frontend (BFF) proxy within the internal `aegis_net` Docker network, keeping `INTERNAL_API_KEY` hidden. | **CRITICAL**: Prevents credential leakage and bypasses CORS hurdles during local and production workflows. |
| **Routing Architecture** | ⚠️ Requires third-party library (`react-router-dom`), manual route configuration, and manual code splitting. | ✅ File-system routing with nested layouts, loading states (`loading.tsx`), and error boundaries (`error.tsx`) out of the box. | Enhances code modularity across tracks. |
| **Live HLS Stream Playback** | ✅ Supports HLS.js in client component. | ✅ Supports HLS.js seamlessly in client component (`"use client"`). | Neutral (identical capability). |
| **Local Docker Dev Integration** | ✅ Simple static file server or dev server. | ✅ Node.js 20 container mounted via `docker-compose.yml` (`aegis_web`). | Neutral (both run cleanly on `aegis_net`). |
| **Hosting & Staging Velocity** | ⚠️ Static hosting (Netlify, S3, GitHub Pages). Requires separate serverless functions for dynamic API routing. | ✅ Native Vercel deployment with automatic PR preview environments for Dr. Amr and TAs to review. | High developer velocity. |

**Decision**: **Next.js 15 (App Router) with TypeScript** is adopted as the single official web framework.

---

## 4. UI/UX Design System & Aesthetics

### Dark Cybersecurity Aesthetic
Deepfake verification is a mission-critical forensic domain. The interface must inspire trust, precision, and technical authority:
- **Base Theme**: Deep charcoal/slate dark mode (`#0b0f17`, `#111827`) with glassmorphism overlays (`backdrop-blur-md`, subtle border glows).
- **Status Semantics**:
  - 🟢 **Verified Authentic**: Emerald / Jade (`#10b981`)
  - 🔴 **Synthetic / Deepfake**: Crimson / Rose (`#f43f5e`)
  - 🟡 **Inconclusive / Debate Active**: Amber / Yellow (`#f59e0b`)
  - 🔵 **Processing / Telemetry Active**: Electric Cyan / Indigo (`#06b6d4` / `#6366f1`)
- **Typography**: Inter via `@next/font` for high legibility across dense metric cards and confidence matrices.

### Component Primitives: Shadcn UI + Tailwind CSS v4
- **Tailwind CSS v4**: Ultra-fast Rust-based engine (`@tailwindcss/vite` or `@tailwindcss/postcss`), modern CSS variable theming.
- **Shadcn UI**: Provides unstyled, fully accessible Radix primitives (Dialog, Tabs, Progress, Slider, DropdownMenu, Accordion, Tooltip) directly copied into `src/components/ui/`. No bloated external NPM component dependencies.

### Impeccable Design Quality & Anti-Slop Framework
To ensure the interface feels like an authentic forensic workstation rather than generic AI boilerplate, the team adopts **Impeccable** (`pbakaus/impeccable`) as the official UI/UX design governance skill:

1. **Banning "AI Slop" Anti-Patterns**:
   - 🚫 **No Monotonous Nested Cards**: Avoid endless cards-inside-cards with identical borders.
   - 🚫 **No Generic Purple/Blue Gradients**: Avoid standard SaaS gradient fills; use clean, dark slate backgrounds with functional border glows.
   - 🚫 **No Inaccessible Contrast**: Ensure all metric labels, status indicators, and claim summaries exceed WCAG AA 4.5:1 contrast standards.
   - 🚫 **No Generic Centered Heroes**: The dashboard is a dense, high-utility forensic workspace, not a marketing landing page.

2. **Living Design Contracts**:
   - **`web/PRODUCT.md`**: Codifies the target audience (forensic examiners, journalists, court officials), user mental models, and critical workflows for UC-07 (shareable reports) and UC-02 (real-time stream ingest).
   - **`web/DESIGN.md`**: Captures the concrete design tokens (palette, spacing scale, font weights, tabular number formats for hashes/timestamps, micro-animation easing curves).

3. **24 AI Pair-Programming Commands**:
   During frontend development in Antigravity/Cursor/Claude, developers leverage Impeccable's command suite:
   - `/critique`: Evaluate layout hierarchy, cognitive load, and forensic clarity before writing code.
   - `/typeset`: Optimize font weights, tabular numbers, and readability for telemetry grids.
   - `/audit`: Verify accessibility (WCAG AA), responsive breakpoints, and theme contrast.
   - `/polish`: Perform pixel-level alignment, spacing rhythm, and border subtlety checks.
   - `/distill`: Eliminate visual noise and unnecessary chrome from complex detector matrices.
   - `/animate`: Apply subtle, purposeful micro-interactions for streaming status changes.
   - `/harden`: Make components resilient to edge cases (overflows, missing metadata, zero-claim runs).

4. **Deterministic CI/CD Guardrails**:
   - Run `npx impeccable detect web/` in GitHub Actions to catch UI anti-patterns and contrast violations automatically on every pull request without requiring LLM calls.

---

## 5. Media & Real-Time Data Handling

### Live Video Pipeline (MediaMTX)
AEGIS ingests live RTSP camera feeds and streams them through MediaMTX:
- **RTSP Ingest**: Port `8554`
- **RTMP Ingest**: Port `1935`
- **HLS Egress**: Port `8888`
- **In-Browser Player**: A custom React component wrapping `hls.js` with auto-reconnect, buffer monitoring, and frame-accurate playback time synchronization with the inference engine's detector logs.

### Job Polling & Telemetry
Inference runs asynchronously across 6 microservices:
- **TanStack Query (`useQuery`)**: Polls `/api/jobs/[id]/status` at adaptive intervals (e.g. 1000ms while running, backoff on completion).
- **Zustand Store**: Keeps track of active stream URL, user-selected detector filters, and debate transcript view preferences.

---

## 6. Docker & Deployment Specification

### Local Development (`docker-compose.yml`)
The web application runs as service `web` (container `aegis_web`):
```yaml
web:
  image: node:20-alpine
  container_name: aegis_web
  ports:
    - "3000:3000"
  volumes:
    - ./web:/app
  environment:
    - NODE_ENV=development
    - ORCHESTRATOR_URL=http://orchestrator:8000
    - INTERNAL_API_KEY=${INTERNAL_API_KEY}
  networks:
    - aegis_net
  depends_on:
    - orchestrator
```

### Staging / Production
- Configured for zero-configuration continuous deployment via **Vercel**.
- Edge middleware handles authentication and redirects.
- Environment variables in Vercel synchronize with production orchestrator gateway endpoints.

---

## 7. Handoff to Task 3 (Frontend Repository Skeleton)

With this decision approved and recorded, the assigned team member for **UI Track — Task 3** will initialize the frontend skeleton and design harness using:
```bash
# 1. Initialize Next.js 15 App Router skeleton (Task 3 scope)
pnpm create next-app web --typescript --tailwind --eslint --app --src-dir --use-pnpm

# 2. Install & Link Impeccable Design Skill Harness
npx impeccable install
# Or initialize project context:
# npx impeccable init
```

This completes **UI/UX Track — Task 1: Decide Web App Tech Stack**.

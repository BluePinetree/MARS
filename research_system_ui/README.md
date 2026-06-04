# MARS — React Frontend

**Unified React UI for all three MARS pipeline backends (CrewAI, LangGraph, AutoGen).**

Consumes the SSE event stream from the backend and renders agent conversations, phase progress, experiment output, and all 5 human-in-the-loop interaction gates in real time.

---

## Features

| Feature | Description |
|---------|-------------|
| **Dashboard** | Lists all research sessions as cards with status, phase, and elapsed time |
| **SessionView** | 3-column layout: sidebar (sessions + filters) · log view · detail panel |
| **Event renderers** | Per-event-type UI components: agent bubbles, code highlighter, terminal pane, result cards |
| **ApprovalDialog** | Phase 1 plan approval gate (approve / request revision / reject) |
| **GuidanceDrawer** | Phase 2/3 code repair gate — hint input + skip option |
| **PreflightFlow** | Phase 0 Q&A gate — full-screen overlay with 60-second countdown |
| **TerminalPane** | Live `exec_stdout` streaming with auto-scroll and scroll lock |
| **TokenBudgetBar** | Token usage progress bar (Phase 2) |
| **RunStatusRibbon** | Active run indicator with elapsed time and current phase |
| **ContextInjectionInput** | Phase 3 context injection — bottom-fixed input, Ctrl+Enter to send |
| **ProposalSheet** | Phase 4 extension proposals — bottom sheet with follow-up experiment suggestions |
| **Log filtering** | Filter by agent name, event type, or keyword search |
| **SSE reconnection** | EventSource reconnects automatically; `mergeLogEvents` deduplicates replayed events |

---

## Tech Stack

- **React 19** + **TypeScript** + **Vite 7**
- **TailwindCSS 4** + **shadcn/ui** (Radix primitives)
- **Recharts** — comparison charts
- **react-syntax-highlighter** — code blocks
- **Framer Motion** — animations
- **Express** — production SSR server (`server/index.ts`)
- **pnpm** — package manager

---

## Project Structure

```
research_system_ui/
├── client/
│   └── src/
│       ├── components/          # All UI components
│       │   ├── LogEvents.tsx    # Event-type registry (12+ renderers)
│       │   ├── LogView.tsx      # Central log view + Phase stepper
│       │   ├── Sidebar.tsx      # Session list + agent/type filters
│       │   ├── DetailPanel.tsx  # Right-side detail panel
│       │   ├── ApprovalDialog.tsx
│       │   ├── GuidanceDrawer.tsx
│       │   ├── PreflightFlow.tsx
│       │   ├── TerminalPane.tsx
│       │   ├── TokenBudgetBar.tsx
│       │   ├── RunStatusRibbon.tsx
│       │   ├── ContextInjectionInput.tsx
│       │   └── ProposalSheet.tsx
│       ├── pages/
│       │   ├── Dashboard.tsx
│       │   ├── SessionView.tsx
│       │   └── ComparisonView.tsx
│       └── lib/
│           ├── api.ts           # API client + SSE hook
│           ├── types.ts         # TypeScript type definitions
│           └── constants.ts     # Agent colors, event type mapping
├── server/
│   └── index.ts                 # Production Express server
├── shared/                      # Shared types (frontend ↔ server)
├── package.json
├── vite.config.ts
├── .env.example                 # VITE_API_BASE_URL template
└── Dockerfile
```

---

## Quick Start

### Prerequisites

- Node.js ≥ 18
- pnpm ≥ 8 (`npm install -g pnpm`)
- MARS backend running at `http://localhost:8000`

### Development

```bash
cd research_system_ui
pnpm install
pnpm dev
```

Open [http://localhost:5173](http://localhost:5173).

### Environment variable

Create `.env.local` to point at a non-default backend:

```env
VITE_API_BASE_URL=http://localhost:8000
```

### Production build

```bash
pnpm build
node dist/index.js
```

---

## End-to-End Validation

1. Start backend: `cd crewai_prototype && python -m uvicorn entrypoints.api:app --port 8000`
2. Start frontend: `cd research_system_ui && pnpm dev`
3. Open [http://localhost:5173](http://localhost:5173)
4. Click **New Research** → fill in topic → submit
5. Confirm auto-navigation to SessionView
6. Confirm live log events append in real time
7. Confirm `ApprovalDialog` pops up for Phase 1
8. Approve → confirm Phase 2 coding events appear
9. Confirm `TerminalPane` activates during Phase 3
10. Confirm `SYSTEM_END` updates session status to "completed"

---

## Design Theme

**Mission Control** — dark mode inspired by space mission operations.

| Token | Color | Usage |
|-------|-------|-------|
| Background | `#0A0E1A` Deep Navy | Page background |
| Accent | `#00D4FF` Cyan | Active state, live data |
| Warning | `#FFB800` Amber | User input required, paused |
| Success | `#10B981` Emerald | Completed, passed |
| Failure | `#EF4444` Coral | Error, failed |

Typography: **JetBrains Mono** (headings, code) + **IBM Plex Sans** (body)

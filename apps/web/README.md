# @repolearn/web

Next.js 15 (App Router) + React 19 + TypeScript + Tailwind CSS v4 frontend for RepoLearn.

## The one architectural rule

The browser **only** talks to same-origin `/api/*`. Every request is forwarded by a
Route Handler under `src/app/api/**` to `REPOLEARN_API_BASE` (default
`http://127.0.0.1:8000`), server-side, with `X-Internal-Token`. Putting an absolute
backend URL in client code would drop cookies, `SameSite` protection, SSE buffering
control and audio `Range` support all at once (spec §2.2 constraint 6).

Flow: `client.ts` → `/api/<x>` → `src/lib/api/bff.ts` → `${API_BASE}/v1/<x>`.

## Environment (server-only)

| Variable | Meaning |
| --- | --- |
| `REPOLEARN_API_BASE` | FastAPI base URL, default `http://127.0.0.1:8000` |
| `REPOLEARN_INTERNAL_TOKEN` | Shared token sent as `X-Internal-Token` |
| `REPOLEARN_WEB_MOCK` | `1` = offline/E2E hints in the BFF (never masks stream shape) |

`src/lib/env.ts` asserts it is only imported on the server. Client code imports the
header/cookie names from `src/lib/api/constants.ts` instead.

## Layout

```
src/
├─ app/                     pages + BFF route handlers
│  ├─ page.tsx              P01 home (hero import, features, hot courses, recents)
│  ├─ setup/                5-step first-run wizard
│  ├─ repo/[owner]/[name]/  P02 preparation (SSE, blueprint, quality)
│  ├─ course/[courseId]/    workbench shell + overview / walkthrough / deep-dive / recap
│  ├─ book/[bookId]/        P09 book reader, P10 PDF
│  ├─ settings/             profiles, roles, revisions, cost, doctor
│  └─ api/**/route.ts       BFF: json passthrough, SSE proxy, binary Range proxy
├─ components/              ui, shell, ide, player, learning, prepare, setup, book, recap, settings
├─ lib/
│  ├─ api/                  client.ts (typed errors), errors.ts (19 codes), bff.ts, hooks.ts, types.ts
│  ├─ sse/                  parse.ts (frame decoder), useEventStream.ts (fetch + ReadableStream)
│  ├─ player/               timeline.ts (pure math, unit tested), subtitles.ts
│  ├─ ide/                  decorations.ts, font-size.ts
│  ├─ jobs/                 prepare-state.ts (SSE → four-section progress reducer)
│  ├─ markdown/             sanitize.ts (rehype-sanitize allowlist)
│  └─ env.ts                server-only config
├─ stores/                  zustand: player, ide, setupWizard (sessionStorage draft)
├─ styles/tokens.css        the 24 design tokens (§7.1)
└─ middleware.ts            pure-cookie first-run guard (no network)
```

## Notable behaviour

- **Player**: one time source (`audio.currentTime`, or `performance.now()` × speed for
  audio-less lessons at 4.2 chars/s). The `<audio>` element lives in the course
  layout, so switching tabs never restarts the lesson. Progress is PUT every 2s and
  `sendBeacon`-ed on hide/unload.
- **SSE**: `fetch` + `ReadableStream` (never `EventSource`), exponential reconnect
  1/2/4/8/16s, resume via `Last-Event-ID`, unknown event types logged and skipped,
  `job.snapshot` re-syncs through `GET /api/jobs/{id}`.
- **IDE**: Monaco readonly with decoration-driven highlighting; if the Monaco AMD
  loader cannot be reached the pane falls back to a plain decorated code view so the
  deep-dive page never goes blank.
- **Markdown**: always `react-markdown` + `rehype-sanitize` allowlist; no
  `dangerouslySetInnerHTML` anywhere (locked by `src/components/ui/markdown.test.tsx`).
- **PDF**: when the backend reports `engine=browser-print` the page offers a print
  view instead of a fake download.

## Scripts

```bash
pnpm --filter @repolearn/web dev        # http://localhost:3000
pnpm --filter @repolearn/web build
pnpm --filter @repolearn/web typecheck
pnpm --filter @repolearn/web test       # vitest (timeline, subtitles, decorations,
                                        # prepare reducer, sanitisation, setup auto-assign)
```

## Assumptions

- Course chapters map to layers by index: chapter 1 → overview, 2 → walkthrough,
  3 → deep-dive, 4 → recap. `?lesson=<key>` overrides the choice.
- `Mermaid` is not rendered as a diagram (no renderer dependency is allowed); the
  architecture canvas renders `board.nodes` as clickable cards and exposes the
  mermaid source for copying.
- `feedback on recent-learning`: the course list has no per-course progress field, so
  the home page sorts by `updated_at` and the workbench derives completed lessons from
  `GET /api/courses/{id}/recap`.

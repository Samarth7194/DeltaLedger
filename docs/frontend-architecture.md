# Frontend Architecture

DeltaLedger's frontend is a Next.js analyst workspace for disclosure consistency review. It is not a chatbot, trading terminal, or demo-data dashboard. The first screen is the working dashboard for companies, filing comparisons, workflow status, review gates, evidence, and structured reports.

## Stack

- Next.js 16.3 App Router with TypeScript.
- Tailwind CSS for a restrained financial-workspace UI.
- TanStack Query for server state, caching, polling, and mutation invalidation.
- Lucide icons for recognizable action affordances.
- Vitest and Testing Library for deterministic component and flow tests.
- Playwright for mocked HTTP-boundary browser acceptance tests.

`NEXT_PUBLIC_API_BASE_URL` configures the backend API base URL. It defaults to `http://localhost:8000/api/v1`.

## Structure

- `src/app`: route pages for dashboard, companies, analyses, review, reports, and settings.
- `src/components/layout`: persistent navigation and workspace header.
- `src/components/ui`: accessible primitives for buttons, badges, panels, tabs, loading, empty, and error states.
- `src/components/analyses`, `disclosures`, `financial`, `contradictions`, `evidence`, `filings`, `review`, and `reports`: domain components.
- `src/lib/api`: typed backend client and endpoint functions.
- `src/lib/queries`: query keys, polling behavior, and mutation invalidation.
- `src/lib/status.ts`: backend-to-frontend status labels and polling cadence.
- `src/lib/formatters.ts`: dates, confidence, currency, percentages, percentage points, and basis points.

## Routes

- `/`: recent analyses, review gates, completed runs, recent companies, warning states, and summary counts.
- `/companies`: company list with ticker, CIK, filing count, latest period, and ingestion state.
- `/companies/[companyId]`: company metadata, filings, recent analyses, and a New Analysis action.
- `/analyses/new`: validates and submits a current filing plus older comparison filing pair.
- `/analyses`: workflow runs with status and progress filters.
- `/analyses/[analysisRunId]`: Overview, Disclosure Changes, Financial Verification, Potential Inconsistencies, Evidence, Review, and Report tabs.
- `/review`: workflow runs awaiting human review.
- `/reports`: completed analyses with report access.
- `/settings`: environment configuration without secrets.

## API And Cache

The API client unwraps the backend response envelope, parses FastAPI validation errors, and raises safe `ApiError` instances. Raw fetch calls are kept in `src/lib/api/endpoints.ts`.

TanStack Query keys are centralized. Analysis detail polling uses backend status:

- active statuses poll every 5 seconds
- `awaiting_human_review` slows to 30 seconds
- completed, failed, and cancelled states stop polling

Mutations invalidate only related analysis, review, report, comparison, or finding queries.

## Evidence UX

Filing text, model summaries, and evidence fields are rendered as untrusted text. The frontend does not use unsafe HTML rendering. Evidence is shown through side-by-side comparison panels, XBRL fact candidate tables, structured JSON blocks, and an evidence drawer for potential inconsistencies.

## Review UX

Workflow-level review supports the Phase 6 statuses: `approved`, `rejected`, `partially_approved`, `needs_changes`, and `uncertain`. Submission and resume buttons disable while mutations are pending to prevent duplicate clicks. Finding-level review controls are present where backend review endpoints support the object type.

## Responsive Behavior

The primary layout is desktop-first and data-dense. Tables scroll horizontally on narrow screens. Side-by-side disclosure comparisons stack on small screens so previous and current text remain readable.

## Testing

Frontend tests use schema-shaped fixtures and mocked component behavior. They cover filing-pair validation, workflow status mappings, financial formatting, disclosure comparisons, financial verification detail, XBRL evidence rows, potential inconsistency wording, review/resume state, and structured report rendering.

Playwright E2E tests cover the browser path from Companies to a completed report
using mocked FastAPI responses at the network boundary. The E2E suite fails on
unexpected console errors, page errors, and backend-envelope API error
responses.

## Production Configuration

The frontend reads the API base URL from `NEXT_PUBLIC_API_BASE_URL`. Hosted
builds must set it to the deployed FastAPI `/api/v1` origin instead of
localhost.

The supported frontend runtime is Node `20.20.x`; CI uses Node `20.20.2`.

`next.config.mjs` uses standalone output and sets moderate security headers:
content type sniffing protection, referrer policy, frame denial, and a CSP that
permits the Next.js runtime while avoiding broad external defaults.

The App Router includes production error, loading, and not-found states so
unexpected API or route failures fail visibly without exposing backend traces.

# Demo Script

This walkthrough uses deterministic demo data and avoids live SEC or model
provider instability.

## Setup

```bash
cd backend
python -m app.cli.seed_demo_data --manifest-only
python -m app.cli.seed_demo_data --offline
python -m uvicorn app.main:app --reload --port 8000
```

In another terminal:

```bash
cd frontend
npm run dev
```

## 5-10 Minute Flow

1. Open the dashboard and explain that DeltaLedger is an analyst workspace, not
   a filing chatbot.
2. Open the demo company, `DLTA`.
3. Show the two comparable 10-Q filings.
4. Open the prepared analysis run.
5. Show workflow progress and explain LangGraph checkpoint/resume.
6. Open the disclosure comparison and show the liquidity language weakening.
7. Open financial verification and show the revenue claim.
8. Show the XBRL-backed calculation: reported 12% growth versus calculated 4%.
9. Open the potential inconsistency and inspect evidence links.
10. Show the human-review decision.
11. Open the final report and point to the evidence manifest.
12. Run or show the offline evaluation report:

```bash
cd backend
python -m app.cli.evaluate --suite all --offline --output-dir evaluation/reports
```

## Talking Points

- The system separates retrieval, deterministic financial verification,
  potential inconsistency generation, human review, and report generation.
- XBRL arithmetic is deterministic; model outputs are never authoritative for
  calculations.
- Findings are potential inconsistencies requiring analyst review.
- Evaluation reports distinguish measured metrics from `not_evaluated` paths.

## Screenshot Guidance

Capture real screenshots only from the running app:

- dashboard
- company filing list
- analysis progress
- disclosure comparison
- financial verification
- potential inconsistency details
- evidence viewer
- review screen
- final report
- evaluation report artifact

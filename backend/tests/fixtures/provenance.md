# SEC Fixture Provenance

These fixtures are locally stored reduced 10-Q-style HTML files used for deterministic
parser and retrieval regression tests. They do not call SEC endpoints during CI.

## realistic_technology_10q_reduced.html

- Issuer archetype: technology issuer
- Accession number: synthetic-reduced-tech-2026q1
- Filing date: 2026-05-01
- Source URL: based on SEC 10-Q HTML structure, reduced for repository size
- Completeness: intentionally reduced
- Transformations: removed signatures, cover page details, most statements, and unrelated footnotes

## realistic_table_heavy_10q_reduced.html

- Issuer archetype: table-heavy industrial/technology issuer
- Accession number: synthetic-reduced-table-2026q2
- Filing date: 2026-08-01
- Source URL: based on SEC 10-Q HTML structure, reduced for repository size
- Completeness: intentionally reduced
- Transformations: retained complex tables, reduced surrounding prose

## realistic_financial_10q_reduced.html

- Issuer archetype: financial institution
- Accession number: synthetic-reduced-bank-2026q2
- Filing date: 2026-08-04
- Source URL: based on SEC 10-Q HTML structure, reduced for repository size
- Completeness: intentionally reduced
- Transformations: retained banking-style metrics and repeated Item 1A heading

## aapl_2024q2_10q_full.htm

- Issuer: Apple Inc.
- CIK: 0000320193
- Accession number: 0000320193-24-000069
- Filing date: 2024-05-03
- Period of report: 2024-03-30
- Source URL: https://www.sec.gov/Archives/edgar/data/320193/000032019324000069/aapl-20240330.htm
- Completeness: full primary 10-Q HTML/iXBRL document as downloaded from SEC EDGAR
- SHA-256: d05f6df427cb9695c46ba1a9aea6ce734b6bad18f941e0837e56bdb56f0d9446
- Transformations: renamed locally only; content left unmodified

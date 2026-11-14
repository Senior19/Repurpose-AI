# Reproducible research walkthrough

This is a **run protocol**, not a claim that a particular drug treats a disease. Results are retrieved live from external databases and can change over time.

## Question

Investigate whether a selected compound has a plausible, evidence-supported relationship to a selected disease.

## Run the investigation

1. Start RepurposeAI using the root README instructions.
2. Open the application and choose **Research Room** or **Evidence & Hypothesis Lab**.
3. Enter the disease name and a specific, testable hypothesis.
4. Run the investigation and wait for the agents to finish.
5. Open each candidate and inspect every evidence item.
6. Follow the PubMed, ClinicalTrials.gov, ChEMBL, or openFDA source links.
7. Record missing evidence and contradictory findings rather than treating missing records as negative evidence.

## Record the run

| Field | Value |
|---|---|
| Research run ID | |
| Date/time (UTC) | |
| Disease / condition | |
| Candidate compound | |
| User hypothesis | |
| Target / mechanism | |
| Supporting records | |
| Contradictory records | |
| Clinical trial records | |
| Safety label records | |
| Main knowledge gaps | |
| Reviewer notes | |

## Evidence interpretation

- **Mechanistic database record:** a curated association or mechanism entry; it is not proof of clinical benefit.
- **Publication metadata:** a title, abstract metadata, or publication identifier; title-level triage is not a substitute for reading the paper.
- **Clinical trial registration:** evidence that a study is registered, not that it succeeded.
- **Drug label:** regulatory labeling information for the product/label retrieved; it is not a complete safety assessment for a new use.
- **No record returned:** means the current query did not retrieve a record. It does not prove that no evidence exists.

## What makes a useful case study?

A strong case study includes the exact query, run ID, retrieval date, source identifiers (PMID, DOI, NCT ID, ChEMBL ID), the original source links, contradictory evidence, and limitations. Do not publish an AI-generated claim unless you can trace it to the underlying record and explain the inference.

> RepurposeAI is an exploratory research prototype. It does not provide medical advice, validate a treatment, or replace scientific and clinical review.

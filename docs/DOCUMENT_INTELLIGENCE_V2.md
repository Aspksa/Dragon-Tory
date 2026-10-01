# Document Intelligence v2

Version **00.00.33** replaces the old head-biased document analysis path with
chunk-first structural analysis.

## Whole-document analysis

Dragon Tory extracts document chunks first and analyzes facts across the complete
chunk set. The old behavior of deriving entities only from the first 250000
characters is no longer used.

A representative sample is still built for human-readable summaries and external
AI requests, but the sample is drawn across the document rather than only from
the beginning.

## Structural provenance

Extracted evidence can carry:

- page;
- table or worksheet;
- cell/range;
- chunk number;
- evidence hash;
- excerpt;
- extraction method;
- confidence.

DOCX tables and XLSX worksheets preserve structural locators when possible.
PDF/OCR evidence preserves page numbers.

## Local checks

Document Intelligence v2 performs deterministic local checks before optional
external AI use:

- candidate document totals;
- VAT mentions and simple included-VAT arithmetic where enough data exists;
- key requisites for contracts and invoice-offers;
- deadlines and dates;
- conflicting total candidates;
- indirect prompt-injection signals embedded in document text.

Warnings are evidence for human review. They are not legal or accounting
conclusions.

## Prompt-injection boundary

Text inside a document is always treated as untrusted document data. A phrase
such as "ignore previous instructions" is recorded as a warning and is never
allowed to replace Dragon Tory system policy.

## Version comparison

Local version diff now contains both legacy date/amount differences and
structured facts added or removed, including their source coordinates. Optional
DeepSeek semantic comparison uses representative content sampled across each
version.

## Memory integration

When a permitted document is studied into project memory, the durable summary
still passes through Memory Intake and Guardian. The resulting memory receives
precise document evidence records containing document id, page/table/cell/chunk
coordinates and evidence hashes.

Original document bytes are not modified by analysis.

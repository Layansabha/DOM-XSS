# Model and research compatibility

[README](../README.md) · [Use the pipeline](USAGE.md) · [How it works](PIPELINE.md)

## Source work

This project is derived from Carnegie Mellon University's
[DOM XSS Web Vulnerability Dataset](https://kilthub.cmu.edu/articles/dataset/DOM_XSS_Web_Vulnerability_Dataset/13870256)
and the WWW 2021 paper
[Towards a Lightweight, Hybrid Approach for Detecting DOM XSS Vulnerabilities with Machine Learning](https://www.contrib.andrew.cmu.edu/~liminjia/research/papers/www2021-dom-xss-dnn.pdf).
The authors published their data/model parsing tools in
[`pwwl/www-dom-xss-tools`](https://github.com/pwwl/www-dom-xss-tools).

The deployed model is Layan Sabha's LightGBM derivative from
[`Layansabha/Dom-xss-ML`](https://github.com/Layansabha/Dom-xss-ML), not the
paper's TensorFlow DNN. No researcher-trained weights are used by the runtime.

The runtime bundle is committed under [`artifacts/`](../artifacts/) so a
container build does not depend on an external download. Its manifest records
the exact source commit, Git blob identifiers, and SHA-256 digests. Both CI and
the Docker build reject a missing or modified model, vocabulary, or metadata
file.

## Compatibility audit

| Research contract | This pipeline | Status |
|---|---|---|
| Analyze JavaScript at function level | Tree-sitter segments declarations, expressions, arrows, generators, and methods; inline handlers are treated as functions | Aligned in intent |
| Represent each function as AST-token term frequencies | Counts identifiers, properties, methods, literals, calls, assignments, and operators, then adds deterministic security-interaction terms | Aligned representation family with an extension |
| Collect browser-executed source and parsed V8 representation | Collects original/rendered scripts plus source reported by Chromium `Debugger.scriptParsed` | Closer runtime coverage, not identical |
| Modified Chromium/V8 with taint tracking | Standard modern Chromium plus optional OWASP ZAP | Not reproduced |
| Paper feature hashing into `2^18` buckets | Explicit train-only 4,096-feature vocabulary used by the LightGBM derivative | Deliberate model difference |
| Paper TensorFlow DNN with embedding | Native LightGBM booster | Deliberate model difference |
| Split by complete source script | Deterministic 80/10/10 split by `dbg` script identifier | Aligned |
| Extremely imbalanced web-scale data | Class-weighted LightGBM on 87,210 parsed CMU-derived rows; exact training bags are capped instead of globally deduplicated | Not equivalent scale/prevalence |
| Proof-of-concept confirmation labels | Uses the `p`/`n` labels in the CMU-derived workbooks; runtime confirmation uses ZAP | Partial |

## What was verified in code

- The runtime loads the exact model and vocabulary from the same pinned
  `Dom-xss-ML` commit.
- The committed runtime bundle is checked against
  `artifacts/artifact-manifest.json` before it can be packaged.
- Vocabulary indexes must be contiguous and unique.
- LightGBM's feature count must equal vocabulary size before the application
  becomes ready.
- Runtime token normalization, source/sink interaction terms, and vectorization
  use the same feature contract as training.
- Vectors are built by vocabulary index, not JSON insertion order.
- Each function is scored independently and the page exposes the maximum
  function score.
- Zero-coverage units are rejected rather than assigned a misleading baseline
  score.
- Original, rendered, resource, and V8-parsed runtime scripts are
  deduplicated before AST extraction.

## What cannot honestly be claimed

The current extractor cannot be byte-for-byte identical to the dataset
generator. The study used a modified Chromium 57/V8 implementation that
stored its internal parsed AST and taint traces. This project uses current
Chromium for execution coverage and Tree-sitter for a portable AST-token
approximation. Reproducing the original extractor exactly would require the
research browser/instrumentation, not a normal Python library.

The current metrics measure the LightGBM derivative on cleaned, unseen
function feature bags. They do not establish page-level accuracy on the
public web and must not be presented as the paper's results.

## Current strict evaluation

The model source files contained 87,210 parseable rows: 37,258 positive and
49,952 negative. Another 3,290 rows were rejected because the feature
dictionary reached Excel's 32,767-character cell limit and could not be treated
as complete. Split assignment is deterministic by the `dbg` source-script
identifier, so a source script cannot cross train, validation, and test.

Vocabulary selection uses training data only. Exact training feature bags are
capped at 20 copies to retain repeated positive evidence without allowing the
largest duplicate groups to dominate. Validation and test bags remain unique
and are excluded when already seen in an earlier split.

The following table evaluates the **exported 460-tree artifact** at the runtime
threshold on the strict test set. This distinction matters because the exported
artifact is refit on train plus validation after model selection.

| Decision at `0.50` | Rows | Positive | TP | FP | TN | FN | Precision | Recall | F1 | PR-AUC | ROC-AUC |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| LightGBM v2 only | 3,215 | 56 | 47 | 8 | 3,151 | 9 | 0.8545 | 0.8393 | 0.8468 | 0.9161 | 0.9967 |
| Model OR source/sink signal | 3,215 | 56 | 49 | 19 | 3,140 | 7 | 0.7206 | 0.8750 | 0.7903 | — | — |

The hybrid row is reported separately because it is not the model's performance:
it is the application's runtime decision policy. Its extra static signal
improves recall on this test while reducing precision. A syntactic source/sink
pair does not prove attacker-controlled data reaches the sink.

## Page-level regression report

The repository also ships a deterministic, hand-labeled 12-case page-level
corpus. It passes complete rendered-DOM and JavaScript inputs through the
runtime extractor, scores every function, and applies the same maximum-score
page decision used by the application.

The bundled runtime decision was checked at `0.50`:

| Cases | TP | FP | TN | FN | Precision | Recall | F1 | Accuracy |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 12 | 6 | 1 | 5 | 0 | 0.8571 | 1.0000 | 0.9231 | 0.9167 |

The false positive is the synthetic DOMPurify example. That limitation is
intentional and visible: static token co-occurrence cannot prove the imported
sanitizer is genuine, current, correctly configured, and applied to the value
that reaches the sink. The case therefore remains in the corpus instead of
being removed to improve the score.

Run the report with `make benchmark`. The
[benchmark contract](../benchmarks/README.md) explains why this small,
synthetic, balanced corpus is a regression suite—not an external estimate of
real-world accuracy.

## Required validation before a commercial accuracy claim

1. Parse the raw CMU `.xz` release directly to remove the workbook cell limit
   and reproduce the full published distribution.
2. Build a labeled runtime corpus from modern Chromium pages.
3. Compare Tree-sitter vectors with dataset feature bags on matching source
   functions and publish coverage/agreement statistics.
4. Evaluate complete pages and domains at realistic vulnerability prevalence.
5. Report confidence intervals, false positives, false negatives, and ZAP
   confirmation separately.

Until those steps are complete, the correct description is **ML-assisted
DOM-XSS triage with optional dynamic verification**, not a guaranteed
standalone vulnerability detector.

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
paper's TensorFlow DNN.

## Compatibility audit

| Research contract | This pipeline | Status |
|---|---|---|
| Analyze JavaScript at function level | Tree-sitter segments declarations, expressions, arrows, generators, and methods; inline handlers are treated as functions | Aligned in intent |
| Represent each function as AST-token term frequencies | Counts identifiers, properties, methods, literals, calls, assignments, and operators | Aligned representation family |
| Collect browser-executed source and parsed V8 representation | Collects original/rendered scripts plus source reported by Chromium `Debugger.scriptParsed` | Closer runtime coverage, not identical |
| Modified Chromium/V8 with taint tracking | Standard modern Chromium plus optional OWASP ZAP | Not reproduced |
| Paper feature hashing into `2^18` buckets | Explicit train-only top-500 vocabulary used by the LightGBM derivative | Deliberate model difference |
| Paper TensorFlow DNN with embedding | Native LightGBM booster | Deliberate model difference |
| Split by complete source script | Deterministic 80/10/10 split by `dbg` script identifier | Aligned |
| Extremely imbalanced web-scale data | Balanced LightGBM training on a cleaned sampled derivative | Not equivalent scale/prevalence |
| Proof-of-concept confirmation labels | Uses labels available in the sampled CMU-derived files; runtime confirmation uses ZAP | Partial |

## What was verified in code

- The runtime loads the exact model and vocabulary from the same pinned
  `Dom-xss-ML` commit.
- Vocabulary indexes must be contiguous and unique.
- LightGBM's feature count must equal vocabulary size before the application
  becomes ready.
- Runtime token normalization and vectorization use the same lowercase
  token/count contract as grouped training.
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

| Threshold | Precision | Recall | F1 | PR-AUC | ROC-AUC |
|---|---:|---:|---:|---:|---:|
| Validation-selected `0.96085` | 0.9545 | 0.7636 | 0.8485 | 0.9066 | 0.9948 |
| Runtime pre-filter `0.50` | 0.8431 | 0.7818 | 0.8113 | 0.9066 | 0.9948 |

The strict test contains 3,169 unique feature bags unseen by training or
validation, including 55 positives. The runtime keeps `0.50` as the
recall-oriented triage threshold before optional dynamic analysis.

An additional negative-only benchmark used 146,772 unique feature bags from
four separate CMU confirmed-data shards after excluding baseline scripts and
features. At `0.96085`, the model produced 493 false positives (0.3359% FPR,
99.6641% specificity). At `0.50`, it produced 1,441 false positives (0.9818%
FPR, 99.0182% specificity). Vocabulary coverage was 95.6573%.

This strengthens the evidence for specificity on additional in-distribution
CMU negatives, but it does not measure recall because all 874 positive rows in
those shards belonged to scripts already represented in the baseline.

## Page-level regression report

The repository also ships a deterministic, hand-labeled 12-case page-level
corpus. It passes complete rendered-DOM and JavaScript inputs through the
runtime extractor, scores every function, and applies the same maximum-score
page decision used by the application.

The same frozen model was checked at both operating thresholds:

| Threshold | Cases | TP | FP | TN | FN | Precision | Recall | F1 | Accuracy |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Runtime `0.50` | 12 | 1 | 1 | 5 | 5 | 0.5000 | 0.1667 | 0.2500 | 0.5000 |
| CMU-selected `0.96085` | 12 | 0 | 0 | 6 | 6 | 0.0000 | 0.0000 | 0.0000 | 0.5000 |

These low results are useful evidence, not a release gate to tune around. At
`0.50`, the model recognizes the corpus's direct `document.write` case but
misses several obvious sink patterns, while the DOMPurify example is a false
positive. Raising the threshold removes that false positive but also the only
true positive, so the runtime keeps `0.50` for triage before optional ZAP
verification. This identifies feature-contract generalization—not threshold
tuning—as the next model-development problem.

Run the report with `make benchmark`. The
[benchmark contract](../benchmarks/README.md) explains why this small,
synthetic, balanced corpus is a regression suite—not an external estimate of
real-world accuracy.

## Required validation before a commercial accuracy claim

1. Obtain the raw CMU `.xz` release instead of Excel-derived samples.
2. Retrain with the same script-level isolation and train-only vocabulary.
3. Build a labeled runtime corpus from modern Chromium pages.
4. Compare Tree-sitter vectors with dataset feature bags on matching source
   functions and publish coverage/agreement statistics.
5. Evaluate complete pages and domains at realistic vulnerability prevalence.
6. Report confidence intervals, false positives, false negatives, and ZAP
   confirmation separately.

Until those steps are complete, the correct description is **ML-assisted
DOM-XSS triage with optional dynamic verification**, not a guaranteed
standalone vulnerability detector.

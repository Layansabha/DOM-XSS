# Page-level regression benchmark

This directory contains a small, hand-labeled corpus that exercises the
runtime extractor and the page-level maximum-score aggregation used by the
application. Run it with:

```bash
make benchmark
```

The cases cover obvious unsafe source-to-sink flows, safe DOM APIs, constant
HTML, a React-style escaped text child, and a sanitization example. Labels and
rationales are stored beside every case in
[`page-level-corpus.json`](page-level-corpus.json), so failures can be reviewed
instead of hidden behind one aggregate number.

This is a deterministic **regression and diagnostic suite**. It is synthetic,
small, balanced, and does not execute complete websites in Chromium.
Consequently, its precision, recall, and accuracy are not estimates for the
public web and must not be used as commercial performance claims. A defensible
external benchmark still requires independently labeled modern applications,
domain-level isolation, realistic class prevalence, and reproducible dynamic
evidence.

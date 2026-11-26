# Changelog

## Unreleased

* The text summary names the lowest rated product among
  products with at least `--min-reviews` reviews (product
  id, name, average rating, review count). The line is
  omitted when no product reaches the minimum, and the
  JSON output is unchanged.

## 1.0.0 - 2026-11-20

Initial release.

* Unanswered negative review audit over a WooCommerce
  product reviews CSV export: unreplied negative reviews,
  negative reviews unanswered past the reply window,
  reviews awaiting moderation past the reply window, and
  products with too few reviews.
* Fake-review pattern checks: one author leaving many
  reviews, identical review text across reviews, and low
  ratings with almost no detail.
* Rating distribution per product (review count, average
  rating, 1 to 5 star counts, unreplied negative count),
  plus the overall average rating.
* Data quality checks: duplicate and missing review ids,
  missing product ids, malformed rows, invalid ratings and
  timestamps, future timestamps, and unknown statuses.
* Defensive timestamp parsing (ISO 8601 with or without a
  timezone, plus common day/month/year forms) and rating
  parsing (whole numbers from 1 to 5); a bad row is
  reported as a finding and never crashes the run. UTF-8
  BOM headers and extra columns handled.
* Findings carry a review id, a rule name, a severity (error
  or warning), and a message; errors and warnings are counted
  in the summary.
* Text and --json output, --out file output, --reply-days,
  --min-reviews, and --as-of thresholds, and a --check CI
  gate that exits 1 on errors (and on warnings with
  --strict).
* Zero dependencies, Python 3.10 or newer.

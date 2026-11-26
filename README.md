# woo-review-doctor

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/aamirtechs/woo-review-doctor/blob/main/LICENSE) [![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/aamirtechs/woo-review-doctor/issues)

A zero-dependency Python CLI that audits a WooCommerce
product reviews CSV export for the problems that quietly
cost a store sales: negative reviews with no owner reply,
negative reviews left unanswered past the reply window,
fake-review patterns (one author leaving many reviews,
identical review text, a low rating with no detail),
reviews stuck awaiting moderation past the reply window,
products with too few reviews to earn trust, and bad data
such as duplicate review ids, malformed rows, invalid
ratings, and invalid or future dates. It also prints the
rating distribution per product, so a store owner can see
at a glance which products are loved and which are in
trouble.

ReviewX and Ryviu report that over 90% of shoppers check
reviews before buying, 56% say a company's reply changed
their decision, and 45% of customers update a negative
review after a response. Review plugins manage reviews
live inside WordPress, but nobody audits the exported
reviews file first to say which reviews need a reply
today. This tool is that audit: it ranks the unanswered
reviews in the export alone, and never touches your store.

## Install

Requires Python 3.10 or newer. No dependencies beyond the
standard library.

```bash
pip install woo-review-doctor
```

Or run it straight from the source checkout:

```bash
python3 woo_review_doctor.py examples/reviews.csv
```

## Input format

A CSV export with a header row, from the store export, a
reviews plugin, or a manual export. Columns used:
`review_id` (or `id`), `product_id` (or `product`),
`product_name`, `reviewer`, `reviewer_email`, `rating`,
`review_text` (or `review`), `date` (or `review_date`),
`status`, `replied` (or `owner_replied`), and
`verified_owner`. Extra columns are ignored, so a full
reviews export works as-is. A UTF-8 BOM header is handled.
Only `review_id`, `product_id`, `rating`, and `date` are
required; the other columns are optional, and the checks
that need a missing column are skipped.

`date` also accepts `created_at` or `comment_date` as the
column name, `rating` also accepts `stars` or `score`,
`reviewer_email` also accepts `email`, and `replied` also
accepts `has_reply`, `reply`, or `answered`.

Dates accept ISO 8601 with or without a timezone
(`2026-11-17 10:00`, `2026-11-17T10:00:00Z`,
`2026-11-17`), plus day/month/year and month/day/year
forms. A date with no timezone is read as UTC. Ratings
accept whole numbers from 1 to 5 (`5`, `5.0`). A replied
value of `yes`, `true`, `1`, or `y` counts as replied;
anything else, including an empty value, means no reply
yet.

```csv
review_id,product_id,product_name,reviewer,reviewer_email,rating,review_text,date,status,replied,verified_owner
R-101,P-201,Wool Throw Blanket,Ana,ana@example.com,1,Arrived torn and the colour is wrong.,2026-11-17 10:00,approved,no,yes
R-102,P-201,Wool Throw Blanket,Ben,ben@example.com,2,Zip broke after one wash.,2026-11-10 09:00,approved,no,yes
R-103,P-202,Ceramic Mug,Cara,cara@example.com,3,"Nice mug, a bit small.",2026-11-16 09:00,approved,yes,yes
R-104,P-202,Ceramic Mug,Dan,dan@example.com,5,Love it.,2026-11-15 09:00,approved,no,yes
R-105,P-203,Linen Cushion Cover,Eve,eve@example.com,1,Bad.,2026-11-14 09:00,approved,no,no
```

## What it checks

Errors, the ones that mean a review needs a reply now or
data that cannot be trusted:

* `unreplied-negative-overdue`: an approved negative
  review (rating 1 or 2) with no owner reply more than
  `--reply-days` (default 7) after it was posted.
* `duplicate-review-id`: the same review id twice in the
  export.
* `missing-review-id`: a row with no review id, so the
  review cannot be matched to a reply.
* `missing-product-id`: a review with no product id, so it
  cannot be matched to a product.
* `invalid-rating`: a rating that is not a whole number
  from 1 to 5. The row is still audited on the fields that
  did parse.
* `invalid-timestamp`: a date field that matches no known
  format. The row is still audited on the fields that did
  parse.
* `future-timestamp`: a `date` after `--as-of` (default
  now).
* `invalid-status`: a status that is not a known review
  status (approved, pending, hold, spam, trash).
* `malformed-row`: a row with the wrong number of fields.
  The row is skipped and reported, never a crash.

Warnings, reviews that need a reply soon and patterns
worth a closer look:

* `unreplied-negative`: an approved negative review with
  no owner reply yet, still inside the reply window.
* `pending-moderation-overdue`: a pending (or on hold)
  review waiting more than `--reply-days` for moderation.
* `thin-low-rating`: a rating of 1 or 2 with fewer than 15
  characters of detail, so shoppers cannot tell what went
  wrong.
* `identical-text`: review text identical to one or more
  other reviews in the export (compared case-insensitively
  with whitespace collapsed), which looks like copied or
  fake reviews.
* `author-burst`: a reviewer email with four or more
  reviews in the export, which looks like a review burst
  from one author. Email matching is case-insensitive.
* `few-reviews`: a product with fewer than `--min-reviews`
  (default 5) reviews, so shoppers have little social
  proof.

The summary reports the average rating, the unreplied
negative count (with the overdue count), the pending
moderation overdue count, the fake-review pattern finding
count, the count of products with too few reviews, the
lowest rated product among those with at least
`--min-reviews` reviews (omitted when no product reaches
the minimum, and not part of the `--json` output), and a
per-product table with the review count, average rating,
1 to 5 star distribution, and unreplied negative count.

## Usage

```bash
python3 woo_review_doctor.py examples/reviews.csv --as-of 2026-11-18
```

Captured output:

```
ERROR [invalid-rating] R-117: rating 'six' is not a whole number from 1 to 5
ERROR [invalid-timestamp] R-118: date 'not-a-date' is not a readable date
ERROR [future-timestamp] R-119: date 2026-12-01 09:00 is after the as-of date 2026-11-18 00:00
ERROR [duplicate-review-id] R-101: review id appears more than once in the export
ERROR [malformed-row] row 27: row has 10 fields but the header has 11, so the row was skipped
ERROR [missing-review-id] row 28: row has no review id, so the review cannot be matched to a reply
ERROR [missing-product-id] R-126: review has no product id, so it cannot be matched to a product
WARNING [unreplied-negative] R-101: negative review (rating 1) has no owner reply yet
WARNING [identical-text] R-101: review text is identical to 1 other review in this export, which looks like copied or fake reviews
ERROR [unreplied-negative-overdue] R-102: negative review (rating 2) has no owner reply 7.6 days after it was posted, past the 7 day reply window
WARNING [unreplied-negative] R-105: negative review (rating 1) has no owner reply yet
WARNING [thin-low-rating] R-105: rating 1 has only 4 characters of detail, so shoppers cannot tell what went wrong
ERROR [unreplied-negative-overdue] R-106: negative review (rating 1) has no owner reply 12.6 days after it was posted, past the 7 day reply window
WARNING [identical-text] R-106: review text is identical to 1 other review in this export, which looks like copied or fake reviews
ERROR [unreplied-negative-overdue] R-107: negative review (rating 1) has no owner reply 12.6 days after it was posted, past the 7 day reply window
WARNING [identical-text] R-107: review text is identical to 1 other review in this export, which looks like copied or fake reviews
WARNING [identical-text] R-108: review text is identical to 1 other review in this export, which looks like copied or fake reviews
WARNING [identical-text] R-109: review text is identical to 1 other review in this export, which looks like copied or fake reviews
WARNING [unreplied-negative] R-110: negative review (rating 2) has no owner reply yet
WARNING [thin-low-rating] R-110: rating 2 has only 0 characters of detail, so shoppers cannot tell what went wrong
WARNING [pending-moderation-overdue] R-111: review has waited 9.6 days for moderation, past the 7 day reply window
WARNING [pending-moderation-overdue] R-112: review has waited 8.6 days for moderation, past the 7 day reply window
WARNING [identical-text] R-113: review text is identical to 2 other reviews in this export, which looks like copied or fake reviews
WARNING [identical-text] R-114: review text is identical to 2 other reviews in this export, which looks like copied or fake reviews
WARNING [identical-text] R-115: review text is identical to 2 other reviews in this export, which looks like copied or fake reviews
WARNING [identical-text] R-117: review text is identical to 1 other review in this export, which looks like copied or fake reviews
WARNING [identical-text] R-118: review text is identical to 1 other review in this export, which looks like copied or fake reviews
WARNING [author-burst] R-119: reviewer sam@example.com has 5 reviews in this export, which looks like a review burst from one author
ERROR [invalid-status] R-120: status 'weird' is not a known review status
WARNING [author-burst] R-121: reviewer sam@example.com has 5 reviews in this export, which looks like a review burst from one author
WARNING [author-burst] R-122: reviewer sam@example.com has 5 reviews in this export, which looks like a review burst from one author
WARNING [author-burst] R-123: reviewer sam@example.com has 5 reviews in this export, which looks like a review burst from one author
WARNING [author-burst] R-124: reviewer sam@example.com has 5 reviews in this export, which looks like a review burst from one author
WARNING [unreplied-negative] R-101: negative review (rating 1) has no owner reply yet
WARNING [identical-text] R-101: review text is identical to 1 other review in this export, which looks like copied or fake reviews
WARNING [few-reviews] product P-201: product has only 4 reviews, below the 5 review minimum, so shoppers have little social proof
WARNING [few-reviews] product P-202: product has only 3 reviews, below the 5 review minimum, so shoppers have little social proof
WARNING [few-reviews] product P-203: product has only 3 reviews, below the 5 review minimum, so shoppers have little social proof
WARNING [few-reviews] product P-204: product has only 2 reviews, below the 5 review minimum, so shoppers have little social proof
WARNING [few-reviews] product P-205: product has only 4 reviews, below the 5 review minimum, so shoppers have little social proof
WARNING [few-reviews] product P-206: product has only 4 reviews, below the 5 review minimum, so shoppers have little social proof
WARNING [few-reviews] product P-207: product has only 3 reviews, below the 5 review minimum, so shoppers have little social proof
WARNING [few-reviews] product P-208: product has only 2 reviews, below the 5 review minimum, so shoppers have little social proof
WARNING [few-reviews] product P-209: product has only 1 reviews, below the 5 review minimum, so shoppers have little social proof

Reviews: 27, findings: 44, errors: 11, warnings: 33
Average rating: 3.58, unreplied negative reviews: 7 (3 overdue), pending moderation overdue: 2
Fake-review pattern findings: 18, products with too few reviews: 9

Per-product rating summary:
P-201 Wool Throw Blanket: 4 reviews, avg 2.25, 5:1 4:0 3:0 2:1 1:2, unreplied negatives: 3
P-202 Ceramic Mug: 3 reviews, avg 4.33, 5:2 4:0 3:1 2:0 1:0, unreplied negatives: 0
P-203 Linen Cushion Cover: 3 reviews, avg 1.00, 5:0 4:0 3:0 2:0 1:3, unreplied negatives: 3
P-204 Oak Side Table: 2 reviews, avg 5.00, 5:2 4:0 3:0 2:0 1:0, unreplied negatives: 0
P-205 Cotton Tote Bag: 4 reviews, avg 3.75, 5:1 4:2 3:0 2:1 1:0, unreplied negatives: 1
P-206 Wool Scarf: 4 reviews, avg 5.00, 5:4 4:0 3:0 2:0 1:0, unreplied negatives: 0
P-207 Desk Lamp: 3 reviews, avg 2.50, 5:0 4:1 3:0 2:0 1:1, unreplied negatives: 0
P-208 Canvas Wall Art: 2 reviews, avg 4.00, 5:1 4:0 3:1 2:0 1:0, unreplied negatives: 0
P-209 Leather Wallet: 1 reviews, avg 5.00, 5:1 4:0 3:0 2:0 1:0, unreplied negatives: 0
```

The sample has 28 rows; the malformed row 27 is skipped,
so 27 reviews are audited. The headline numbers are 7
unreplied negative reviews, 3 of them overdue, 2 reviews
waiting too long for moderation, 18 fake-review pattern
findings (Sam left 5 reviews across the store, three
reviewers pasted the same "Warm and soft." text, and two
more pairs share identical text), and all 9 products below
the 5 review minimum. The worst product is the Linen
Cushion Cover at an average of 1.00 with 3 unreplied
negative reviews, so it is the first product to fix. No
product reaches the 5 review minimum, so the lowest rated
product line is omitted; with `--min-reviews 3` it names
the Linen Cushion Cover.

Use it as a CI gate: `--check` exits 1 when any error is
found, and 0 otherwise. On the sample above it exits 1:

```bash
python3 woo_review_doctor.py examples/reviews.csv --as-of 2026-11-18 --check
```

On `examples/clean.csv`, five clean reviews for one
product, it exits 0:

```
Reviews: 5, findings: 0, errors: 0, warnings: 0
Average rating: 4.60, unreplied negative reviews: 0 (0 overdue), pending moderation overdue: 0
Fake-review pattern findings: 0, products with too few reviews: 0
Lowest rated product with at least 5 reviews: P-301 Wool Throw Blanket, avg 4.60 from 5 reviews

Per-product rating summary:
P-301 Wool Throw Blanket: 5 reviews, avg 4.60, 5:3 4:2 3:0 2:0 1:0, unreplied negatives: 0

All reviews clean.
```

With `--strict`, `--check` also fails on warnings.
`examples/warnings-only.csv` has one unreplied negative
review and one product with too few reviews, so it passes
`--check` (exit 0) and fails `--check --strict` (exit 1).
With a lower review minimum the few-reviews warning drops
out:

```bash
python3 woo_review_doctor.py examples/warnings-only.csv --as-of 2026-11-18 --min-reviews 2
```

Captured output:

```
WARNING [unreplied-negative] R-401: negative review (rating 1) has no owner reply yet

Reviews: 2, findings: 1, errors: 0, warnings: 1
Average rating: 3.00, unreplied negative reviews: 1 (0 overdue), pending moderation overdue: 0
Fake-review pattern findings: 0, products with too few reviews: 0
Lowest rated product with at least 2 reviews: P-401 Cotton Tote Bag, avg 3.00 from 2 reviews

Per-product rating summary:
P-401 Cotton Tote Bag: 2 reviews, avg 3.00, 5:1 4:0 3:0 2:0 1:1, unreplied negatives: 1
```

A shorter reply window escalates the same review to an
error:

```bash
python3 woo_review_doctor.py examples/warnings-only.csv --as-of 2026-11-18 --reply-days 0 --check
```

Captured output:

```
ERROR [unreplied-negative-overdue] R-401: negative review (rating 1) has no owner reply 0.6 days after it was posted, past the 0 day reply window
WARNING [few-reviews] product P-401: product has only 2 reviews, below the 5 review minimum, so shoppers have little social proof

Reviews: 2, findings: 2, errors: 1, warnings: 1
Average rating: 3.00, unreplied negative reviews: 1 (1 overdue), pending moderation overdue: 0
Fake-review pattern findings: 0, products with too few reviews: 1

Per-product rating summary:
P-401 Cotton Tote Bag: 2 reviews, avg 3.00, 5:1 4:0 3:0 2:0 1:1, unreplied negatives: 1
```

`--json` emits the summary and the findings as JSON, and
`--out` writes the report to a file. JSON for the
warnings-only file:

```json
{
  "reviews": 2,
  "findings": [
    {
      "review": "R-401",
      "rule": "unreplied-negative",
      "severity": "warning",
      "message": "negative review (rating 1) has no owner reply yet"
    },
    {
      "review": "product P-401",
      "rule": "few-reviews",
      "severity": "warning",
      "message": "product has only 2 reviews, below the 5 review minimum, so shoppers have little social proof"
    }
  ],
  "errors": 0,
  "warnings": 2,
  "average_rating": 3.0,
  "unreplied_negatives": 1,
  "overdue_unreplied_negatives": 0,
  "pending_moderation_overdue": 0,
  "fake_pattern_findings": 0,
  "products_with_few_reviews": 1,
  "per_product": [
    {
      "product_id": "P-401",
      "product_name": "Cotton Tote Bag",
      "reviews": 2,
      "average_rating": 3.0,
      "distribution": {
        "1": 1,
        "2": 0,
        "3": 0,
        "4": 0,
        "5": 1
      },
      "unreplied_negatives": 1
    }
  ]
}
```

## Options

| Flag | Meaning |
| --- | --- |
| `--reply-days` | A negative review unanswered more than this many days is overdue, and a pending review older than this is overdue for moderation (default: 7) |
| `--min-reviews` | A product with fewer reviews than this has too few reviews (default: 5) |
| `--as-of` | Date to compare timestamps against, for example 2026-11-18 (default: now) |
| `--json` | Emit JSON instead of text |
| `--check` | Exit 1 if any error is found |
| `--strict` | With --check, also exit 1 on warnings |
| `--out` | Write the report to a file |

## Edge cases

* A row with too many or too few fields is a malformed-row
  error and is skipped; the rest of the file is still
  audited.
* A bad rating or date is an error, and the row is still
  audited on the fields that did parse, so one bad value
  never hides the other problems on the review. A review
  with an unreadable rating is left out of the average and
  the per-product distribution.
* A negative review that the owner already replied to is
  clean, however old it is. A negative review with a
  pending or spam status is not counted as unreplied,
  since it is not live on the store yet or is already
  filtered out.
* The overdue check only fires when the review date parsed
  and is not in the future; a future-dated review gets the
  future-timestamp error instead, and its age is negative,
  so it never also fires the overdue error.
* Identical-text matching is case-insensitive and ignores
  extra whitespace, but empty review text never counts as
  identical, so two blank reviews are not flagged as
  copies of each other.
* Author grouping is by email, case-insensitive, so
  Sam@example.com and sam@example.com count as one author.
  Reviews with no email are never grouped into a burst.
* A blank line in the file is skipped silently. A review
  with no product name still appears in the per-product
  table as `(no name)`.
* `--as-of` makes runs reproducible: without it, the
  future-timestamp and overdue checks compare against the
  current time.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

75 tests, all passing: timestamp and rating parsing,
replied value parsing, header aliases and BOM handling,
malformed rows, duplicate and missing review ids, missing
product ids, invalid ratings and timestamps, future
timestamps, unreplied negative and overdue rules with the
reply window boundary, replied and positive reviews
staying clean, pending moderation rules, thin low ratings,
identical-text matching, author bursts, few-reviews
thresholds, summary totals and per-product distributions,
text and JSON output, `--out` file output, `--reply-days`
and `--min-reviews` flags, and `--check` and `--strict`
exit codes. The same 75 tests pass under pytest.

## License

MIT. See [LICENSE](LICENSE).

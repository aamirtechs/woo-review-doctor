"""WooCommerce product reviews audit CLI.

Reads a WooCommerce product reviews CSV export (from the
store export, a reviews plugin, or a manual export) and
audits every review for the problems that quietly cost a
store sales: negative reviews with no owner reply, negative
reviews left unanswered past the reply window, fake-review
patterns (one author leaving many reviews, identical review
text, a low rating with no detail), reviews stuck awaiting
moderation past the reply window, products with too few
reviews to earn trust, and bad data such as duplicate review
ids, malformed rows, and invalid ratings or dates. It also
prints the rating distribution per product, so a store owner
can see at a glance which products are loved and which are
in trouble.

ReviewX and Ryviu report that over 90% of shoppers check
reviews before buying, 56% say a company's reply changed
their decision, and 45% of customers update a negative
review after a response. Review plugins manage reviews live
inside WordPress, but nobody audits the exported reviews
file first to say which reviews need a reply today. This
tool is that audit: it ranks the unanswered reviews in the
export alone, and never touches your store.

Each problem is a finding with a review id, a rule name, a
severity (error or warning), and a message. Errors are
unanswered negative reviews past the reply window and data
that cannot be trusted; warnings are reviews that need a
reply soon and patterns worth a closer look. --check exits
1 when any error is found, and --strict also fails on
warnings.

Dates are parsed defensively. A bad date or rating is
reported as a finding and the row is still audited on the
fields that did parse, so one bad row never crashes the run.

Zero dependencies, Python 3.10 or newer, standard library only.

Usage:
    python3 woo_review_doctor.py examples/reviews.csv
    python3 woo_review_doctor.py reviews.csv --json --check
    python3 woo_review_doctor.py reviews.csv --as-of 2026-11-18
"""

import argparse
import csv
import json
import sys
from datetime import datetime, timezone

__version__ = "1.0.0"

DEFAULT_REPLY_DAYS = 7
DEFAULT_MIN_REVIEWS = 5
DEFAULT_FAKE_AUTHOR_COUNT = 4
DEFAULT_THIN_TEXT_CHARS = 15

KNOWN_STATUSES = {"approved", "pending", "hold", "spam", "trash"}

TIMESTAMP_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M",
    "%m/%d/%Y %H:%M",
    "%d/%m/%Y",
    "%m/%d/%Y",
)


class Finding:
    """One audit finding for one review, or for one product."""

    def __init__(self, review, rule, severity, message):
        self.review = review
        self.rule = rule
        self.severity = severity
        self.message = message

    def as_dict(self):
        """Return the finding as a plain dict."""
        return {"review": self.review, "rule": self.rule,
                "severity": self.severity, "message": self.message}

    def __str__(self):
        return "%s [%s] %s: %s" % (self.severity.upper(), self.rule,
                                   self.review, self.message)


def parse_timestamp(text):
    """Parse a timestamp string into an aware datetime, or None.

    Accepts ISO 8601 with or without a timezone (a trailing Z is
    handled), plus a few common export formats. A naive timestamp
    is read as UTC. Returns None for an empty string or a value
    that matches no known format, so callers can report it
    instead of crashing.
    """
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    candidate = text
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        parsed = None
    if parsed is None:
        for fmt in TIMESTAMP_FORMATS:
            try:
                parsed = datetime.strptime(candidate, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def parse_rating(text):
    """Parse a rating string into an int from 1 to 5, or None.

    Accepts whole numbers and whole-number decimals (for
    example "5" and "5.0"). Returns None for an empty string,
    a value that is not a number, or a number outside 1 to 5.
    """
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    if value != int(value):
        return None
    value = int(value)
    if value < 1 or value > 5:
        return None
    return value


def parse_replied(text):
    """Return True when a replied column value means yes.

    Accepts yes, true, 1, and y (case-insensitive). Anything
    else, including an empty value, means no reply yet.
    """
    if text is None:
        return False
    return text.strip().lower() in ("yes", "true", "1", "y")


def find_column(header, names):
    """Return the first of names present in header, or None."""
    for name in names:
        if name in header:
            return name
    return None


def normalize_text(text):
    """Normalize review text for identical-text matching."""
    return " ".join(text.lower().split())


def parse_csv(path, as_of):
    """Parse a WooCommerce product reviews CSV export.

    Returns (reviews, findings). Each review is a dict with
    the id, product id and name, reviewer, rating, text, the
    parsed date, status, and whether the owner replied. Rows
    with the wrong number of fields are reported as
    malformed-row errors and skipped, never a crash. A UTF-8
    BOM header is handled. Extra columns are ignored.
    """
    findings = []
    reviews = []
    try:
        handle = open(path, newline="", encoding="utf-8-sig")
    except OSError as exc:
        raise ValueError("cannot read %s: %s" % (path, exc))
    with handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError("%s is empty, no header row found" % path)
        except csv.Error as exc:
            raise ValueError("%s is not a readable CSV file: %s"
                             % (path, exc))
        header = [name.strip() for name in header]
        id_column = find_column(header, ("review_id", "id", "comment_id"))
        if id_column is None:
            raise ValueError(
                "%s has no review_id or id column (header is: %s)"
                % (path, ", ".join(header)))
        product_column = find_column(
            header, ("product_id", "product", "post_id"))
        if product_column is None:
            raise ValueError(
                "%s has no product_id column "
                "(header is: %s)" % (path, ", ".join(header)))
        rating_column = find_column(header, ("rating", "stars", "score"))
        if rating_column is None:
            raise ValueError(
                "%s has no rating column "
                "(header is: %s)" % (path, ", ".join(header)))
        name_column = find_column(
            header, ("product_name", "product_title", "title"))
        reviewer_column = find_column(
            header, ("reviewer", "author", "reviewer_name",
                     "comment_author"))
        email_column = find_column(
            header, ("reviewer_email", "email", "comment_author_email"))
        text_column = find_column(
            header, ("review_text", "review", "comment", "content"))
        date_column = find_column(
            header, ("date", "review_date", "created_at", "comment_date"))
        if date_column is None:
            raise ValueError(
                "%s has no date column "
                "(header is: %s)" % (path, ", ".join(header)))
        status_column = find_column(header, ("status", "comment_status",
                                             "review_status"))
        replied_column = find_column(
            header, ("replied", "owner_replied", "has_reply",
                     "reply", "answered"))
        seen_ids = set()
        for line_number, row in enumerate(reader, start=2):
            if not row or all(not cell.strip() for cell in row):
                continue
            if len(row) != len(header):
                findings.append(Finding(
                    "row %d" % line_number, "malformed-row", "error",
                    "row has %d fields but the header has %d, "
                    "so the row was skipped" % (len(row), len(header))))
                continue
            cells = dict(zip(header, (cell.strip() for cell in row)))
            review_id = cells[id_column]
            if not review_id:
                findings.append(Finding(
                    "row %d" % line_number, "missing-review-id", "error",
                    "row has no review id, so the review cannot be "
                    "matched to a reply"))
                review_id = "row %d" % line_number
            if review_id in seen_ids:
                findings.append(Finding(
                    review_id, "duplicate-review-id", "error",
                    "review id appears more than once in the export"))
            else:
                seen_ids.add(review_id)
            product_id = cells[product_column]
            if not product_id:
                findings.append(Finding(
                    review_id, "missing-product-id", "error",
                    "review has no product id, so it cannot be "
                    "matched to a product"))
            rating_raw = cells[rating_column]
            rating = parse_rating(rating_raw)
            if rating is None:
                findings.append(Finding(
                    review_id, "invalid-rating", "error",
                    "rating %r is not a whole number from 1 to 5"
                    % rating_raw))
            date_raw = cells[date_column]
            review_date = None
            if date_raw:
                review_date = parse_timestamp(date_raw)
                if review_date is None:
                    findings.append(Finding(
                        review_id, "invalid-timestamp", "error",
                        "date %r is not a readable date" % date_raw))
            if review_date is not None and review_date > as_of:
                findings.append(Finding(
                    review_id, "future-timestamp", "error",
                    "date %s is after the as-of date %s"
                    % (review_date.strftime("%Y-%m-%d %H:%M"),
                       as_of.strftime("%Y-%m-%d %H:%M"))))
            status = cells[status_column].lower() if status_column else ""
            reviews.append({
                "id": review_id,
                "product_id": product_id,
                "product_name": (cells[name_column]
                                 if name_column else ""),
                "reviewer": (cells[reviewer_column]
                             if reviewer_column else ""),
                "email": (cells[email_column]
                          if email_column else ""),
                "rating": rating,
                "rating_raw": rating_raw,
                "text": (cells[text_column] if text_column else ""),
                "date": review_date,
                "date_raw": date_raw,
                "status": status,
                "replied": (parse_replied(cells[replied_column])
                            if replied_column else False),
                "line": line_number})
    return reviews, findings


def audit(reviews, as_of, reply_days=DEFAULT_REPLY_DAYS,
          min_reviews=DEFAULT_MIN_REVIEWS,
          fake_author_count=DEFAULT_FAKE_AUTHOR_COUNT,
          thin_text_chars=DEFAULT_THIN_TEXT_CHARS):
    """Audit a parsed review list and return a list of findings."""
    findings = []
    reviews_by_email = {}
    for review in reviews:
        if review["email"]:
            key = review["email"].lower()
            reviews_by_email[key] = reviews_by_email.get(key, 0) + 1
    text_groups = {}
    for review in reviews:
        normalized = normalize_text(review["text"])
        if normalized:
            text_groups.setdefault(normalized, []).append(review)
    reviews_by_product = {}
    for review in reviews:
        if review["product_id"]:
            reviews_by_product.setdefault(
                review["product_id"], []).append(review)
    for review in reviews:
        review_id = review["id"]
        status = review["status"]
        rating = review["rating"]
        review_date = review["date"]
        age_days = None
        if review_date is not None:
            age_days = (as_of - review_date).total_seconds() / 86400.0

        if status and status not in KNOWN_STATUSES:
            findings.append(Finding(
                review_id, "invalid-status", "error",
                "status %r is not a known review status" % status))
        if status == "approved" and rating is not None and rating <= 2 \
                and not review["replied"]:
            if age_days is not None and age_days > reply_days:
                findings.append(Finding(
                    review_id, "unreplied-negative-overdue", "error",
                    "negative review (rating %d) has no owner "
                    "reply %.1f days after it was posted, past "
                    "the %d day reply window"
                    % (rating, age_days, reply_days)))
            else:
                findings.append(Finding(
                    review_id, "unreplied-negative", "warning",
                    "negative review (rating %d) has no owner "
                    "reply yet" % rating))
        if status in ("pending", "hold") and age_days is not None \
                and age_days > reply_days:
            findings.append(Finding(
                review_id, "pending-moderation-overdue", "warning",
                "review has waited %.1f days for moderation, "
                "past the %d day reply window"
                % (age_days, reply_days)))
        if rating is not None and rating <= 2 \
                and len(review["text"].strip()) < thin_text_chars:
            findings.append(Finding(
                review_id, "thin-low-rating", "warning",
                "rating %d has only %d characters of detail, "
                "so shoppers cannot tell what went wrong"
                % (rating, len(review["text"].strip()))))
        normalized = normalize_text(review["text"])
        if normalized and len(text_groups.get(normalized, [])) >= 2:
            others = len(text_groups[normalized]) - 1
            findings.append(Finding(
                review_id, "identical-text", "warning",
                "review text is identical to %d other review%s "
                "in this export, which looks like copied or "
                "fake reviews"
                % (others, "" if others == 1 else "s")))
        if review["email"]:
            count = reviews_by_email.get(review["email"].lower(), 0)
            if count >= fake_author_count:
                findings.append(Finding(
                    review_id, "author-burst", "warning",
                    "reviewer %s has %d reviews in this "
                    "export, which looks like a review burst "
                    "from one author"
                    % (review["email"], count)))
    for product_id in sorted(reviews_by_product):
        product_reviews = reviews_by_product[product_id]
        if len(product_reviews) < min_reviews:
            findings.append(Finding(
                "product %s" % product_id, "few-reviews", "warning",
                "product has only %d reviews, below the %d "
                "review minimum, so shoppers have little "
                "social proof" % (len(product_reviews), min_reviews)))
    return findings


def summarize(reviews, findings, as_of,
              reply_days=DEFAULT_REPLY_DAYS,
              min_reviews=DEFAULT_MIN_REVIEWS):
    """Return the summary counts for a review list and findings."""
    errors = sum(1 for item in findings if item.severity == "error")
    warnings = sum(1 for item in findings
                   if item.severity == "warning")
    ratings = [review["rating"] for review in reviews
               if review["rating"] is not None]
    average = (sum(ratings) / len(ratings)) if ratings else 0.0
    unreplied = sum(
        1 for item in findings
        if item.rule in ("unreplied-negative",
                         "unreplied-negative-overdue"))
    overdue = sum(
        1 for item in findings
        if item.rule == "unreplied-negative-overdue")
    pending = sum(
        1 for item in findings
        if item.rule == "pending-moderation-overdue")
    fake = sum(
        1 for item in findings
        if item.rule in ("author-burst", "identical-text",
                         "thin-low-rating"))
    few = sum(1 for item in findings if item.rule == "few-reviews")
    per_product = []
    products = {}
    for review in reviews:
        if review["product_id"]:
            products.setdefault(review["product_id"], []).append(review)
    for product_id in sorted(products):
        product_reviews = products[product_id]
        product_ratings = [review["rating"] for review in product_reviews
                           if review["rating"] is not None]
        product_average = (sum(product_ratings) / len(product_ratings)
                           if product_ratings else 0.0)
        distribution = {star: 0 for star in (1, 2, 3, 4, 5)}
        for rating in product_ratings:
            distribution[rating] += 1
        name = ""
        for review in product_reviews:
            if review["product_name"]:
                name = review["product_name"]
                break
        unreplied_negatives = sum(
            1 for review in product_reviews
            if review["status"] == "approved"
            and review["rating"] is not None
            and review["rating"] <= 2 and not review["replied"])
        per_product.append({
            "product_id": product_id,
            "product_name": name,
            "reviews": len(product_reviews),
            "average_rating": round(product_average, 2),
            "distribution": {"1": distribution[1], "2": distribution[2],
                             "3": distribution[3], "4": distribution[4],
                             "5": distribution[5]},
            "unreplied_negatives": unreplied_negatives})
    return {"reviews": len(reviews),
            "findings": len(findings),
            "errors": errors,
            "warnings": warnings,
            "average_rating": round(average, 2),
            "unreplied_negatives": unreplied,
            "overdue_unreplied_negatives": overdue,
            "pending_moderation_overdue": pending,
            "fake_pattern_findings": fake,
            "products_with_few_reviews": few,
            "per_product": per_product}


def lowest_rated_product(per_product, min_reviews=DEFAULT_MIN_REVIEWS):
    """Return the lowest rated per-product row, or None.

    Only products with at least min_reviews reviews and at least
    one valid rating are considered. Ties on the average rating
    go to the product id that sorts first. Returns None when no
    product qualifies.
    """
    candidates = [row for row in per_product
                  if row["reviews"] >= min_reviews
                  and sum(row["distribution"].values()) > 0]
    if not candidates:
        return None
    return min(candidates,
               key=lambda row: (row["average_rating"],
                                row["product_id"]))


def render_text(reviews, findings, summary,
                min_reviews=DEFAULT_MIN_REVIEWS):
    """Render the text report."""
    lines = [str(item) for item in findings]
    lines.append("")
    lines.append("Reviews: %(reviews)d, findings: %(findings)d, "
                 "errors: %(errors)d, warnings: %(warnings)d"
                 % summary)
    lines.append("Average rating: %(average_rating).2f, "
                 "unreplied negative reviews: "
                 "%(unreplied_negatives)d "
                 "(%(overdue_unreplied_negatives)d overdue), "
                 "pending moderation overdue: "
                 "%(pending_moderation_overdue)d" % summary)
    lines.append("Fake-review pattern findings: "
                 "%(fake_pattern_findings)d, products with too "
                 "few reviews: %(products_with_few_reviews)d"
                 % summary)
    lowest = lowest_rated_product(summary["per_product"], min_reviews)
    if lowest is not None:
        lines.append("Lowest rated product with at least %d "
                     "reviews: %s %s, avg %.2f from %d reviews"
                     % (min_reviews, lowest["product_id"],
                        lowest["product_name"] or "(no name)",
                        lowest["average_rating"], lowest["reviews"]))
    lines.append("")
    lines.append("Per-product rating summary:")
    for row in summary["per_product"]:
        distribution = row["distribution"]
        lines.append(
            "%s %s: %d reviews, avg %.2f, "
            "5:%d 4:%d 3:%d 2:%d 1:%d, unreplied negatives: %d"
            % (row["product_id"], row["product_name"] or "(no name)",
               row["reviews"], row["average_rating"],
               distribution["5"], distribution["4"],
               distribution["3"], distribution["2"],
               distribution["1"], row["unreplied_negatives"]))
    if summary["findings"] == 0:
        lines.append("")
        lines.append("All reviews clean.")
    return "\n".join(lines) + "\n"


def render_json(reviews, findings, summary):
    """Render the JSON report."""
    report = dict(summary)
    report["findings"] = [item.as_dict() for item in findings]
    return json.dumps(report, indent=2) + "\n"


def build_parser():
    """Build the command line parser."""
    parser = argparse.ArgumentParser(
        prog="woo-review-doctor",
        description="Audit a WooCommerce product reviews CSV "
                    "export for unanswered negative reviews, "
                    "fake-review patterns, and rating problems.")
    parser.add_argument("csv_file", help="product reviews CSV "
                        "export to audit")
    parser.add_argument("--reply-days", type=int,
                        default=DEFAULT_REPLY_DAYS,
                        help="a negative review unanswered more "
                        "than this many days is overdue, and a "
                        "pending review older than this is overdue "
                        "for moderation "
                        "(default: %d)" % DEFAULT_REPLY_DAYS)
    parser.add_argument("--min-reviews", type=int,
                        default=DEFAULT_MIN_REVIEWS,
                        help="a product with fewer reviews than "
                        "this has too few reviews "
                        "(default: %d)" % DEFAULT_MIN_REVIEWS)
    parser.add_argument("--as-of", default=None,
                        help="date to compare timestamps against, "
                        "for example 2026-11-18 (default: now)")
    parser.add_argument("--json", action="store_true",
                        help="emit JSON instead of text")
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if any error is found")
    parser.add_argument("--strict", action="store_true",
                        help="with --check, also exit 1 on warnings")
    parser.add_argument("--out", default=None,
                        help="write the report to a file")
    return parser


def main(argv=None):
    """Run the CLI and return the exit code."""
    args = build_parser().parse_args(argv)
    if args.reply_days < 0:
        print("error: --reply-days must be at least 0",
              file=sys.stderr)
        return 2
    if args.min_reviews < 0:
        print("error: --min-reviews must be at least 0",
              file=sys.stderr)
        return 2
    if args.as_of is None:
        as_of = datetime.now(timezone.utc)
    else:
        as_of = parse_timestamp(args.as_of)
        if as_of is None:
            print("error: --as-of %r is not a readable date"
                  % args.as_of, file=sys.stderr)
            return 2
    try:
        reviews, findings = parse_csv(args.csv_file, as_of)
    except ValueError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    findings.extend(audit(reviews, as_of,
                          reply_days=args.reply_days,
                          min_reviews=args.min_reviews))
    summary = summarize(reviews, findings, as_of,
                        reply_days=args.reply_days,
                        min_reviews=args.min_reviews)
    if args.json:
        report = render_json(reviews, findings, summary)
    else:
        report = render_text(reviews, findings, summary,
                             min_reviews=args.min_reviews)
    if args.out is not None:
        try:
            with open(args.out, "w", encoding="utf-8") as handle:
                handle.write(report)
        except OSError as exc:
            print("error: cannot write %s: %s" % (args.out, exc),
                  file=sys.stderr)
            return 2
    else:
        sys.stdout.write(report)
    if args.check:
        if summary["errors"] > 0:
            return 1
        if args.strict and summary["warnings"] > 0:
            return 1
    return 0


def main_entry():
    """Console script entry point."""
    sys.exit(main())


if __name__ == "__main__":
    main_entry()

"""Tests for woo_review_doctor."""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

import woo_review_doctor as doctor

AS_OF = datetime(2026, 11, 18, tzinfo=timezone.utc)

HEADER = ("review_id,product_id,product_name,reviewer,"
          "reviewer_email,rating,review_text,date,status,"
          "replied,verified_owner\n")


def write_csv(body, directory=None):
    """Write body to a temp CSV file and return its path."""
    handle = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False,
        dir=directory, encoding="utf-8")
    handle.write(body)
    handle.close()
    return handle.name


def row(review_id="R-1", product="P-1", name="Widget",
        reviewer="Ana", email="ana@example.com", rating="5",
        text="Great product, very happy with it.",
        date="2026-11-17 09:00",
        status="approved", replied="no", verified="yes"):
    """Build one CSV data row."""
    return ",".join((review_id, product, name, reviewer, email,
                     rating, '"%s"' % text if "," in text else text,
                     date, status, replied, verified)) + "\n"


def run_cli(argv):
    """Run main with argv and capture stdout, return (code, text)."""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = doctor.main(argv)
    return code, buffer.getvalue()


class TestParseTimestamp(unittest.TestCase):
    def test_iso_with_time(self):
        parsed = doctor.parse_timestamp("2026-11-17 10:00")
        self.assertEqual(parsed, datetime(2026, 11, 17, 10, 0,
                                         tzinfo=timezone.utc))

    def test_iso_with_z(self):
        parsed = doctor.parse_timestamp("2026-11-17T10:00:00Z")
        self.assertEqual(parsed, datetime(2026, 11, 17, 10, 0,
                                         tzinfo=timezone.utc))

    def test_date_only(self):
        parsed = doctor.parse_timestamp("2026-11-17")
        self.assertEqual(parsed, datetime(2026, 11, 17,
                                         tzinfo=timezone.utc))

    def test_day_month_year(self):
        parsed = doctor.parse_timestamp("17/11/2026 09:00")
        self.assertEqual(parsed, datetime(2026, 11, 17, 9, 0,
                                         tzinfo=timezone.utc))

    def test_bad_value(self):
        self.assertIsNone(doctor.parse_timestamp("not-a-date"))

    def test_empty_value(self):
        self.assertIsNone(doctor.parse_timestamp(""))
        self.assertIsNone(doctor.parse_timestamp(None))


class TestParseRating(unittest.TestCase):
    def test_whole_numbers(self):
        for text, value in (("1", 1), ("3", 3), ("5", 5)):
            self.assertEqual(doctor.parse_rating(text), value)

    def test_whole_decimal(self):
        self.assertEqual(doctor.parse_rating("5.0"), 5)

    def test_fraction_rejected(self):
        self.assertIsNone(doctor.parse_rating("4.5"))

    def test_out_of_range(self):
        self.assertIsNone(doctor.parse_rating("0"))
        self.assertIsNone(doctor.parse_rating("6"))

    def test_non_numeric(self):
        self.assertIsNone(doctor.parse_rating("six"))
        self.assertIsNone(doctor.parse_rating(""))

    def test_whitespace(self):
        self.assertEqual(doctor.parse_rating(" 4 "), 4)


class TestParseReplied(unittest.TestCase):
    def test_yes_forms(self):
        for text in ("yes", "Yes", "YES", "true", "1", "y"):
            self.assertTrue(doctor.parse_replied(text))

    def test_no_forms(self):
        for text in ("no", "false", "0", "", "maybe"):
            self.assertFalse(doctor.parse_replied(text))
        self.assertFalse(doctor.parse_replied(None))


class TestParseCsv(unittest.TestCase):
    def setUp(self):
        self.paths = []

    def tearDown(self):
        for path in self.paths:
            os.unlink(path)

    def parse(self, body):
        path = write_csv(body)
        self.paths.append(path)
        return doctor.parse_csv(path, AS_OF)

    def test_clean_row_parses(self):
        reviews, findings = self.parse(HEADER + row())
        self.assertEqual(len(reviews), 1)
        self.assertEqual(findings, [])
        review = reviews[0]
        self.assertEqual(review["id"], "R-1")
        self.assertEqual(review["product_id"], "P-1")
        self.assertEqual(review["rating"], 5)
        self.assertFalse(review["replied"])

    def test_header_aliases(self):
        body = ("id,product,review,author,score,date,comment_status\n"
                "R-9,P-9,Great,Ben,5,2026-11-17 09:00,approved\n")
        reviews, findings = self.parse(body)
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0]["id"], "R-9")
        self.assertEqual(reviews[0]["product_id"], "P-9")
        self.assertEqual(reviews[0]["rating"], 5)
        self.assertEqual(findings, [])

    def test_bom_header(self):
        reviews, findings = self.parse("\ufeff" + HEADER + row())
        self.assertEqual(len(reviews), 1)
        self.assertEqual(findings, [])

    def test_missing_file(self):
        with self.assertRaises(ValueError):
            doctor.parse_csv("/no/such/file.csv", AS_OF)

    def test_empty_file(self):
        path = write_csv("")
        self.paths.append(path)
        with self.assertRaises(ValueError):
            doctor.parse_csv(path, AS_OF)

    def test_missing_id_column(self):
        body = "product_id,rating,date\nP-1,5,2026-11-17\n"
        path = write_csv(body)
        self.paths.append(path)
        with self.assertRaises(ValueError) as caught:
            doctor.parse_csv(path, AS_OF)
        self.assertIn("review_id", str(caught.exception))

    def test_missing_product_column(self):
        body = "review_id,rating,date\nR-1,5,2026-11-17\n"
        path = write_csv(body)
        self.paths.append(path)
        with self.assertRaises(ValueError) as caught:
            doctor.parse_csv(path, AS_OF)
        self.assertIn("product_id", str(caught.exception))

    def test_missing_rating_column(self):
        body = "review_id,product_id,date\nR-1,P-1,2026-11-17\n"
        path = write_csv(body)
        self.paths.append(path)
        with self.assertRaises(ValueError) as caught:
            doctor.parse_csv(path, AS_OF)
        self.assertIn("rating", str(caught.exception))

    def test_missing_date_column(self):
        body = "review_id,product_id,rating\nR-1,P-1,5\n"
        path = write_csv(body)
        self.paths.append(path)
        with self.assertRaises(ValueError) as caught:
            doctor.parse_csv(path, AS_OF)
        self.assertIn("date", str(caught.exception))

    def test_extra_columns_ignored(self):
        body = HEADER.replace("\n", ",extra_col\n") + row()[:-1] + ",x\n"
        reviews, findings = self.parse(body)
        self.assertEqual(len(reviews), 1)
        self.assertEqual(findings, [])

    def test_blank_lines_skipped(self):
        reviews, findings = self.parse(HEADER + "\n" + row() + "\n")
        self.assertEqual(len(reviews), 1)
        self.assertEqual(findings, [])

    def test_malformed_row_skipped(self):
        reviews, findings = self.parse(
            HEADER + row() + "R-2,P-1,Widget\n")
        self.assertEqual(len(reviews), 1)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule, "malformed-row")
        self.assertEqual(findings[0].severity, "error")

    def test_duplicate_review_id(self):
        reviews, findings = self.parse(HEADER + row() + row())
        self.assertEqual(len(reviews), 2)
        rules = [item.rule for item in findings]
        self.assertIn("duplicate-review-id", rules)

    def test_missing_review_id(self):
        body = HEADER + row(review_id="")
        reviews, findings = self.parse(body)
        self.assertEqual(reviews[0]["id"], "row 2")
        rules = [item.rule for item in findings]
        self.assertIn("missing-review-id", rules)

    def test_missing_product_id(self):
        reviews, findings = self.parse(HEADER + row(product=""))
        rules = [item.rule for item in findings]
        self.assertIn("missing-product-id", rules)

    def test_invalid_rating(self):
        reviews, findings = self.parse(HEADER + row(rating="six"))
        self.assertIsNone(reviews[0]["rating"])
        self.assertEqual(findings[0].rule, "invalid-rating")

    def test_rating_out_of_range(self):
        reviews, findings = self.parse(HEADER + row(rating="6"))
        self.assertIsNone(reviews[0]["rating"])
        self.assertEqual(findings[0].rule, "invalid-rating")

    def test_invalid_timestamp(self):
        reviews, findings = self.parse(HEADER + row(date="not-a-date"))
        self.assertIsNone(reviews[0]["date"])
        self.assertEqual(findings[0].rule, "invalid-timestamp")

    def test_future_timestamp(self):
        reviews, findings = self.parse(
            HEADER + row(date="2026-12-01 09:00"))
        rules = [item.rule for item in findings]
        self.assertIn("future-timestamp", rules)

    def test_empty_date_is_not_an_error(self):
        reviews, findings = self.parse(HEADER + row(date=""))
        self.assertIsNone(reviews[0]["date"])
        self.assertEqual(findings, [])


class TestAudit(unittest.TestCase):
    def audit(self, body, **kwargs):
        kwargs.setdefault("min_reviews", 1)
        path = write_csv(body)
        try:
            reviews, findings = doctor.parse_csv(path, AS_OF)
        finally:
            os.unlink(path)
        findings.extend(doctor.audit(reviews, AS_OF, **kwargs))
        return reviews, findings

    def rules(self, findings):
        return [item.rule for item in findings]

    def test_unreplied_negative_warning(self):
        _, findings = self.audit(
            HEADER + row(rating="1", date="2026-11-17 09:00"))
        self.assertIn("unreplied-negative", self.rules(findings))
        self.assertNotIn("unreplied-negative-overdue",
                         self.rules(findings))

    def test_unreplied_negative_overdue_error(self):
        _, findings = self.audit(
            HEADER + row(rating="2", date="2026-11-10 09:00"))
        self.assertIn("unreplied-negative-overdue",
                      self.rules(findings))
        self.assertNotIn("unreplied-negative", self.rules(findings))
        error = [item for item in findings
                 if item.rule == "unreplied-negative-overdue"][0]
        self.assertEqual(error.severity, "error")

    def test_reply_days_boundary(self):
        _, findings = self.audit(
            HEADER + row(rating="1", date="2026-11-11 00:00"),
            reply_days=7)
        self.assertIn("unreplied-negative", self.rules(findings))
        _, findings = self.audit(
            HEADER + row(rating="1", date="2026-11-10 23:59"),
            reply_days=7)
        self.assertIn("unreplied-negative-overdue",
                      self.rules(findings))

    def test_replied_negative_is_clean(self):
        _, findings = self.audit(
            HEADER + row(rating="1", date="2026-11-05 09:00",
                         replied="yes"))
        self.assertEqual(findings, [])

    def test_positive_unreplied_is_clean(self):
        _, findings = self.audit(
            HEADER + row(rating="5", date="2026-11-05 09:00"))
        self.assertEqual(findings, [])

    def test_three_star_unreplied_is_clean(self):
        _, findings = self.audit(
            HEADER + row(rating="3", date="2026-11-05 09:00"))
        self.assertEqual(findings, [])

    def test_reply_days_flag(self):
        _, findings = self.audit(
            HEADER + row(rating="1", date="2026-11-17 09:00"),
            reply_days=0)
        self.assertIn("unreplied-negative-overdue",
                      self.rules(findings))

    def test_pending_overdue(self):
        _, findings = self.audit(
            HEADER + row(rating="4", date="2026-11-08 09:00",
                         status="pending"))
        self.assertIn("pending-moderation-overdue",
                      self.rules(findings))

    def test_pending_fresh_is_clean(self):
        _, findings = self.audit(
            HEADER + row(rating="4", date="2026-11-17 09:00",
                         status="pending"))
        self.assertEqual(findings, [])

    def test_pending_does_not_trigger_negative_rules(self):
        _, findings = self.audit(
            HEADER + row(rating="1", date="2026-11-17 09:00",
                         status="pending"))
        self.assertNotIn("unreplied-negative", self.rules(findings))

    def test_spam_review_skipped(self):
        _, findings = self.audit(
            HEADER + row(rating="1", date="2026-11-05 09:00",
                         status="spam"))
        self.assertEqual(findings, [])

    def test_invalid_status(self):
        _, findings = self.audit(HEADER + row(status="weird"))
        self.assertIn("invalid-status", self.rules(findings))

    def test_thin_low_rating(self):
        _, findings = self.audit(HEADER + row(rating="1", text="Bad."))
        self.assertIn("thin-low-rating", self.rules(findings))

    def test_thin_low_rating_empty_text(self):
        _, findings = self.audit(
            HEADER + row(rating="2", text=""))
        self.assertIn("thin-low-rating", self.rules(findings))

    def test_detailed_low_rating_is_not_thin(self):
        _, findings = self.audit(
            HEADER + row(rating="1",
                         text="Arrived torn and the colour is wrong."))
        self.assertNotIn("thin-low-rating", self.rules(findings))

    def test_thin_high_rating_is_not_thin(self):
        _, findings = self.audit(HEADER + row(rating="5", text="Bad."))
        self.assertNotIn("thin-low-rating", self.rules(findings))

    def test_identical_text(self):
        body = (HEADER
                + row(review_id="R-1", text="Great table, solid.")
                + row(review_id="R-2", reviewer="Ben",
                      email="ben@example.com",
                      text="Great table, solid."))
        _, findings = self.audit(body)
        identical = [item for item in findings
                     if item.rule == "identical-text"]
        self.assertEqual(len(identical), 2)

    def test_identical_text_case_and_space_insensitive(self):
        body = (HEADER
                + row(review_id="R-1", text="Great table, solid.")
                + row(review_id="R-2", reviewer="Ben",
                      email="ben@example.com",
                      text="  GREAT   table, solid. "))
        _, findings = self.audit(body)
        self.assertEqual(
            len([item for item in findings
                 if item.rule == "identical-text"]), 2)

    def test_unique_text_is_clean(self):
        body = (HEADER
                + row(review_id="R-1", text="Great table, solid.")
                + row(review_id="R-2", reviewer="Ben",
                      email="ben@example.com",
                      text="Lovely table, very sturdy."))
        _, findings = self.audit(body)
        self.assertNotIn("identical-text", self.rules(findings))

    def test_empty_text_not_identical(self):
        body = (HEADER
                + row(review_id="R-1", rating="2", text="")
                + row(review_id="R-2", reviewer="Ben",
                      email="ben@example.com", rating="2", text=""))
        _, findings = self.audit(body)
        self.assertNotIn("identical-text", self.rules(findings))

    def test_author_burst(self):
        body = HEADER
        for index in range(1, 5):
            body += row(review_id="R-%d" % index,
                        product="P-%d" % index)
        _, findings = self.audit(body)
        burst = [item for item in findings
                 if item.rule == "author-burst"]
        self.assertEqual(len(burst), 4)

    def test_three_reviews_is_not_a_burst(self):
        body = HEADER
        for index in range(1, 4):
            body += row(review_id="R-%d" % index,
                        product="P-%d" % index)
        _, findings = self.audit(body)
        self.assertNotIn("author-burst", self.rules(findings))

    def test_author_burst_case_insensitive_email(self):
        body = HEADER
        for index in range(1, 5):
            body += row(review_id="R-%d" % index,
                        product="P-%d" % index,
                        email="ANA@example.com"
                        if index % 2 else "ana@example.com")
        _, findings = self.audit(body)
        self.assertEqual(
            len([item for item in findings
                 if item.rule == "author-burst"]), 4)

    def test_few_reviews(self):
        _, findings = self.audit(HEADER + row(), min_reviews=5)
        self.assertIn("few-reviews", self.rules(findings))

    def test_enough_reviews_is_clean(self):
        body = HEADER
        for index in range(1, 6):
            body += row(review_id="R-%d" % index,
                        reviewer="Person%d" % index,
                        email="person%d@example.com" % index,
                        text="Review number %d here." % index)
        _, findings = self.audit(body, min_reviews=5)
        self.assertNotIn("few-reviews", self.rules(findings))

    def test_min_reviews_flag(self):
        _, findings = self.audit(HEADER + row(), min_reviews=1)
        self.assertNotIn("few-reviews", self.rules(findings))


class TestSummarize(unittest.TestCase):
    def summarize(self, body, **kwargs):
        path = write_csv(body)
        try:
            reviews, findings = doctor.parse_csv(path, AS_OF)
        finally:
            os.unlink(path)
        findings.extend(doctor.audit(reviews, AS_OF, **kwargs))
        return doctor.summarize(reviews, findings, AS_OF, **kwargs)

    def test_sample_counts(self):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        path = os.path.join(base, "examples", "reviews.csv")
        reviews, findings = doctor.parse_csv(path, AS_OF)
        findings.extend(doctor.audit(reviews, AS_OF))
        summary = doctor.summarize(reviews, findings, AS_OF)
        self.assertEqual(summary["reviews"], 27)
        self.assertEqual(summary["findings"], 44)
        self.assertEqual(summary["errors"], 11)
        self.assertEqual(summary["warnings"], 33)
        self.assertEqual(summary["average_rating"], 3.58)
        self.assertEqual(summary["unreplied_negatives"], 7)
        self.assertEqual(summary["overdue_unreplied_negatives"], 3)
        self.assertEqual(summary["pending_moderation_overdue"], 2)
        self.assertEqual(summary["fake_pattern_findings"], 18)
        self.assertEqual(summary["products_with_few_reviews"], 9)

    def test_per_product_distribution(self):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        path = os.path.join(base, "examples", "reviews.csv")
        reviews, findings = doctor.parse_csv(path, AS_OF)
        findings.extend(doctor.audit(reviews, AS_OF))
        summary = doctor.summarize(reviews, findings, AS_OF)
        by_id = {row["product_id"]: row
                 for row in summary["per_product"]}
        self.assertEqual(by_id["P-201"]["reviews"], 4)
        self.assertEqual(by_id["P-201"]["average_rating"], 2.25)
        self.assertEqual(by_id["P-201"]["distribution"],
                         {"1": 2, "2": 1, "3": 0, "4": 0, "5": 1})
        self.assertEqual(by_id["P-201"]["unreplied_negatives"], 3)
        self.assertEqual(by_id["P-203"]["distribution"],
                         {"1": 3, "2": 0, "3": 0, "4": 0, "5": 0})
        self.assertEqual(len(summary["per_product"]), 9)

    def test_clean_summary(self):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        path = os.path.join(base, "examples", "clean.csv")
        reviews, findings = doctor.parse_csv(path, AS_OF)
        findings.extend(doctor.audit(reviews, AS_OF))
        summary = doctor.summarize(reviews, findings, AS_OF)
        self.assertEqual(summary["reviews"], 5)
        self.assertEqual(summary["findings"], 0)
        self.assertEqual(summary["average_rating"], 4.6)

    def test_lowest_rated_product_helper(self):
        per_product = [
            {"product_id": "P-1", "reviews": 5, "average_rating": 2.0,
             "distribution": {"1": 0, "2": 5, "3": 0, "4": 0, "5": 0}},
            {"product_id": "P-2", "reviews": 4, "average_rating": 1.0,
             "distribution": {"1": 4, "2": 0, "3": 0, "4": 0, "5": 0}},
            {"product_id": "P-3", "reviews": 6, "average_rating": 0.0,
             "distribution": {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}},
            {"product_id": "P-0", "reviews": 5, "average_rating": 2.0,
             "distribution": {"1": 0, "2": 5, "3": 0, "4": 0, "5": 0}}]
        lowest = doctor.lowest_rated_product(per_product, 5)
        self.assertEqual(lowest["product_id"], "P-0")
        lowest = doctor.lowest_rated_product(per_product, 4)
        self.assertEqual(lowest["product_id"], "P-2")
        self.assertIsNone(doctor.lowest_rated_product(per_product, 7))
        self.assertIsNone(doctor.lowest_rated_product([], 0))


class TestOutput(unittest.TestCase):
    def test_text_output_sample(self):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        path = os.path.join(base, "examples", "reviews.csv")
        code, text = run_cli([path, "--as-of", "2026-11-18"])
        self.assertEqual(code, 0)
        self.assertIn("Reviews: 27, findings: 44, errors: 11, "
                      "warnings: 33", text)
        self.assertIn("Average rating: 3.58, unreplied negative "
                      "reviews: 7 (3 overdue)", text)
        self.assertIn("P-201 Wool Throw Blanket: 4 reviews, "
                      "avg 2.25", text)

    def test_json_output(self):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        path = os.path.join(base, "examples", "reviews.csv")
        code, text = run_cli([path, "--as-of", "2026-11-18", "--json"])
        self.assertEqual(code, 0)
        report = json.loads(text)
        self.assertEqual(report["reviews"], 27)
        self.assertEqual(len(report["findings"]), 44)
        self.assertEqual(report["errors"], 11)
        self.assertEqual(len(report["per_product"]), 9)
        self.assertEqual(report["per_product"][0]["product_id"],
                         "P-201")

    def test_out_file(self):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        path = os.path.join(base, "examples", "clean.csv")
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False) as handle:
            out_path = handle.name
        try:
            code, text = run_cli([path, "--as-of", "2026-11-18",
                                  "--out", out_path])
            self.assertEqual(code, 0)
            self.assertEqual(text, "")
            with open(out_path, encoding="utf-8") as handle:
                self.assertIn("All reviews clean.", handle.read())
        finally:
            os.unlink(out_path)

    def test_check_exit_codes(self):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        sample = os.path.join(base, "examples", "reviews.csv")
        clean = os.path.join(base, "examples", "clean.csv")
        warnings_only = os.path.join(base, "examples",
                                     "warnings-only.csv")
        code, _ = run_cli([sample, "--as-of", "2026-11-18", "--check"])
        self.assertEqual(code, 1)
        code, _ = run_cli([clean, "--as-of", "2026-11-18", "--check"])
        self.assertEqual(code, 0)
        code, _ = run_cli([warnings_only, "--as-of", "2026-11-18",
                           "--check"])
        self.assertEqual(code, 0)
        code, _ = run_cli([warnings_only, "--as-of", "2026-11-18",
                           "--check", "--strict"])
        self.assertEqual(code, 1)

    def test_warnings_only_numbers(self):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        path = os.path.join(base, "examples", "warnings-only.csv")
        code, text = run_cli([path, "--as-of", "2026-11-18"])
        self.assertEqual(code, 0)
        self.assertIn("Reviews: 2, findings: 2, errors: 0, "
                      "warnings: 2", text)

    def test_min_reviews_flag_drops_few_reviews(self):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        path = os.path.join(base, "examples", "warnings-only.csv")
        code, text = run_cli([path, "--as-of", "2026-11-18",
                              "--min-reviews", "2"])
        self.assertEqual(code, 0)
        self.assertIn("Reviews: 2, findings: 1, errors: 0, "
                      "warnings: 1", text)

    def test_reply_days_flag_escalates(self):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        path = os.path.join(base, "examples", "warnings-only.csv")
        code, _ = run_cli([path, "--as-of", "2026-11-18",
                           "--reply-days", "0", "--check"])
        self.assertEqual(code, 1)

    def test_lowest_rated_product_line_shown(self):
        body = HEADER
        for number in range(1, 6):
            body += row(review_id="R-%d" % number, product="P-9",
                        name="Bad Kettle", rating="1",
                        email="user%d@example.com" % number,
                        text="Broke on day one, leaked everywhere "
                             "%d." % number,
                        replied="yes")
        body += row(review_id="R-6", product="P-8", name="Good Mug",
                    rating="5", email="other@example.com",
                    replied="yes")
        path = write_csv(body)
        try:
            code, text = run_cli([path, "--as-of", "2026-11-18"])
            _, json_text = run_cli([path, "--as-of", "2026-11-18",
                                    "--json"])
        finally:
            os.unlink(path)
        self.assertEqual(code, 0)
        self.assertIn("Lowest rated product with at least 5 reviews: "
                      "P-9 Bad Kettle, avg 1.00 from 5 reviews\n", text)
        report = json.loads(json_text)
        self.assertNotIn("lowest_rated_product", report)
        self.assertNotIn("Lowest rated product", json_text)

    def test_lowest_rated_product_line_absent_for_sample(self):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        path = os.path.join(base, "examples", "reviews.csv")
        code, text = run_cli([path, "--as-of", "2026-11-18"])
        self.assertEqual(code, 0)
        self.assertNotIn("Lowest rated product", text)

    def test_lowest_rated_product_follows_min_reviews(self):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        path = os.path.join(base, "examples", "reviews.csv")
        code, text = run_cli([path, "--as-of", "2026-11-18",
                              "--min-reviews", "3"])
        self.assertEqual(code, 0)
        self.assertIn("Lowest rated product with at least 3 reviews: "
                      "P-203 Linen Cushion Cover, avg 1.00 from 3 "
                      "reviews\n", text)

    def test_json_keys_unchanged(self):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        path = os.path.join(base, "examples", "clean.csv")
        code, text = run_cli([path, "--as-of", "2026-11-18", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(sorted(json.loads(text)), sorted([
            "reviews", "findings", "errors", "warnings",
            "average_rating", "unreplied_negatives",
            "overdue_unreplied_negatives",
            "pending_moderation_overdue", "fake_pattern_findings",
            "products_with_few_reviews", "per_product"]))

    def test_bad_reply_days(self):
        code, _ = run_cli(["examples/clean.csv", "--reply-days", "-1"])
        self.assertEqual(code, 2)

    def test_bad_min_reviews(self):
        code, _ = run_cli(["examples/clean.csv", "--min-reviews", "-1"])
        self.assertEqual(code, 2)

    def test_bad_as_of(self):
        code, _ = run_cli(["examples/clean.csv", "--as-of", "not-a-date"])
        self.assertEqual(code, 2)

    def test_missing_file_exit(self):
        code, _ = run_cli(["/no/such/file.csv"])
        self.assertEqual(code, 2)

    def test_out_to_bad_path(self):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        path = os.path.join(base, "examples", "clean.csv")
        code, _ = run_cli([path, "--out", "/no/such/dir/out.txt"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()

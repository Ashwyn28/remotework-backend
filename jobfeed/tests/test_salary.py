import unittest

from jobfeed import salary


class FromTextTests(unittest.TestCase):
    def test_reads_posted_ranges(self):
        self.assertEqual(salary.from_text("Salary: £60,000 – £90,000 + bonus"), "£60k – £90k")
        self.assertEqual(salary.from_text("Hybrid Salary: £58,000 to £70,000 DOE"), "£58k – £70k")
        self.assertEqual(salary.from_text("Pay £80k-£100k plus equity"), "£80k – £100k")
        self.assertEqual(salary.from_text("£97,600 - £125,000"), "£98k – £125k")

    def test_reads_a_single_salary_only_when_it_is_pay(self):
        self.assertEqual(salary.from_text("Salary: £45,000 per annum"), "£45k")
        self.assertEqual(salary.from_text("We have 4,000 customers and £50,000 in prizes"), "")

    def test_ignores_funding_and_small_amounts(self):
        self.assertEqual(salary.from_text("We raised £20m – £30m last year"), "")
        self.assertEqual(salary.from_text("Backed by £100 million from investors, salary not listed"), "")
        self.assertEqual(salary.from_text("£500 - £600 per day"), "")
        self.assertEqual(salary.from_text("Salaries from $120,000 to $150,000"), "")


class EstimateTests(unittest.TestCase):
    def test_scales_with_level(self):
        self.assertEqual(salary.estimate("senior", "engineering", "acme", "fintech", "London"), "£85k – £110k")
        self.assertEqual(salary.estimate("junior", "engineering", "acme", "fintech", "London"), "£40k – £55k")

    def test_adjusts_for_employer_and_place(self):
        quant = salary.estimate("senior", "engineering", "jane-street", "fintech", "London")
        outside = salary.estimate("senior", "engineering", "acme", "fintech", "Glasgow, United Kingdom")
        self.assertEqual(quant, "£135k – £175k")
        self.assertEqual(outside, "£70k – £95k")

    def test_unknown_level_counts_as_mid(self):
        self.assertEqual(salary.estimate("", "engineering", "acme", "fintech", "London"), "£65k – £85k")

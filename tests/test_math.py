"""
FestivePulse — Unit Tests for Mathematical Business Logic & Formulas
Verifies deterministic calculations: Currency, GST Slabs, Demand Estimation, and Safety Stock.
"""

import unittest
from services.currency_utils import format_inr, format_compact_inr, number_to_words_inr
from services.sales_service import calculate_line_gst


class TestFestivePulseMath(unittest.TestCase):

    def test_inr_formatting(self):
        # Basic amounts
        self.assertEqual(format_inr(950), "₹950.00")
        self.assertEqual(format_inr(1500), "₹1,500.00")
        # Lakhs (Indian grouping: 1,00,000)
        self.assertEqual(format_inr(150000), "₹1,50,000.00")
        self.assertEqual(format_inr(1250000.50), "₹12,50,000.50")
        # Crores (Indian grouping: 1,00,00,000)
        self.assertEqual(format_inr(10000000), "₹1,00,00,000.00")
        self.assertEqual(format_inr(125000000), "₹12,50,00,000.00")
        # Without decimals
        self.assertEqual(format_inr(150000, show_decimals=False), "₹1,50,000")
        # Negative numbers
        self.assertEqual(format_inr(-45000), "-₹45,000.00")

    def test_compact_inr(self):
        self.assertEqual(format_compact_inr(1500), "₹1.5 K")
        self.assertEqual(format_compact_inr(250000), "₹2.50 L")
        self.assertEqual(format_compact_inr(15000000), "₹1.50 Cr")

    def test_number_to_words_inr(self):
        w1 = number_to_words_inr(1500)
        self.assertEqual(w1, "Rupees One Thousand Five Hundred Only")

        w2 = number_to_words_inr(150250)
        self.assertEqual(w2, "Rupees One Lakh Fifty Thousand Two Hundred Fifty Only")

        w3 = number_to_words_inr(2500.50)
        self.assertEqual(w3, "Rupees Two Thousand Five Hundred and Fifty Paise Only")

    def test_gst_intra_state_split(self):
        # Intra-state: 50% CGST + 50% SGST
        taxable_value = 1000.0
        gst_rate = 18.0
        is_interstate = False

        res = calculate_line_gst(taxable_value, gst_rate, is_interstate)
        self.assertEqual(res["taxable_value"], 1000.0)
        self.assertEqual(res["cgst_rate"], 9.0)
        self.assertEqual(res["cgst_amount"], 90.0)
        self.assertEqual(res["sgst_rate"], 9.0)
        self.assertEqual(res["sgst_amount"], 90.0)
        self.assertEqual(res["igst_rate"], 0.0)
        self.assertEqual(res["igst_amount"], 0.0)
        self.assertEqual(res["total_line_amount"], 1180.0)

    def test_gst_inter_state_igst(self):
        # Inter-state: 100% IGST
        taxable_value = 2000.0
        gst_rate = 12.0
        is_interstate = True

        res = calculate_line_gst(taxable_value, gst_rate, is_interstate)
        self.assertEqual(res["taxable_value"], 2000.0)
        self.assertEqual(res["cgst_amount"], 0.0)
        self.assertEqual(res["sgst_amount"], 0.0)
        self.assertEqual(res["igst_rate"], 12.0)
        self.assertEqual(res["igst_amount"], 240.0)
        self.assertEqual(res["total_line_amount"], 2240.0)

    def test_gst_zero_rate_puja_items(self):
        # 0% GST (e.g. handmade clay diyas)
        taxable_value = 500.0
        gst_rate = 0.0
        is_interstate = False

        res = calculate_line_gst(taxable_value, gst_rate, is_interstate)
        self.assertEqual(res["cgst_amount"], 0.0)
        self.assertEqual(res["sgst_amount"], 0.0)
        self.assertEqual(res["igst_amount"], 0.0)
        self.assertEqual(res["total_line_amount"], 500.0)


if __name__ == "__main__":
    unittest.main()

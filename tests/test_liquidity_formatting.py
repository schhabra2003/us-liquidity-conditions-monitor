"""Tests for the liquidity monitor's canonical number-formatting contract."""

from __future__ import annotations

import math
import unittest

from liquidity_monitor.liquidity_formatting import (
    MISSING_VALUE,
    UNIT_PERCENT,
    UNIT_PERCENTAGE_POINTS,
    UNIT_USD_BILLIONS,
    UNIT_USD_PRICE,
    describe_layer_contribution,
    format_basis_points,
    format_market_price,
    format_percent,
    format_percentage_points,
    format_percentile,
    format_score,
    format_source_value,
    format_usd_billions,
)


class LiquidityFormattingTests(unittest.TestCase):
    def test_missing_values_use_explicit_professional_copy(self) -> None:
        self.assertEqual(MISSING_VALUE, "Not available")

    def test_usd_billions_uses_two_decimals_and_dynamic_scale(self) -> None:
        self.assertEqual(format_usd_billions(2_916.824), "$2.92T")
        self.assertEqual(format_usd_billions(959.435), "$959.44B")
        self.assertEqual(format_usd_billions(0.456), "$456.00M")
        self.assertEqual(format_usd_billions(-1_500), "−$1.50T")
        self.assertEqual(format_usd_billions(2, signed=True), "+$2.00B")

    def test_rates_spreads_prices_and_basis_points_use_fixed_precision(self) -> None:
        self.assertEqual(format_basis_points(16.335, signed=True), "+16.3 bp")
        self.assertEqual(format_basis_points(-7.678, signed=True), "−7.7 bp")
        self.assertEqual(format_percent(3.645), "3.65%")
        self.assertEqual(format_percentage_points(1.61), "1.61 pp")
        self.assertEqual(format_market_price(771.1), "$771.10")

    def test_scores_and_percentiles_use_integer_display(self) -> None:
        self.assertEqual(format_score(39.5833), "40 / 100")
        self.assertEqual(format_score(120), "100 / 100")
        self.assertEqual(format_percentile(1), "1st percentile")
        self.assertEqual(format_percentile(2), "2nd percentile")
        self.assertEqual(format_percentile(3), "3rd percentile")
        self.assertEqual(format_percentile(11), "11th percentile")

    def test_non_finite_values_fail_to_one_missing_value(self) -> None:
        for value in (None, math.nan, math.inf, -math.inf, "not-a-number"):
            with self.subTest(value=value):
                self.assertEqual(format_usd_billions(value), MISSING_VALUE)
                self.assertEqual(format_basis_points(value), MISSING_VALUE)

    def test_weakest_layer_copy_is_sign_aware(self) -> None:
        negative = describe_layer_contribution("Reserve capacity", -0.68)
        self.assertEqual(negative[0], "Primary model drag")
        self.assertIn("primary drag", negative[1])
        self.assertIn("largest negative contribution", negative[2])

        positive = describe_layer_contribution("Bank credit", 0.02)
        self.assertEqual(positive[0], "Smallest positive model layer")
        self.assertIn("All four model layers are supportive", positive[1])
        self.assertIn("smallest positive contribution", positive[2])

        neutral = describe_layer_contribution("Funding support", -0.001)
        self.assertEqual(neutral[0], "Least supportive model layer")
        self.assertIn("neutral", neutral[1])
        self.assertIn("neutral contribution", neutral[2])

        unavailable = describe_layer_contribution("Funding support", math.nan)
        self.assertIn("not available", unavailable[2])

    def test_source_formatter_uses_the_same_contract(self) -> None:
        self.assertEqual(format_source_value(1_250, UNIT_USD_BILLIONS), "$1.25T")
        self.assertEqual(format_source_value(3.64, UNIT_PERCENT), "3.64%")
        self.assertEqual(format_source_value(1.61, UNIT_PERCENTAGE_POINTS), "1.61 pp")
        self.assertEqual(format_source_value(771.1, UNIT_USD_PRICE), "$771.10")


if __name__ == "__main__":
    unittest.main()

"""Focused release-clock regressions for the live liquidity snapshot."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

import pandas as pd

from liquidity_monitor.liquidity_live_snapshot import (
    apply_federal_reserve_release_availability,
    expected_observation_date,
    load_federal_reserve_release_calendars,
    load_live_snapshot,
    runtime_expected_dates,
    snapshot_is_current,
    source_current_mask,
)
from liquidity_monitor.liquidity_signal_monitor import live_source_status_table
from scripts.refresh_liquidity_live_snapshot import (
    download_adjusted_close,
    matched_admin_spread_bp,
)
from scripts.refresh_liquidity_live_snapshot import (
    expected_observation_date as refresh_expected_observation_date,
)

ROOT = Path(__file__).resolve().parents[1]
LIVE_ROOT = ROOT / "data" / "liquidity_live_snapshot"


class LiquidityFreshnessClockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = load_live_snapshot(LIVE_ROOT, verify_hashes=True)

    def _pre_publication_onrrp_snapshot(self):
        """Return a deterministic Sep. 3 ON RRP package for Sep. 4 clock tests."""

        sources = (
            self.snapshot.sources.loc[self.snapshot.sources["field"].eq("onrrp_bn")]
            .copy(deep=True)
            .reset_index(drop=True)
        )
        onrrp = sources["field"].eq("onrrp_bn")
        sources.loc[onrrp, "value"] = 0.702
        sources.loc[onrrp, "observation_date"] = "2026-09-03"
        sources.loc[onrrp, "expected_observation_date"] = "2026-09-03"
        sources.loc[onrrp, "verified_through"] = "2026-09-04"
        sources.loc[onrrp, "status"] = "CURRENT_PUBLICATION_LAG"
        sources.loc[onrrp, "status_detail"] = (
            "Current under the latest completed New York Fed operation"
        )
        manifest = dict(self.snapshot.manifest)
        manifest.update(
            {
                "as_of_et": "2026-09-04T12:27:35-04:00",
                "information_cutoff_et": "2026-09-04T12:27:35-04:00",
                "all_sources_current": True,
            }
        )
        return replace(self.snapshot, manifest=manifest, sources=sources)

    def test_current_release_is_hash_verified_at_its_own_cutoff(self) -> None:
        self.assertEqual(
            self.snapshot.manifest["release_id"], "US-LIQ-LIVE-2026-09-04"
        )
        self.assertEqual(len(self.snapshot.sources), 28)
        self.assertEqual(len(self.snapshot.manifest["raw_files"]), 33)
        release_clock = pd.Timestamp(self.snapshot.manifest["as_of_et"])
        self.assertEqual(release_clock.date().isoformat(), "2026-09-04")
        self.assertTrue(
            snapshot_is_current(
                self.snapshot, now=release_clock + pd.Timedelta(minutes=1)
            )
        )

    def test_on_rrp_ages_after_runtime_publication_checkpoint(self) -> None:
        snapshot = self._pre_publication_onrrp_snapshot()
        before = pd.Timestamp("2026-09-04 13:59:59", tz="America/New_York")
        after = pd.Timestamp("2026-09-04 14:00:00", tz="America/New_York")

        before_mask = source_current_mask(snapshot, now=before)
        after_mask = source_current_mask(snapshot, now=after)

        self.assertTrue(bool(snapshot.manifest["all_sources_current"]))
        self.assertTrue(before_mask.all())
        self.assertEqual(
            snapshot.sources.loc[~after_mask, "field"].tolist(), ["onrrp_bn"]
        )
        self.assertTrue(snapshot_is_current(snapshot, now=before))
        self.assertFalse(snapshot_is_current(snapshot, now=after))

        before_expected = runtime_expected_dates(snapshot, now=before)
        after_expected = runtime_expected_dates(snapshot, now=after)
        onrrp_index = snapshot.sources.index[snapshot.sources["field"].eq("onrrp_bn")][
            0
        ]
        self.assertEqual(
            before_expected.loc[onrrp_index].date().isoformat(), "2026-09-03"
        )
        self.assertEqual(
            after_expected.loc[onrrp_index].date().isoformat(), "2026-09-04"
        )

    def test_runtime_status_explains_point_in_time_manifest_transition(self) -> None:
        snapshot = self._pre_publication_onrrp_snapshot()
        after = pd.Timestamp("2026-09-04 14:00:00", tz="America/New_York")
        status = live_source_status_table(snapshot, current_time=after)
        onrrp = status.loc[status["Series"].eq("Overnight reverse repo")].iloc[0]

        self.assertEqual(onrrp["Live status"], "STALE · REFRESH REQUIRED")
        self.assertEqual(str(onrrp["Observation date"]), "2026-09-03")
        self.assertEqual(str(onrrp["Expected date"]), "2026-09-04")
        self.assertIn("Packaged observation 2026-09-03", onrrp["Status detail"])
        self.assertIn(
            str(snapshot.manifest["information_cutoff_et"]),
            onrrp["Status detail"],
        )
        self.assertIn("2:00 p.m. ET publication checkpoint", onrrp["Status detail"])

    def test_on_rrp_checkpoint_is_timezone_stable(self) -> None:
        eastern = pd.Timestamp("2026-09-04 14:00:00", tz="America/New_York")
        utc = pd.Timestamp("2026-09-04 18:00:00", tz="UTC")

        eastern_date, eastern_rule = expected_observation_date("onrrp_bn", eastern)
        utc_date, utc_rule = expected_observation_date("onrrp_bn", utc)

        self.assertEqual(eastern_date, utc_date)
        self.assertEqual(eastern_rule, utc_rule)
        self.assertEqual(eastern_date.date().isoformat(), "2026-09-04")

    def test_on_rrp_weekend_expectation_stays_on_friday(self) -> None:
        saturday = pd.Timestamp("2026-09-05 16:00:00", tz="America/New_York")
        expected, _ = expected_observation_date("onrrp_bn", saturday)
        self.assertEqual(expected.date().isoformat(), "2026-09-04")

    def test_weekly_and_market_cutoffs_are_exact(self) -> None:
        cases = (
            ("assets_bn", "2026-09-03 16:29:59", "2026-08-26"),
            ("assets_bn", "2026-09-03 16:30:00", "2026-09-02"),
            ("deposits_bn", "2026-09-04 16:14:59", "2026-08-19"),
            ("deposits_bn", "2026-09-04 16:15:00", "2026-08-26"),
            ("market", "2026-09-04 16:29:59", "2026-09-03"),
            ("market", "2026-09-04 16:30:00", "2026-09-04"),
        )
        for field, stamp, expected_date in cases:
            with self.subTest(field=field, stamp=stamp):
                observed, _ = expected_observation_date(
                    field,
                    pd.Timestamp(stamp, tz="America/New_York"),
                )
                self.assertEqual(observed.date().isoformat(), expected_date)

    def test_daily_source_cutoff_is_exact_for_every_grouped_field(self) -> None:
        daily_fields = (
            "tga_dts_bn",
            "hy_oas",
            "ig_oas",
            "real_yield_10y",
        )
        before = pd.Timestamp("2026-09-04 16:59:59", tz="America/New_York")
        after = pd.Timestamp("2026-09-04 17:00:00", tz="America/New_York")
        for field in daily_fields:
            with self.subTest(field=field):
                before_date, before_rule = expected_observation_date(field, before)
                after_date, after_rule = expected_observation_date(field, after)
                self.assertEqual(before_date.date().isoformat(), "2026-09-02")
                self.assertEqual(after_date.date().isoformat(), "2026-09-03")
                self.assertEqual(before_rule, after_rule)

    def test_total_repo_operations_use_a_same_day_publication_clock(self) -> None:
        before = pd.Timestamp("2026-09-04 14:29:59", tz="America/New_York")
        after = pd.Timestamp("2026-09-04 14:30:00", tz="America/New_York")
        before_date, before_rule = expected_observation_date("repo_add_bn", before)
        after_date, after_rule = expected_observation_date("repo_add_bn", after)
        self.assertEqual(before_date.date().isoformat(), "2026-09-03")
        self.assertEqual(after_date.date().isoformat(), "2026-09-04")
        self.assertEqual(before_rule, after_rule)
        self.assertIn("total Federal Reserve overnight repo", after_rule)

    def test_baa10y_cutoff_tracks_its_later_fred_publication(self) -> None:
        cases = (
            ("2026-09-04 17:00:00", "2026-09-02"),
            ("2026-09-04 17:14:59", "2026-09-02"),
            ("2026-09-04 17:15:00", "2026-09-03"),
        )
        for stamp, expected_date in cases:
            with self.subTest(stamp=stamp):
                observed, rule = expected_observation_date(
                    "baa10y", pd.Timestamp(stamp, tz="America/New_York")
                )
                self.assertEqual(observed.date().isoformat(), expected_date)
                self.assertIn("5:15 p.m. ET checkpoint", rule)

    def test_snapshot_builder_and_runtime_share_one_clock_function(self) -> None:
        self.assertIs(refresh_expected_observation_date, expected_observation_date)

    def test_admin_spread_uses_reference_rate_effective_date(self) -> None:
        reference_rate = pd.Series(
            [4.01], index=pd.to_datetime(["2026-09-16"]), dtype=float
        )
        iorb = pd.Series(
            [4.00, 3.75],
            index=pd.to_datetime(["2026-09-16", "2026-09-17"]),
            dtype=float,
        )

        matched = matched_admin_spread_bp(reference_rate, iorb)
        naive_mismatched = (float(reference_rate.iloc[-1]) - float(iorb.iloc[-1])) * 100

        self.assertAlmostEqual(matched, 1.0)
        self.assertAlmostEqual(naive_mismatched, 26.0)

    def test_labor_day_clocks_do_not_require_nonexistent_observations(self) -> None:
        holiday = pd.Timestamp("2026-09-07 14:00:00", tz="America/New_York")
        tuesday_before = pd.Timestamp(
            "2026-09-08 07:59:59", tz="America/New_York"
        )
        tuesday_after = pd.Timestamp(
            "2026-09-08 08:00:00", tz="America/New_York"
        )

        self.assertEqual(
            expected_observation_date("onrrp_bn", holiday)[0].date().isoformat(),
            "2026-09-04",
        )
        self.assertEqual(
            expected_observation_date("market", holiday)[0].date().isoformat(),
            "2026-09-04",
        )
        for field in ("sofr", "tgcr", "bgcr"):
            with self.subTest(field=field):
                self.assertEqual(
                    expected_observation_date(field, holiday)[0].date().isoformat(),
                    "2026-09-03",
                )
                self.assertEqual(
                    expected_observation_date(field, tuesday_before)[0]
                    .date()
                    .isoformat(),
                    "2026-09-03",
                )
                self.assertEqual(
                    expected_observation_date(field, tuesday_after)[0]
                    .date()
                    .isoformat(),
                    "2026-09-04",
                )

    def test_government_securities_calendar_does_not_close_for_saturday_veterans_day(self) -> None:
        friday_after = pd.Timestamp(
            "2023-11-10 08:00:00", tz="America/New_York"
        )
        monday_after = pd.Timestamp(
            "2023-11-13 08:00:00", tz="America/New_York"
        )
        for field in ("sofr", "tgcr", "bgcr"):
            with self.subTest(field=field):
                self.assertEqual(
                    expected_observation_date(field, friday_after)[0]
                    .date()
                    .isoformat(),
                    "2023-11-09",
                )
                self.assertEqual(
                    expected_observation_date(field, monday_after)[0]
                    .date()
                    .isoformat(),
                    "2023-11-10",
                )

    def test_official_h41_and_h8_release_calendars_cover_delayed_archives(self) -> None:
        calendars = load_federal_reserve_release_calendars(LIVE_ROOT)
        h41_values = pd.Series(
            [1.0, 2.0],
            index=pd.to_datetime(["2020-12-23", "2025-12-24"]),
        )
        h8_values = pd.Series(
            [1.0, 2.0, 3.0, 4.0],
            index=pd.to_datetime(
                ["2020-12-09", "2020-12-16", "2021-06-09", "2025-12-17"]
            ),
        )
        h41_available = apply_federal_reserve_release_availability(
            h41_values, "h41", calendars["h41"]
        )
        h8_available = apply_federal_reserve_release_availability(
            h8_values, "h8", calendars["h8"]
        )
        self.assertEqual(
            [date.date().isoformat() for date in h41_available.index],
            ["2020-12-28", "2025-12-29"],
        )
        self.assertEqual(
            [date.date().isoformat() for date in h8_available.index],
            ["2020-12-18", "2020-12-28", "2021-06-21", "2025-12-29"],
        )

    def test_official_h10_clock_uses_last_business_day_of_prior_week(self) -> None:
        calendars = load_federal_reserve_release_calendars(LIVE_ROOT)
        cases = (
            ("2026-08-31 16:15:00", "2026-08-28"),
            ("2026-06-22 16:15:00", "2026-06-18"),
            ("2026-07-06 16:15:00", "2026-07-02"),
            ("2023-11-13 16:15:00", "2023-11-09"),
        )
        for timestamp, expected_date in cases:
            with self.subTest(timestamp=timestamp):
                observed, rule = expected_observation_date(
                    "broad_usd",
                    pd.Timestamp(timestamp, tz="America/New_York"),
                    release_calendars=calendars,
                )
                self.assertEqual(observed.date().isoformat(), expected_date)
                self.assertIn("official H.10", rule)

    def test_h10_supplemental_releases_are_not_forced_into_one_to_one_mapping(self) -> None:
        calendars = load_federal_reserve_release_calendars(LIVE_ROOT)
        self.assertIn(pd.Timestamp("2026-08-10"), calendars["h10"])
        self.assertIn(pd.Timestamp("2026-08-12"), calendars["h10"])
        values = pd.Series([1.0], index=pd.to_datetime(["2026-08-07"]))
        with self.assertRaisesRegex(ValueError, "H41 and H8 only"):
            apply_federal_reserve_release_availability(
                values, "h10", calendars["h10"]
            )

    def test_h8_friday_holiday_release_is_recognized_on_thursday(self) -> None:
        before = pd.Timestamp("2026-07-02 16:14:59", tz="America/New_York")
        after = pd.Timestamp("2026-07-02 16:15:00", tz="America/New_York")
        self.assertEqual(
            expected_observation_date("bank_assets_bn", before)[0]
            .date()
            .isoformat(),
            "2026-06-17",
        )
        self.assertEqual(
            expected_observation_date("bank_assets_bn", after)[0]
            .date()
            .isoformat(),
            "2026-06-24",
        )

    def test_h41_thanksgiving_release_is_deferred_to_friday(self) -> None:
        thursday = pd.Timestamp("2026-11-26 17:00:00", tz="America/New_York")
        friday_before = pd.Timestamp(
            "2026-11-27 16:29:59", tz="America/New_York"
        )
        friday_after = pd.Timestamp(
            "2026-11-27 16:30:00", tz="America/New_York"
        )
        for timestamp, expected in (
            (thursday, "2026-11-18"),
            (friday_before, "2026-11-18"),
            (friday_after, "2026-11-25"),
        ):
            with self.subTest(timestamp=timestamp):
                self.assertEqual(
                    expected_observation_date("assets_bn", timestamp)[0]
                    .date()
                    .isoformat(),
                    expected,
                )

    def test_fedwire_month_end_becomes_available_after_exactly_25_days(self) -> None:
        before = pd.Timestamp("2026-08-24 23:59:59", tz="America/New_York")
        at_lag = pd.Timestamp("2026-08-25 00:00:00", tz="America/New_York")
        self.assertEqual(
            expected_observation_date("fedwire_daily_value_bn", before)[0],
            pd.Timestamp("2026-06-30"),
        )
        self.assertEqual(
            expected_observation_date("fedwire_daily_value_bn", at_lag)[0],
            pd.Timestamp("2026-07-31"),
        )

    def test_fedwire_25_day_lag_handles_short_february(self) -> None:
        before = pd.Timestamp("2026-03-24 23:59:59", tz="America/New_York")
        at_lag = pd.Timestamp("2026-03-25 00:00:00", tz="America/New_York")
        self.assertEqual(
            expected_observation_date("fedwire_daily_value_bn", before)[0],
            pd.Timestamp("2026-01-31"),
        )
        self.assertEqual(
            expected_observation_date("fedwire_daily_value_bn", at_lag)[0],
            pd.Timestamp("2026-02-28"),
        )

    def test_future_dated_source_is_not_current_at_package_or_runtime(self) -> None:
        sources = self.snapshot.sources.copy(deep=True)
        sources.loc[sources.index[0], "observation_date"] = "2026-09-10"
        sources.loc[sources.index[0], "verified_through"] = "2026-09-10"
        synthetic = replace(self.snapshot, sources=sources)
        release_clock = pd.Timestamp(self.snapshot.manifest["as_of_et"])

        self.assertFalse(bool(source_current_mask(synthetic, now=release_clock).all()))
        self.assertFalse(snapshot_is_current(synthetic, now=release_clock))

    def test_loader_rejects_future_dated_and_backdated_clock_ledgers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "live"
            shutil.copytree(LIVE_ROOT, target)

            sources = pd.read_csv(target / "source_status.csv")
            sources.loc[sources.index[0], "observation_date"] = "2026-09-10"
            sources.loc[sources.index[0], "verified_through"] = "2026-09-10"
            sources.to_csv(target / "source_status.csv", index=False)
            manifest = json.loads((target / "manifest.json").read_text())
            manifest["files"]["source_status.csv"]["sha256"] = hashlib.sha256(
                (target / "source_status.csv").read_bytes()
            ).hexdigest()
            (target / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "future-dated"):
                load_live_snapshot(target, verify_hashes=True)

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "live"
            shutil.copytree(LIVE_ROOT, target)

            sources = pd.read_csv(target / "source_status.csv")
            sources.loc[sources.index[0], "expected_observation_date"] = "2026-01-01"
            sources.to_csv(target / "source_status.csv", index=False)
            manifest = json.loads((target / "manifest.json").read_text())
            manifest["files"]["source_status.csv"]["sha256"] = hashlib.sha256(
                (target / "source_status.csv").read_bytes()
            ).hexdigest()
            (target / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "source clock"):
                load_live_snapshot(target, verify_hashes=True)

    def test_market_download_recovers_a_missing_batch_symbol(self) -> None:
        dates = pd.to_datetime(["2026-09-03", "2026-09-04"])
        batch = pd.DataFrame(
            [[100.0], [101.0]],
            index=dates,
            columns=pd.MultiIndex.from_tuples([("Adj Close", "AAA")]),
        )
        single = pd.DataFrame({"Adj Close": [50.0, 51.0]}, index=dates)

        def fake_download(symbols, **_kwargs):
            return batch if isinstance(symbols, list) else single

        with mock.patch(
            "scripts.refresh_liquidity_live_snapshot.yf.download",
            side_effect=fake_download,
        ):
            frame = download_adjusted_close(
                ["AAA", "BBB"],
                start="2026-09-01",
                end="2026-09-05",
                attempts=1,
            )

        self.assertEqual(list(frame.columns), ["AAA", "BBB"])
        self.assertAlmostEqual(float(frame.loc[dates[-1], "AAA"]), 101.0)
        self.assertAlmostEqual(float(frame.loc[dates[-1], "BBB"]), 51.0)


if __name__ == "__main__":
    unittest.main()

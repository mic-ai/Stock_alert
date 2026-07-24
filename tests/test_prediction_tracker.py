import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import pytest
from prediction_tracker import (
    PREDICTION_COLUMNS,
    load_predictions,
    compute_eval_due_date,
    build_prediction_rows,
    append_predictions,
    judge_hit,
    mark_due_predictions_evaluated,
    aggregate_hit_rate,
)


class TestLoadPredictions:
    def test_missing_file_returns_empty_df(self, tmp_path):
        df = load_predictions(str(tmp_path / "nope.csv"))
        assert df.empty
        assert list(df.columns) == PREDICTION_COLUMNS

    def test_header_only_file_returns_empty_df(self, tmp_path):
        path = tmp_path / "predictions.csv"
        path.write_text(",".join(PREDICTION_COLUMNS) + "\n")
        df = load_predictions(str(path))
        assert df.empty


class TestComputeEvalDueDate:
    def test_friday_plus_5_business_days_lands_next_friday(self):
        # 2026-07-24 is a Friday
        assert compute_eval_due_date("2026-07-24", 5) == "2026-07-31"

    def test_n_equals_1(self):
        # 2026-07-24 is a Friday -> +1 business day is Monday
        assert compute_eval_due_date("2026-07-24", 1) == "2026-07-27"


class TestJudgeHit:
    def test_buy_exact_boundary_is_hit(self):
        assert judge_hit("buy", 100.0, 102.0, 0.02, 0.02) == "hit"

    def test_buy_just_below_boundary_is_miss(self):
        assert judge_hit("buy", 100.0, 101.99, 0.02, 0.02) == "miss"

    def test_sell_exact_boundary_is_hit(self):
        assert judge_hit("sell", 100.0, 98.0, 0.02, 0.02) == "hit"

    def test_sell_just_above_boundary_is_miss(self):
        assert judge_hit("sell", 100.0, 98.01, 0.02, 0.02) == "miss"

    def test_unknown_signal_type_raises(self):
        with pytest.raises(ValueError):
            judge_hit("hold", 100.0, 100.0, 0.02, 0.02)


class TestBuildAndAppendPredictions:
    def test_build_prediction_rows_basic(self):
        candidates = [{"ticker": "NVDA", "close": 120.5}]
        rows = build_prediction_rows(candidates, "buy", "2026-07-24", 5)
        assert len(rows) == 1
        assert rows.iloc[0]["prediction_id"] == "2026-07-24_NVDA_buy"
        assert rows.iloc[0]["basis_price"] == 120.5
        assert rows.iloc[0]["eval_due_date"] == "2026-07-31"
        assert rows.iloc[0]["status"] == "pending"

    def test_build_prediction_rows_empty_candidates(self):
        rows = build_prediction_rows([], "buy", "2026-07-24", 5)
        assert rows.empty
        assert list(rows.columns) == PREDICTION_COLUMNS

    def test_append_predictions_dedups_by_prediction_id(self):
        existing = pd.DataFrame(columns=PREDICTION_COLUMNS)
        first_rows = build_prediction_rows([{"ticker": "NVDA", "close": 100.0}], "buy", "2026-07-24", 5)
        merged, n_skipped = append_predictions(existing, first_rows)
        assert len(merged) == 1
        assert n_skipped == 0

        # 同一日同一銘柄で再実行（basis_priceが変わっても既存行は上書きされない）
        rerun_rows = build_prediction_rows([{"ticker": "NVDA", "close": 999.0}], "buy", "2026-07-24", 5)
        merged, n_skipped = append_predictions(merged, rerun_rows)
        assert len(merged) == 1
        assert n_skipped == 1
        assert merged.iloc[0]["basis_price"] == 100.0

    def test_append_predictions_empty_new_rows(self):
        existing = pd.DataFrame(columns=PREDICTION_COLUMNS)
        empty_rows = pd.DataFrame(columns=PREDICTION_COLUMNS)
        merged, n_skipped = append_predictions(existing, empty_rows)
        assert merged.empty
        assert n_skipped == 0


class TestMarkDuePredictionsEvaluated:
    def _make_df(self):
        return pd.DataFrame([
            {
                "prediction_id": "2026-07-01_NVDA_buy", "date": "2026-07-01", "ticker": "NVDA",
                "signal_type": "buy", "basis_price": 100.0, "eval_due_date": "2026-07-08",
                "eval_price": None, "result": None, "status": "pending",
            },
            {
                "prediction_id": "2026-07-01_AMD_sell", "date": "2026-07-01", "ticker": "AMD",
                "signal_type": "sell", "basis_price": 200.0, "eval_due_date": "2026-07-08",
                "eval_price": None, "result": None, "status": "pending",
            },
            {
                "prediction_id": "2026-07-20_MU_buy", "date": "2026-07-20", "ticker": "MU",
                "signal_type": "buy", "basis_price": 50.0, "eval_due_date": "2026-07-27",
                "eval_price": None, "result": None, "status": "pending",
            },
        ])

    def test_not_yet_due_rows_untouched(self):
        df = self._make_df()
        updated = mark_due_predictions_evaluated(df, {"NVDA": 105.0, "AMD": 190.0}, "2026-07-08", 0.02, 0.02)
        mu_row = updated[updated["ticker"] == "MU"].iloc[0]
        assert mu_row["status"] == "pending"

    def test_hit_and_miss_and_unavailable(self):
        df = self._make_df()
        updated = mark_due_predictions_evaluated(
            df, {"NVDA": 105.0, "AMD": None}, "2026-07-08", 0.02, 0.02
        )
        nvda_row = updated[updated["ticker"] == "NVDA"].iloc[0]
        assert nvda_row["status"] == "evaluated"
        assert nvda_row["result"] == "hit"
        assert nvda_row["eval_price"] == 105.0

        amd_row = updated[updated["ticker"] == "AMD"].iloc[0]
        assert amd_row["status"] == "unavailable"
        assert pd.isna(amd_row["eval_price"])

    def test_idempotent_rerun_does_not_change_already_evaluated_rows(self):
        df = self._make_df()
        first = mark_due_predictions_evaluated(df, {"NVDA": 105.0, "AMD": None}, "2026-07-08", 0.02, 0.02)
        # 別の価格を渡して再実行しても、既にevaluated/unavailableの行は変化しない
        second = mark_due_predictions_evaluated(first, {"NVDA": 999.0, "AMD": 999.0}, "2026-07-08", 0.02, 0.02)
        pd.testing.assert_frame_equal(first, second)

    def test_date_and_basis_price_never_modified(self):
        df = self._make_df()
        updated = mark_due_predictions_evaluated(df, {"NVDA": 105.0, "AMD": None}, "2026-07-08", 0.02, 0.02)
        assert updated[updated["ticker"] == "NVDA"].iloc[0]["basis_price"] == 100.0
        assert updated[updated["ticker"] == "NVDA"].iloc[0]["date"] == "2026-07-01"


class TestAggregateHitRate:
    def _make_evaluated_df(self):
        rows = []
        for i, result in enumerate(["hit", "hit", "miss", "hit", "miss"]):
            rows.append({
                "prediction_id": f"p{i}", "date": f"2026-07-{i+1:02d}", "ticker": "X",
                "signal_type": "buy", "basis_price": 100.0, "eval_due_date": f"2026-07-{i+8:02d}",
                "eval_price": 100.0, "result": result, "status": "evaluated",
            })
        rows.append({
            "prediction_id": "sell1", "date": "2026-07-01", "ticker": "Y",
            "signal_type": "sell", "basis_price": 100.0, "eval_due_date": "2026-07-08",
            "eval_price": None, "result": None, "status": "pending",
        })
        return pd.DataFrame(rows)

    def test_zero_evaluated_returns_none_hit_rate(self):
        df = pd.DataFrame(columns=PREDICTION_COLUMNS)
        agg = aggregate_hit_rate(df, "buy", "count", 30, "2026-07-24")
        assert agg == {"hit_count": 0, "miss_count": 0, "total": 0, "hit_rate": None}

    def test_pending_and_unavailable_excluded(self):
        df = self._make_evaluated_df()
        agg = aggregate_hit_rate(df, "sell", "count", 30, "2026-07-24")
        assert agg["total"] == 0
        assert agg["hit_rate"] is None

    def test_count_window(self):
        df = self._make_evaluated_df()
        agg = aggregate_hit_rate(df, "buy", "count", 3, "2026-07-24")
        # 直近3件: miss, hit, miss -> 1/3
        assert agg["total"] == 3
        assert agg["hit_count"] == 1
        assert agg["hit_rate"] == pytest.approx(1 / 3)

    def test_count_window_larger_than_available_rows(self):
        df = self._make_evaluated_df()
        agg = aggregate_hit_rate(df, "buy", "count", 100, "2026-07-24")
        assert agg["total"] == 5
        assert agg["hit_count"] == 3

    def test_invalid_window_mode_raises(self):
        df = pd.DataFrame(columns=PREDICTION_COLUMNS)
        with pytest.raises(ValueError):
            aggregate_hit_rate(df, "buy", "weeks", 30, "2026-07-24")

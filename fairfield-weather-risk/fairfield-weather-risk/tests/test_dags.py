"""Checks that the DAG files load and are wired up as intended.

Skipped when Airflow is not installed, so the other tests can run without it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("airflow")

from airflow.models import DagBag  # noqa: E402

DAGS_DIR = Path(__file__).resolve().parents[1] / "dags"


@pytest.fixture(scope="module")
def dagbag() -> DagBag:
    return DagBag(dag_folder=str(DAGS_DIR))


def test_all_dag_files_import_without_errors(dagbag):
    assert dagbag.import_errors == {}
    assert set(dagbag.dag_ids) == {"fairfield_weather_daily", "fairfield_weather_backfill"}


def test_daily_dag_settings(dagbag):
    dag = dagbag.dags["fairfield_weather_daily"]
    assert dag.catchup is False and dag.max_active_runs == 1
    assert dag.timezone.name == "Africa/Johannesburg"
    assert "target_date" in dag.params
    assert dag.default_args["retries"] == 3


def test_daily_dag_tasks_run_in_the_intended_order(dagbag):
    dag = dagbag.dags["fairfield_weather_daily"]
    downstream = {task.task_id: set(task.downstream_task_ids) for task in dag.tasks}
    assert downstream == {
        "plan_run": {"extract_observed", "transform_observed", "forecast_is_current",
                     "extract_forecast", "transform_forecast", "quality_checks"},
        "extract_observed": {"transform_observed"},
        "transform_observed": {"quality_checks"},
        "forecast_is_current": {"extract_forecast"},
        "extract_forecast": {"transform_forecast"},
        "transform_forecast": {"quality_checks"},
        "quality_checks": set(),
    }


def test_quality_checks_still_run_when_the_forecast_is_skipped(dagbag):
    checks = dagbag.dags["fairfield_weather_daily"].get_task("quality_checks")
    assert str(checks.trigger_rule).lower().endswith("none_failed")
    assert checks.retries == 0


def test_backfill_dag_is_manual_only(dagbag):
    dag = dagbag.dags["fairfield_weather_backfill"]
    assert dag.catchup is False
    assert {"start_date", "end_date"} <= set(dag.params)
    assert [task.task_id for task in dag.tasks] == ["load_history"]

"""Fairfield weather risk pipeline.

The package has no dependency on Airflow. The DAGs in the dags folder are a
thin layer that calls the functions in fairfield_weather.pipeline, so the same
code can be run from the command line and from tests.
"""

__version__ = "1.0.0"

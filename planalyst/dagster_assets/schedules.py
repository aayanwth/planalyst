"""
PLanalyst — Dagster: Schedules

  daily   07:00 UTC  news ingestion (RSS only exposes recent items, so skipping days loses articles)
  weekly  Mon 09:00  full matchweek pipeline, after the weekend's fixtures
  monthly 1st 06:00  model retraining

All run only while a Dagster daemon is up (`dagster dev` or a deployed daemon).
"""

from dagster import DefaultScheduleStatus, ScheduleDefinition

from planalyst.dagster_assets.jobs import matchweek_pipeline, model_training_job, news_ingestion_job

daily_news_schedule = ScheduleDefinition(
    job=news_ingestion_job,
    cron_schedule="0 7 * * *",
    execution_timezone="UTC",
    default_status=DefaultScheduleStatus.RUNNING,
)

weekly_matchweek_schedule = ScheduleDefinition(
    job=matchweek_pipeline,
    cron_schedule="0 9 * * 1",
    execution_timezone="UTC",
    default_status=DefaultScheduleStatus.RUNNING,
)

monthly_training_schedule = ScheduleDefinition(
    job=model_training_job,
    cron_schedule="0 6 1 * *",
    execution_timezone="UTC",
    default_status=DefaultScheduleStatus.RUNNING,
)

all_schedules = [daily_news_schedule, weekly_matchweek_schedule, monthly_training_schedule]

"""Run GE suites and demonstrate fail-fast on an intentionally broken check."""
import sys

from planalyst.quality.match_expectations import validate_matches
from planalyst.quality.news_expectations import validate_news

print("=== Task 3: Great Expectations (happy path) ===")
validate_matches(fail_fast=True)
validate_news(fail_fast=True)

print("\n=== Task 3 checkpoint: intentional fail-fast ===")
print("Forcing row-count max=1 on bronze.raw_matches (380 rows) to prove halt...")

from great_expectations.expectations import ExpectTableRowCountToBeBetween
from planalyst.quality.ge_config import get_context, get_or_create_batch_definition, get_or_create_table_asset
from planalyst.config import SCHEMA_BRONZE
import great_expectations as gx

context = get_context()
suite = context.suites.add(gx.ExpectationSuite(name="intentional_fail_suite"))
suite.expectations = [
    ExpectTableRowCountToBeBetween(min_value=1, max_value=1),
]
try:
    suite.save()
except Exception:
    pass

data_asset = get_or_create_table_asset(
    context, "raw_matches_asset", "raw_matches", SCHEMA_BRONZE
)
batch_definition = get_or_create_batch_definition(data_asset, "raw_matches_batch")
try:
    vd = context.validation_definitions.get("intentional_fail_vd")
except Exception:
    vd = context.validation_definitions.add(
        gx.ValidationDefinition(
            name="intentional_fail_vd",
            data=batch_definition,
            suite=suite,
        )
    )
try:
    ckpt = context.checkpoints.get("intentional_fail_ckpt")
except Exception:
    ckpt = context.checkpoints.add(
        gx.Checkpoint(name="intentional_fail_ckpt", validation_definitions=[vd])
    )

result = ckpt.run()
if result.success:
    print("UNEXPECTED: intentional fail check passed")
    sys.exit(1)

print("[FAIL] Intentional check failed as expected — pipeline would halt here.")
print("Fail-fast demonstration complete.")

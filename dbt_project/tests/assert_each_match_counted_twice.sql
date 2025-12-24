-- Every finished match in silver produces exactly two fact rows (one per team).
with expected as (
    select count(*) * 2 as n from {{ ref('silver_matches') }} where home_goals is not null
),
actual as (
    select count(*) as n from {{ ref('fact_team_sentiment_performance') }}
)
select expected.n as expected_rows, actual.n as actual_rows
from expected, actual
where expected.n <> actual.n

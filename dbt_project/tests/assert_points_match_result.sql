-- A team's points must agree with its result: W = 3, D = 1, L = 0.
select team_name, matchweek_number, result, points
from {{ ref('fact_team_sentiment_performance') }}
where (result = 'W' and points <> 3)
   or (result = 'D' and points <> 1)
   or (result = 'L' and points <> 0)

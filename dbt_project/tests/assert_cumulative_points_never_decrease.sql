-- Running points can only go up from one matchweek to the next.
select team_name, matchweek_number, cumulative_points, previous_points
from (
    select
        team_name,
        matchweek_number,
        cumulative_points,
        lag(cumulative_points) over (partition by team_name order by matchweek_number) as previous_points
    from {{ ref('fact_team_sentiment_performance') }}
) t
where previous_points is not null
  and cumulative_points < previous_points

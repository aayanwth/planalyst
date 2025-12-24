-- Sentiment scores are documented as -1 to +1.
select team_name, matchweek_number, avg_sentiment_score
from {{ ref('fact_team_sentiment_performance') }}
where avg_sentiment_score < -1 or avg_sentiment_score > 1

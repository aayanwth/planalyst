-- Articles naming three or more clubs are round-ups: no club may receive their sentiment.
select article_url, team_name, polarity
from {{ ref('silver_article_teams') }}
where teams_mentioned >= 3
  and polarity <> 0

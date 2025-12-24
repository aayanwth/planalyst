-- An article may only be attributed to a match that had not kicked off when it was published.
select a.article_url, a.team_name, a.next_kickoff, n.published_at
from {{ ref('silver_article_teams') }} a
join {{ ref('silver_news_articles') }} n using (article_url)
where a.next_fixture_id is not null
  and a.next_kickoff < n.published_at

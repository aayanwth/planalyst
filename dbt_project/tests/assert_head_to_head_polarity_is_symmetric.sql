-- In a head-to-head article one side counts +1 and the other -1, so polarities must cancel.
select article_url, sum(polarity) as polarity_sum
from {{ ref('silver_article_teams') }}
where is_head_to_head
group by article_url
having sum(polarity) <> 0

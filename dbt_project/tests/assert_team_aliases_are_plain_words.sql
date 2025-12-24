-- Aliases are spliced into a regular expression, so they may only contain letters, spaces,
-- apostrophes and ampersands (no regex metacharacters).
select alias
from {{ ref('team_aliases') }}
where alias !~ '^[A-Za-z'' &]+$'

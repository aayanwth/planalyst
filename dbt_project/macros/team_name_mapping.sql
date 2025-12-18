/*
    PLanalyst — Macro: Map any team name variant to canonical name.

    Looks up the team name in the team_name_lookup seed table and
    returns the canonical_name. Falls back to the original name if
    no mapping is found.
*/

{% macro map_team_name(column_name) %}
    COALESCE(
        (SELECT tnl.canonical_name
         FROM {{ ref('team_name_lookup') }} tnl
         WHERE tnl.api_name = {{ column_name }}
            OR tnl.news_name = {{ column_name }}
         LIMIT 1),
        {{ column_name }}
    )
{% endmacro %}

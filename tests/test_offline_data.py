import pandas as pd

from planalyst.ml.offline_data import assign_matchdays, parse_season_csv, season_code

CSV = (
    "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,B365H\n"
    "E0,08/08/15,Aston,Bolton,0,1,2.1\n"
    "E0,08/08/2015,Chelsea,Derby,2,2,1.4\n"
    "E0,15/08/2015,Bolton,Chelsea,1,0,5.0\n"
    "E0,15/08/2015,Derby,Aston,3,1,2.8\n"
    "E0,,,,,,\n"
)


def test_season_code():
    assert season_code(2015) == "1516"
    assert season_code(1999) == "9900"


def test_parse_handles_bom_mixed_dates_and_blank_rows():
    df = parse_season_csv(("﻿" + CSV).encode("utf-8"), 2015)
    assert len(df) == 4
    assert df["utc_date"].iloc[0] == pd.Timestamp("2015-08-08")  # 2-digit year
    assert df["utc_date"].iloc[1] == pd.Timestamp("2015-08-08")  # 4-digit year
    assert df["utc_date"].iloc[2] == pd.Timestamp("2015-08-15")  # day-first


def test_parse_outcome_columns_and_no_odds_leak():
    df = parse_season_csv(CSV, 2015)
    assert list(df["score_winner"]) == ["AWAY_TEAM", "DRAW", "HOME_TEAM", "HOME_TEAM"]
    assert not any(c.startswith("B365") for c in df.columns)  # odds are out of scope
    assert df["id"].is_unique
    assert (df["season"] == 2015).all() and (df["season_label"] == "2015-2016").all()


def test_each_team_plays_once_per_matchday():
    df = parse_season_csv(CSV, 2015)
    assert list(df["matchday"]) == [1, 1, 2, 2]
    for _, rnd in df.groupby("matchday"):
        teams = list(rnd["home_team_name"]) + list(rnd["away_team_name"])
        assert len(teams) == len(set(teams))


def test_repeat_fixture_gets_a_later_round():
    df = pd.DataFrame(
        {
            "utc_date": pd.to_datetime(["2020-01-01", "2020-01-08", "2020-03-01"]),
            "home_team_name": ["A", "A", "A"],
            "away_team_name": ["B", "C", "B"],
        }
    )
    assert list(assign_matchdays(df)) == [1, 2, 3]


def test_api_name_mapping_is_one_to_one_and_uses_api_spelling():
    from planalyst.ml.offline_data import API_TEAM_NAMES

    assert len(set(API_TEAM_NAMES.values())) == len(API_TEAM_NAMES)  # no two clubs collapse together
    assert API_TEAM_NAMES["Man City"] == "Manchester City FC"
    assert API_TEAM_NAMES["Nott'm Forest"] == "Nottingham Forest FC"


def test_to_api_names_renames_and_rejects_unknown_clubs():
    import pytest

    from planalyst.ml.offline_data import to_api_names

    df = pd.DataFrame({"home_team_name": ["Man United"], "away_team_name": ["Wolves"]})
    out = to_api_names(df)
    assert (out.loc[0, "home_team_name"], out.loc[0, "away_team_name"]) == (
        "Manchester United FC",
        "Wolverhampton Wanderers FC",
    )
    with pytest.raises(ValueError, match="Atlantis"):
        to_api_names(pd.DataFrame({"home_team_name": ["Atlantis"], "away_team_name": ["Wolves"]}))

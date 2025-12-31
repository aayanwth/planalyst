"""Label mapping and text preparation for the sentiment scorer (model itself is stubbed)."""

import pandas as pd

from planalyst.nlp.sentiment import (
    FALLBACK_MODEL,
    PRIMARY_MODEL,
    normalize_label,
    prepare_text_for_scoring,
    score_articles,
)


def test_cardiff_labels_map_to_standard_names():
    assert normalize_label("LABEL_0", PRIMARY_MODEL) == "NEGATIVE"
    assert normalize_label("neutral", PRIMARY_MODEL) == "NEUTRAL"
    assert normalize_label("LABEL_2", PRIMARY_MODEL) == "POSITIVE"


def test_sst2_fallback_has_no_neutral_class():
    assert normalize_label("LABEL_1", FALLBACK_MODEL) == "POSITIVE"
    assert normalize_label("NEGATIVE", FALLBACK_MODEL) == "NEGATIVE"


def test_prepare_text_joins_title_and_description_and_truncates():
    assert prepare_text_for_scoring({"title": "Win", "description": "Late goal"}) == "Win Late goal"
    assert prepare_text_for_scoring({"title": None, "description": None}) == ""
    assert len(prepare_text_for_scoring({"title": "x" * 900, "description": ""})) == 500


def test_score_articles_skips_empty_text_and_keeps_alignment():
    articles = pd.DataFrame(
        {
            "article_url": ["u1", "u2", "u3"],
            "title": ["Great win", None, "Awful loss"],
            "description": [None, None, None],
        }
    )
    seen = []

    def fake_pipeline(texts, batch_size):
        seen.extend(texts)
        return [{"label": "LABEL_2" if "Great" in t else "LABEL_0", "score": 0.91234} for t in texts]

    out = score_articles(articles, fake_pipeline, PRIMARY_MODEL)
    assert seen == ["Great win", "Awful loss"]  # the empty article never reaches the model
    assert [(r["article_url"], r["sentiment_label"]) for r in out] == [
        ("u1", "POSITIVE"),
        ("u3", "NEGATIVE"),
    ]
    assert out[0]["sentiment_score"] == 0.9123


def test_score_articles_with_nothing_to_score():
    empty = pd.DataFrame({"article_url": ["u"], "title": [None], "description": [None]})
    assert score_articles(empty, lambda *a, **k: [], PRIMARY_MODEL) == []

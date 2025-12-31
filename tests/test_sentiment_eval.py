import pandas as pd
import pytest

from planalyst.nlp import evaluate as ev


def test_load_labelled_normalises_and_validates(tmp_path):
    path = tmp_path / "labels.csv"
    pd.DataFrame(
        {"text": ["a", "b", "c", None], "label": [" positive ", "NEGATIVE", None, "NEUTRAL"]}
    ).to_csv(path, index=False)
    df = ev.load_labelled(path)
    assert list(df["label"]) == ["POSITIVE", "NEGATIVE"]  # blank text / blank label rows dropped


def test_load_labelled_rejects_unknown_label_and_empty_files(tmp_path):
    bad = tmp_path / "bad.csv"
    pd.DataFrame({"text": ["a"], "label": ["HAPPY"]}).to_csv(bad, index=False)
    with pytest.raises(ValueError, match="Unknown labels"):
        ev.load_labelled(bad)
    empty = tmp_path / "empty.csv"
    pd.DataFrame({"text": ["a"], "label": [""]}).to_csv(empty, index=False)
    with pytest.raises(ValueError, match="No labelled rows"):
        ev.load_labelled(empty)
    with pytest.raises(ValueError, match="missing columns"):
        pd.DataFrame({"text": ["a"]}).to_csv(tmp_path / "nolabel.csv", index=False)
        ev.load_labelled(tmp_path / "nolabel.csv")


def test_classification_metrics_hand_computed():
    y_true = ["POSITIVE", "POSITIVE", "NEGATIVE", "NEUTRAL"]
    y_pred = ["POSITIVE", "NEGATIVE", "NEGATIVE", "NEUTRAL"]
    m = ev.classification_metrics(y_true, y_pred)
    assert m["accuracy"] == pytest.approx(0.75)
    pos = m["per_class"]["POSITIVE"]
    assert (pos["precision"], pos["recall"], pos["support"]) == (1.0, 0.5, 2)
    neg = m["per_class"]["NEGATIVE"]
    assert neg["precision"] == pytest.approx(0.5) and neg["recall"] == 1.0
    assert m["confusion"].loc["true POSITIVE", "pred NEGATIVE"] == 1
    assert m["confusion"].to_numpy().sum() == 4


def test_missing_class_does_not_crash():
    m = ev.classification_metrics(["POSITIVE", "POSITIVE"], ["POSITIVE", "NEUTRAL"])
    assert m["per_class"]["NEGATIVE"]["support"] == 0


def test_evaluate_uses_the_supplied_predictor_and_checks_length():
    df = pd.DataFrame({"text": ["win", "loss"], "label": ["POSITIVE", "NEGATIVE"]})
    perfect = ev.evaluate(df, lambda texts: ["POSITIVE" if t == "win" else "NEGATIVE" for t in texts])
    assert perfect["accuracy"] == 1.0
    with pytest.raises(ValueError, match="one label per text"):
        ev.evaluate(df, lambda texts: ["POSITIVE"])


def test_markdown_report_contains_the_numbers():
    m = ev.classification_metrics(["POSITIVE", "NEGATIVE"], ["POSITIVE", "POSITIVE"])
    report = ev.to_markdown(m, "demo-model")
    assert "demo-model" in report and "accuracy: 0.500" in report and "true NEGATIVE" in report

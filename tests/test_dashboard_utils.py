from streamlit_app import utils
from streamlit_app.utils import split_report


def test_split_report_separates_images_from_markdown_in_order():
    text = "# Title\n\nIntro\n\n![Alt](img/a.png)\n\n## Next\n![](img/b.png)\nTail"
    blocks = split_report(text)
    assert [kind for kind, _ in blocks] == ["markdown", "image", "markdown", "image", "markdown"]
    assert blocks[1] == ("image", "img/a.png") and blocks[3] == ("image", "img/b.png")
    assert blocks[0][1].startswith("# Title") and blocks[4][1] == "Tail"


def test_split_report_without_images_is_one_markdown_block():
    assert split_report("a\nb") == [("markdown", "a\nb")]
    assert split_report("") == []


def test_inline_images_inside_a_paragraph_are_left_alone():
    blocks = split_report("see ![x](img/a.png) inline")
    assert blocks == [("markdown", "see ![x](img/a.png) inline")]


def test_api_get_degrades_gracefully(monkeypatch):
    import requests

    def refuse(*args, **kwargs):
        raise requests.exceptions.ConnectionError

    monkeypatch.setattr(requests, "get", refuse)
    assert utils.api_get("/health") is None  # dashboard shows "cannot connect", not a traceback

    class BadResponse:
        def raise_for_status(self):
            raise requests.exceptions.HTTPError("404 Client Error")

    monkeypatch.setattr(requests, "get", lambda *a, **k: BadResponse())
    assert "error" in utils.api_get("/team/x/sentiment")

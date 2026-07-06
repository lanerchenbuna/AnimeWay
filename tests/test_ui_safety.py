from components.ui import render_anime_card


def test_render_anime_card_escapes_external_fields():
    html = render_anime_card(
        {
            "id": "x",
            "name": '<script>alert("x")</script>',
            "_anime_name": "Anime <b>Title</b>",
            "_city": 'Tokyo" onclick="bad()',
            "description": "<img src=x onerror=bad()>",
            "lat": 35.0,
            "lon": 139.0,
        }
    )

    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<img src=x" not in html
    assert "onclick=\"bad()" not in html

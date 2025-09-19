import json

from app import codex


def test_parse_model_listing_includes_codex_variants_from_json():
    payload = json.dumps(
        {
            "data": [
                {"id": "gpt-5", "deployment": "codex"},
                {"id": "gpt-5-mini", "deployments": ["codex", "default"]},
                {"id": "gpt-5-pro", "variants": [{"id": "codex-latest"}]},
                {"id": "o4-mini", "deployment": "default"},
            ]
        }
    )

    models = codex._parse_model_listing(payload)

    assert "gpt-5" in models
    assert models.count("gpt-5-codex") == 1
    assert models.count("gpt-5-mini-codex") == 1
    assert "gpt-5-pro-codex-latest" in models
    assert "o4-mini" in models
    assert "o4-mini-codex" not in models


def test_parse_model_listing_infers_codex_from_plaintext():
    raw = """
    Available models:
      gpt-5 codex default
      gpt-5-mini codex
      o4-mini default
    """

    models = codex._parse_model_listing(raw)

    assert "gpt-5-codex" in models
    assert "gpt-5-mini-codex" in models
    assert "o4-mini-codex" not in models

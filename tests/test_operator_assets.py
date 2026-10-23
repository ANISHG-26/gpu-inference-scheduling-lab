"""The static page loads only files the same-origin backend actually serves."""
from html.parser import HTMLParser
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from inference_lab.operator import STATIC_FILES

ROOT = Path(__file__).resolve().parents[1]


class AssetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.assets = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("src"):
            self.assets.append(attrs["src"])
        if tag == "link" and attrs.get("rel") == "stylesheet":
            self.assets.append(attrs["href"])


class OperatorAssetTests(unittest.TestCase):
    def test_page_assets_match_server_allowlist(self):
        parser = AssetParser()
        parser.feed((ROOT / "operator/static/index.html").read_text(encoding="utf-8"))
        self.assertEqual(set(parser.assets), {"/style.css", "/app.js"})
        for asset in parser.assets:
            self.assertTrue((ROOT / "operator/static" / STATIC_FILES[asset]).is_file())


if __name__ == "__main__":
    unittest.main()

# tests/test_adapter_books.py —— 离线解析测试，不联网
from pathlib import Path

from scripts.crawl.adapters.books_toscrape import BooksToscrapeAdapter

FIXTURE = Path(__file__).parent / "fixtures" / "books_product.html"


def test_parse_product_from_fixture():
    html = FIXTURE.read_text(encoding="utf-8")
    adapter = BooksToscrapeAdapter()
    rec = adapter.parse_product(html, "https://books.toscrape.com/catalogue/x/index.html")
    assert rec.external_id == "x"          # 从 URL slug 提取
    assert rec.title
    assert rec.price > 0
    assert rec.currency == "GBP"
    assert rec.rating in (1, 2, 3, 4, 5)
    assert rec.image_urls, "thumbnail url not found"
    assert rec.description


def test_fetch_reviews_returns_empty():
    adapter = BooksToscrapeAdapter()
    assert adapter.fetch_reviews("<html></html>", "u") == []

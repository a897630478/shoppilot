# tests/test_base_adapter.py  —— 纯逻辑，不联网
import time

from scripts.crawl.base_adapter import BaseAdapter, ProductRecord, ReviewItem


class DummyAdapter(BaseAdapter):
    def iter_product_urls(self):
        return iter([])

    def parse_product(self, html, url):
        raise NotImplementedError

    def fetch_reviews(self, html, url):
        return []


def test_throttle_sleeps_at_least_two_seconds(monkeypatch):
    adapter = DummyAdapter()
    events = []   # 顺序记录：("sleep", 秒) / ("get", url)

    class FakeSession:
        def get(self, url, headers=None, timeout=None):
            events.append(("get", url))
            class R:
                text = "<html></html>"
                def raise_for_status(self):
                    pass
            return R()

    import scripts.crawl.base_adapter as ba
    monkeypatch.setattr(time, "sleep", lambda s: events.append(("sleep", s)))

    adapter.throttled_get("http://example.com", FakeSession())
    assert len(events) == 2
    assert events[0][0] == "sleep" and events[0][1] >= 2.0
    assert events[1] == ("get", "http://example.com")


def test_product_record_defaults():
    rec = ProductRecord(
        external_id="x", title="t", category=None, price=1.0,
        currency="GBP", description=None, params={}, rating=None,
        url="u", image_urls=[], review_items=[],
    )
    assert rec.image_urls == []
    assert rec.review_items == []
    assert isinstance(rec.review_items, list)

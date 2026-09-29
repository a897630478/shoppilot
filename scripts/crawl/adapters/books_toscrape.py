# scripts/crawl/adapters/books_toscrape.py
# books.toscrape.com —— 官方爬虫沙箱，robots 全开放，零反爬。
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from scripts.crawl.base_adapter import BaseAdapter, ProductRecord, ReviewItem

BASE = "https://books.toscrape.com"
_RATING_WORDS = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}
PAGE_COUNT = 5   # 每页 20 本，5 页 = 100 本（M1 试跑规模）


class BooksToscrapeAdapter(BaseAdapter):
    site_name = "books_toscrape"

    def iter_product_urls(self):
        for page in range(1, PAGE_COUNT + 1):
            catalog_url = f"{BASE}/catalogue/page-{page}.html"
            # 列表页抓取交给调用方？不：直接产出详情页 URL 需先读列表页。
            # 为保持同步接口简单，这里用一次性轻量抓取（同样限速由调用方
            # 通过 throttled_get 无法复用，故列表页在此内部用同样节奏抓取）。
            yield from self._urls_from_catalog(catalog_url)

    def _urls_from_catalog(self, catalog_url: str):
        import time
        import random
        import requests
        from scripts.crawl.base_adapter import USER_AGENT, MIN_INTERVAL_SECONDS

        time.sleep(MIN_INTERVAL_SECONDS + random.uniform(0.0, 1.0))
        resp = requests.get(catalog_url, headers={"User-Agent": USER_AGENT}, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.select("article.product_pod h3 a"):
            href = a.get("href")
            if href:
                yield urljoin(catalog_url, href)

    def parse_product(self, html: str, url: str) -> ProductRecord:
        soup = BeautifulSoup(html, "html.parser")
        external_id = urlparse(url).path.rstrip("/").split("/")[-2]  # slug 即唯一 ID
        title = soup.select_one("h1").get_text(strip=True)
        price_text = soup.select_one(".price_color").get_text(strip=True)  # "£51.77"
        price = float(price_text.replace("£", "").replace("Â", "").strip())
        rating_el = soup.select_one(".star-rating")
        rating = _RATING_WORDS.get(rating_el["class"][-1]) if rating_el else None
        desc_el = soup.select_one("#product_description ~ p") or soup.select_one("p.product_description + p")
        description = desc_el.get_text(strip=True) if desc_el else None
        # 真实页面是 div.thumbnail 包裹 img（img 自身无 class），故优先 .thumbnail img，
        # 回退 img.thumbnail 兼容最小结构 fixture
        img = soup.select_one(".thumbnail img") or soup.select_one("img.thumbnail")
        image_urls = [urljoin(url, img["src"])] if img and img.get("src") else []
        # 规格表：tr th=键 td=值
        params = {}
        for tr in soup.select("table tr"):
            th, td = tr.select_one("th"), tr.select_one("td")
            if th and td:
                params[th.get_text(strip=True)] = td.get_text(strip=True)
        # 面包屑最后一段是类目
        crumbs = [a.get_text(strip=True) for a in soup.select("ul.breadcrumb li a")]
        category = crumbs[-1] if crumbs else None
        return ProductRecord(
            external_id=external_id, title=title, category=category,
            price=price, currency="GBP", description=description,
            params=params, rating=rating, url=url, image_urls=image_urls,
        )

    def fetch_reviews(self, html: str, url: str) -> list[ReviewItem]:
        return []   # 沙箱站无用户评价

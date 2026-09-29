# scripts/crawl/base_adapter.py
# 商品站点适配器基类：新站点 = 新建一个子类实现三个抽象方法。
# 合规硬约束（spec §3.2）：限速 ≥2s 随机抖动、显式 UA、遵守 robots.txt、仅公开页面。
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import requests

USER_AGENT = "ShopPilotDemo/0.1 (local demo; contact: none)"
MIN_INTERVAL_SECONDS = 2.0


@dataclass
class ReviewItem:
    author: str | None
    rating: int | None
    content: str


@dataclass
class ProductRecord:
    external_id: str
    title: str
    category: str | None
    price: float
    currency: str
    description: str | None
    params: dict
    rating: int | None
    url: str
    image_urls: list[str] = field(default_factory=list)
    review_items: list[ReviewItem] = field(default_factory=list)


class BaseAdapter(ABC):
    site_name: str = "base"

    @abstractmethod
    def iter_product_urls(self):
        """产出商品详情页 URL 迭代器（内部可翻页；调用方负责逐个 throttled_get）。"""

    @abstractmethod
    def parse_product(self, html: str, url: str) -> ProductRecord:
        """把详情页 HTML 解析为 ProductRecord。"""

    @abstractmethod
    def fetch_reviews(self, html: str, url: str) -> list[ReviewItem]:
        """从详情页（或其携带的数据）提取评价；站点无评价返回 []。"""

    def throttled_get(self, url: str, session: requests.Session) -> str:
        time.sleep(MIN_INTERVAL_SECONDS + random.uniform(0.0, 1.0))
        resp = session.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
        resp.raise_for_status()
        return resp.text

# M1 数据地基 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 电商改造的第一块地基——商品/评价/订单等 7 张新表入 PG、爬虫入库真实商品、Milvus 商品知识集合、`/products` 与 `/orders` 轻量外壳 API，全部落地且**不破坏现有 EduAgent 功能**。

**Architecture:** 在现有 FastAPI + PostgreSQL + Milvus 栈上做纯增量扩展：新表走 `migrations.py` 幂等 DDL；爬虫是独立脚本目录 `scripts/crawl/`（适配器模式，站点可换）；商品图片存 MinIO 新桶 `product-images`；商品切块入**新** Milvus 集合 `product_knowledge`（旧 `knowledge_domain` 课程集合原样保留，M2 才切换 QA）；API 层新增 `products.py` / `orders.py` 两个子路由。

**Tech Stack:** Python 3.11、FastAPI、SQLAlchemy async（raw SQL，沿用现库模式）、pymilvus、minio 客户端、httpx + BeautifulSoup（爬虫）、pytest。

**Spec:** `docs/superpowers/specs/2026-09-27-ecommerce-rework-design.md`

## Global Constraints

- 现有 EduAgent 功能（QA/考试/简历/面试）在 M1 期间**必须保持可运行**；不改、不删任何教育模块代码。
- 所有 DDL 幂等（`CREATE TABLE IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS`），禁止 DROP/TRUNCATE。
- 爬虫硬性合规：单请求间隔 ≥2s 随机抖动、显式 UA、遵守目标站 robots.txt、仅抓公开页面、数据仅本地演示。
- 不做购物车、支付网关、库存、优惠券（YAGNI，见 spec §8）。
- LLM 生成的商品价格/参数不采信，一律以 PG 库内数据为准。
- Python 3.11；`requirements.txt` 已有依赖**不得升级版本**，只允许追加新依赖。
- 所有连接配置从 `.env.local` 读取，禁止硬编码端口/密钥。

## 目标站点决策（spec §3.2 留待 M1 的决定）

首个适配器选 **books.toscrape.com**：官方爬虫练习沙箱、robots 全开放、结构十年稳定、零反爬，完全满足 spec「反爬压力小、结构稳定 + 合规」标准。适配器模式保证后续换真实站点只新增一个文件。

**评价数据说明**：该站不提供用户评价。`base_adapter` 仍定义 `fetch_reviews()` 接口（真实站点适配器实现后直接爬取）；M1 用 `scripts/seed_product_reviews.py` 以 DeepSeek 生成标注 `source='generated'` 的种子评价（每商品 30 条），供 M4 评价分析 Agent 开发使用。真实评价待选定带评价的真实站点后由爬虫覆盖。

## 文件结构总览

| 文件 | 职责 | 动作 |
|------|------|------|
| `backend/db/migrations.py` | 7 张电商表的幂等 DDL | 修改（追加） |
| `backend/config.py` | 新增 MinIO 配置字段 | 修改 |
| `.env.local` | 追加 MINIO_* 键 | 修改 |
| `requirements.txt` | 追加 `minio`、`beautifulsoup4` | 修改 |
| `backend/core/storage.py` | MinIO 桶初始化/图片上传下载 | 新建 |
| `scripts/crawl/base_adapter.py` | 适配器基类 + ProductRecord + 限速器 | 新建 |
| `scripts/crawl/adapters/books_toscrape.py` | books.toscrape 解析实现 | 新建 |
| `scripts/crawl/run_crawl.py` | 爬虫 CLI：爬取→图片入 MinIO→商品入 PG | 新建 |
| `scripts/seed_product_reviews.py` | LLM 生成种子评价 | 新建 |
| `scripts/init_milvus_product.py` | 建 `product_knowledge` 集合（product_id 字段） | 新建 |
| `scripts/build_product_knowledge.py` | 商品切块→BGE-M3→写入 Milvus | 新建 |
| `backend/api/v1/products.py` | 商品列表/详情/图片接口 | 新建 |
| `backend/api/v1/orders.py` | 模拟下单/订单查询/模拟支付接口 | 新建 |
| `backend/api/router.py` | 挂载 products / orders 子路由 | 修改 |
| `tests/test_adapter_books.py` | 适配器解析单测（fixture HTML，不联网） | 新建 |
| `tests/test_migrations.py` | 新表存在性单测（需 PG） | 新建 |
| `scripts/manual_tests/test_products_api.py` | 商品接口冒烟（需后端运行） | 新建 |
| `scripts/manual_tests/test_orders_api.py` | 订单接口冒烟（需后端运行） | 新建 |

---

### Task 1: 电商 7 张表的幂等迁移

**Files:**
- Modify: `backend/db/migrations.py:17-45`（`_MIGRATIONS` 列表追加）
- Test: `tests/test_migrations.py`（新建）

**Interfaces:**
- Consumes: `backend.dependencies.AsyncSessionLocal`（已存在）
- Produces: PG 表 `products`、`product_reviews`、`orders`、`service_tickets`、`review_reports`、`recommendation_sessions`、`recommendation_results`——后续所有任务读写的表名与列名以本任务 DDL 为准。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_migrations.py`：

```python
# tests/test_migrations.py
# 需要本地 PG 已启动（docker-compose postgres healthy）
import asyncio

import pytest
from sqlalchemy import text

from backend.db.migrations import run_migrations
from backend.dependencies import AsyncSessionLocal

EXPECTED_TABLES = [
    "products", "product_reviews", "orders", "service_tickets",
    "review_reports", "recommendation_sessions", "recommendation_results",
]


@pytest.mark.asyncio
async def test_ecommerce_tables_exist():
    await run_migrations()
    async with AsyncSessionLocal() as session:
        for table in EXPECTED_TABLES:
            res = await session.execute(
                text(
                    "SELECT to_regclass(:t) IS NOT NULL AS exists"
                ),
                {"t": table},
            )
            row = res.fetchone()
            assert row[0] is True, f"missing table: {table}"
```

- [ ] **Step 2: 运行确认失败**

Run: `$env:MIMO_PYTHON -m pytest tests/test_migrations.py -v`
Expected: FAIL，`missing table: products`

- [ ] **Step 3: 在 `_MIGRATIONS` 列表末尾追加 DDL**

在 `backend/db/migrations.py` 的 `_MIGRATIONS` 列表内、现有最后一条元组之后追加（沿用现有 `(名字, SQL)` 元组格式）：

```python
    # ── 电商改造 M1（spec: 2026-09-27-ecommerce-rework-design.md §3.1）──
    (
        "create_products",
        """
        CREATE TABLE IF NOT EXISTS products (
            id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id       VARCHAR(64) NOT NULL DEFAULT 'tenant_default',
            external_id     VARCHAR(128),
            source          VARCHAR(64) NOT NULL DEFAULT 'books_toscrape',
            title           VARCHAR(512) NOT NULL,
            category        VARCHAR(128),
            price           NUMERIC(10,2),
            currency        VARCHAR(8) NOT NULL DEFAULT 'GBP',
            description     TEXT,
            params          JSONB NOT NULL DEFAULT '{}',
            image_object    VARCHAR(512),
            rating          INT,
            url             VARCHAR(1024),
            is_active       BOOLEAN NOT NULL DEFAULT TRUE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (source, external_id)
        );
        CREATE INDEX IF NOT EXISTS idx_products_category ON products (category);
        CREATE INDEX IF NOT EXISTS idx_products_title ON products (title);
        """,
    ),
    (
        "create_product_reviews",
        """
        CREATE TABLE IF NOT EXISTS product_reviews (
            id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            product_id      UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            author          VARCHAR(128),
            rating          INT CHECK (rating BETWEEN 1 AND 5),
            content         TEXT NOT NULL,
            source          VARCHAR(16) NOT NULL DEFAULT 'generated'
                            CHECK (source IN ('generated', 'crawled')),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_product_reviews_product_id ON product_reviews (product_id);
        """,
    ),
    (
        "create_orders",
        """
        CREATE TABLE IF NOT EXISTS orders (
            id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id       VARCHAR(64) NOT NULL DEFAULT 'tenant_default',
            user_id         UUID NOT NULL REFERENCES users(id),
            product_id      UUID NOT NULL REFERENCES products(id),
            quantity        INT NOT NULL DEFAULT 1 CHECK (quantity > 0),
            unit_price      NUMERIC(10,2) NOT NULL,
            total_amount    NUMERIC(10,2) NOT NULL,
            currency        VARCHAR(8) NOT NULL DEFAULT 'GBP',
            receiver        VARCHAR(128) NOT NULL,
            address         VARCHAR(512) NOT NULL,
            status          VARCHAR(16) NOT NULL DEFAULT 'created'
                            CHECK (status IN ('created','paid','shipped','completed','cancelled')),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders (user_id);
        CREATE INDEX IF NOT EXISTS idx_orders_status ON orders (status);
        """,
    ),
    (
        "create_service_tickets",
        """
        CREATE TABLE IF NOT EXISTS service_tickets (
            id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id       VARCHAR(64) NOT NULL DEFAULT 'tenant_default',
            order_id        UUID NOT NULL REFERENCES orders(id),
            user_id         UUID NOT NULL REFERENCES users(id),
            ticket_type     VARCHAR(16) NOT NULL
                            CHECK (ticket_type IN ('logistics','refund','exchange')),
            reason          TEXT NOT NULL,
            status          VARCHAR(16) NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending','processing','resolved','rejected')),
            ai_result       JSONB,
            needs_review    BOOLEAN NOT NULL DEFAULT FALSE,
            reviewed_by     UUID REFERENCES users(id),
            reviewed_at     TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_service_tickets_status ON service_tickets (status);
        CREATE INDEX IF NOT EXISTS idx_service_tickets_order_id ON service_tickets (order_id);
        """,
    ),
    (
        "create_review_reports",
        """
        CREATE TABLE IF NOT EXISTS review_reports (
            id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id       VARCHAR(64) NOT NULL DEFAULT 'tenant_default',
            product_id      UUID NOT NULL REFERENCES products(id),
            triggered_by    UUID REFERENCES users(id),
            scores          JSONB,
            pros            JSONB,
            cons            JSONB,
            summary         TEXT,
            status          VARCHAR(16) NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending','processing','done','failed')),
            error_msg       TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_review_reports_product_id ON review_reports (product_id);
        """,
    ),
    (
        "create_recommendation_sessions",
        """
        CREATE TABLE IF NOT EXISTS recommendation_sessions (
            id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id        VARCHAR(64) NOT NULL DEFAULT 'tenant_default',
            user_id          UUID REFERENCES users(id),
            session_id       VARCHAR(128) NOT NULL,
            thread_id        VARCHAR(128) NOT NULL UNIQUE,
            stage            VARCHAR(32) NOT NULL DEFAULT 'needs_discovery',
            status           VARCHAR(16) NOT NULL DEFAULT 'in_progress'
                             CHECK (status IN ('in_progress','finished')),
            result           JSONB,
            finished_at      TIMESTAMPTZ,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_rec_sessions_user_id ON recommendation_sessions (user_id);
        """,
    ),
    (
        "create_recommendation_results",
        """
        CREATE TABLE IF NOT EXISTS recommendation_results (
            id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            session_id      UUID NOT NULL REFERENCES recommendation_sessions(id) ON DELETE CASCADE,
            product_id      UUID NOT NULL REFERENCES products(id),
            rank            INT NOT NULL,
            reason          TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_rec_results_session_id ON recommendation_results (session_id);
        """,
    ),
```

注意：`run_migrations` 对多语句 SQL 用 `session.execute(text(sql))` 执行——asyncpg 支持一次 execute 多条分号分隔语句；若实测报错，把每条 `CREATE INDEX` 拆成独立的 `_MIGRATIONS` 条目（DDL 本身幂等，拆开更稳妥）。

- [ ] **Step 4: 运行测试确认通过**

Run: `$env:MIMO_PYTHON -m pytest tests/test_migrations.py -v`
Expected: PASS（7 个表全部存在）

- [ ] **Step 5: 验证现有功能未破坏**

Run: `uvicorn backend.main:app --port 8000`，另开终端 `Invoke-WebRequest http://localhost:8000/health`
Expected: `{"status":"ok"}`，启动日志无 migration 报错（`db.migrations_done` 正常打印）

---

### Task 2: MinIO 配置与存储助手

**Files:**
- Modify: `backend/config.py:61-67`（应用基础配置区之前追加 MinIO 段）
- Modify: `.env.local`（末尾追加 4 键）
- Modify: `requirements.txt`（工具区追加）
- Create: `backend/core/storage.py`
- Test: `tests/test_storage.py`（新建）

**Interfaces:**
- Consumes: `get_settings()`；docker-compose 中已有的 MinIO 服务（:9002，凭据 `MINIO_ACCESS_KEY`/`MINIO_SECRET_KEY`，缺省 `minioadmin`）
- Produces:
  - `backend.core.storage.ensure_bucket() -> None`（幂等建桶 `product-images`）
  - `backend.core.storage.upload_product_image(object_name: str, data: bytes, content_type: str) -> str`（返回 object_name）
  - `backend.core.storage.download_product_image(object_name: str) -> tuple[bytes, str]`（返回 `(bytes, content_type)`，不存在抛 `FileNotFoundError`）
  - Settings 新增字段：`minio_endpoint`、`minio_access_key`、`minio_secret_key`、`minio_bucket`（默认值如下）

- [ ] **Step 1: 追加依赖**

`requirements.txt` 的「工具」区（`httpx==0.28.1` 所在区块）末尾追加：

```
minio==7.2.9
beautifulsoup4==4.12.3
```

Run: `$env:MIMO_PYTHON -m pip install minio==7.2.9 beautifulsoup4==4.12.3`
Expected: 安装成功

- [ ] **Step 2: 追加配置**

`backend/config.py` 在 `# ── 应用基础配置 ──` 注释之前插入：

```python
    # ── 对象存储（MinIO，商品图片）──
    minio_endpoint: str = "localhost:9002"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "product-images"
```

`.env.local` 末尾追加（值与 docker-compose 默认一致，可后续改）：

```ini
# MinIO（商品图片桶）
MINIO_ENDPOINT=localhost:9002
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=product-images
```

- [ ] **Step 3: 写失败测试**

新建 `tests/test_storage.py`：

```python
# tests/test_storage.py
# 需要 docker-compose 的 minio 服务已启动
from backend.core import storage


def test_upload_download_roundtrip():
    storage.ensure_bucket()
    payload = b"\x89PNG\r\n\x1a\nfake"
    object_name = "test/roundtrip.png"
    returned = storage.upload_product_image(object_name, payload, "image/png")
    assert returned == object_name
    data, ctype = storage.download_product_image(object_name)
    assert data == payload
    assert ctype == "image/png"


def test_download_missing_raises():
    storage.ensure_bucket()
    try:
        storage.download_product_image("no/such/object.png")
        raise AssertionError("should raise FileNotFoundError")
    except FileNotFoundError:
        pass
```

- [ ] **Step 4: 运行确认失败**

Run: `$env:MIMO_PYTHON -m pytest tests/test_storage.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'backend.core.storage'`

- [ ] **Step 5: 实现 storage**

新建 `backend/core/storage.py`：

```python
# backend/core/storage.py
# MinIO 商品图片存取（桶幂等创建；凭证/端点全部来自 .env.local）
from minio import Minio
from minio.error import S3Error

from backend.config import get_settings
from backend.core.logger import get_logger

logger = get_logger(__name__)

_CONTENT_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif",
}

_client: Minio | None = None


def _get_client() -> Minio:
    global _client
    if _client is None:
        s = get_settings()
        _client = Minio(
            s.minio_endpoint,
            access_key=s.minio_access_key,
            secret_key=s.minio_secret_key,
            secure=False,   # 本地 docker http
        )
    return _client


def ensure_bucket() -> None:
    bucket = get_settings().minio_bucket
    client = _get_client()
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
        logger.info("storage.bucket_created", bucket=bucket)


def upload_product_image(object_name: str, data: bytes, content_type: str) -> str:
    from io import BytesIO
    bucket = get_settings().minio_bucket
    _get_client().put_object(
        bucket, object_name, BytesIO(data), len(data),
        content_type=content_type,
    )
    return object_name


def download_product_image(object_name: str) -> tuple[bytes, str]:
    bucket = get_settings().minio_bucket
    try:
        resp = _get_client().get_object(bucket, object_name)
    except S3Error as e:
        if e.code in ("NoSuchKey", "NoSuchObject"):
            raise FileNotFoundError(object_name) from e
        raise
    try:
        return resp.read(), resp.headers.get("Content-Type", "application/octet-stream")
    finally:
        resp.close()
        resp.release_conn()
```

- [ ] **Step 6: 运行测试确认通过**

Run: `$env:MIMO_PYTHON -m pytest tests/test_storage.py -v`
Expected: 2 passed（若连接被拒，先 `docker-compose --env-file .env.local up -d minio`）

---

### Task 3: 爬虫适配器基类

**Files:**
- Create: `scripts/crawl/__init__.py`（空文件）
- Create: `scripts/crawl/adapters/__init__.py`（空文件）
- Create: `scripts/crawl/base_adapter.py`
- Test: `tests/test_base_adapter.py`（新建）

**Interfaces:**
- Consumes: 无（纯标准库 + `dataclasses`）
- Produces:
  - `@dataclass ProductRecord`：`external_id, title, category, price, currency, description, params, rating, url, image_urls, review_items`
  - `@dataclass ReviewItem`：`author, rating, content`
  - `class BaseAdapter`：抽象方法 `iter_product_urls() -> Iterator[str]`、`parse_product(html: str, url: str) -> ProductRecord`、`fetch_reviews(html: str, url: str) -> list[ReviewItem]`；具体方法 `throttled_get(url: str, session: requests.Session) -> str`（限速 ≥2s+抖动、UA、超时）
  - `USER_AGENT` 常量：`"EduAgentEcommerceCrawler/0.1 (local demo; contact: none)"`

- [ ] **Step 1: 写失败测试**

新建 `tests/test_base_adapter.py`：

```python
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
```

保留 `ReviewItem` import（Task 4 的适配器直接使用同一模块导出）。

- [ ] **Step 2: 运行确认失败**

Run: `$env:MIMO_PYTHON -m pytest tests/test_base_adapter.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'scripts.crawl.base_adapter'`

- [ ] **Step 3: 实现基类**

新建 `scripts/crawl/base_adapter.py`：

```python
# scripts/crawl/base_adapter.py
# 商品站点适配器基类：新站点 = 新建一个子类实现三个抽象方法。
# 合规硬约束（spec §3.2）：限速 ≥2s 随机抖动、显式 UA、遵守 robots.txt、仅公开页面。
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import requests

USER_AGENT = "EduAgentEcommerceCrawler/0.1 (local demo; contact: none)"
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `$env:MIMO_PYTHON -m pytest tests/test_base_adapter.py -v`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add scripts/crawl tests/test_base_adapter.py
git commit -m "feat(crawl): add adapter base with throttled compliant fetcher"
```

（若仓库无 git 则跳过提交，仅保留文件。）

---

### Task 4: books.toscrape 适配器

**Files:**
- Create: `scripts/crawl/adapters/books_toscrape.py`
- Test: `tests/test_adapter_books.py`（新建），Fixture: `tests/fixtures/books_product.html`（新建）

**Interfaces:**
- Consumes: `scripts.crawl.base_adapter` 的 `BaseAdapter / ProductRecord / ReviewItem / throttled_get`
- Produces: `class BooksToscrapeAdapter(BaseAdapter)`，`site_name = "books_toscrape"`；该站无用户评价，`fetch_reviews` 返回 `[]`（真实站点适配器需实现）

- [ ] **Step 1: 制作离线 fixture**

用 `Invoke-WebRequest https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html` 抓一页保存为 `tests/fixtures/books_product.html`（保留原始 HTML；若网络不可用，手工写入含 `<h1>`、`.price_color`、`img.thumbnail`、`p.product_description`、`.star-rating Three` 的最小结构 HTML，测试断言按此最小结构写）。

- [ ] **Step 2: 写失败测试**

新建 `tests/test_adapter_books.py`：

```python
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
```

- [ ] **Step 3: 运行确认失败**

Run: `$env:MIMO_PYTHON -m pytest tests/test_adapter_books.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 4: 实现适配器**

新建 `scripts/crawl/adapters/books_toscrape.py`：

```python
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
        img = soup.select_one("img.thumbnail")
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
```

- [ ] **Step 5: 运行测试确认通过**

Run: `$env:MIMO_PYTHON -m pytest tests/test_adapter_books.py -v`
Expected: 2 passed

- [ ] **Step 6: 小规模联网自检（手动）**

Run:
```powershell
$env:MIMO_PYTHON -c "from scripts.crawl.adapters.books_toscrape import BooksToscrapeAdapter as A; import requests; a=A(); u=next(a.iter_product_urls()); html=a.throttled_get(u, requests.Session()); p=a.parse_product(html,u); print(p.title, p.price, p.rating)"
```
Expected: 打印一本书的标题/价格/星级；耗时 ≥2s（限速生效）

---

### Task 5: 爬虫 CLI：爬取 → 图片入 MinIO → 商品入 PG

**Files:**
- Create: `scripts/crawl/run_crawl.py`
- Test: `scripts/manual_tests/test_crawl_ingest.py`（新建，需 PG+MinIO）

**Interfaces:**
- Consumes: Task 1 表 `products`（`UNIQUE(source, external_id)` 供 upsert）；Task 2 `storage.ensure_bucket/upload_product_image`；Task 4 `BooksToscrapeAdapter`
- Produces: 命令 `python -m scripts.crawl.run_crawl --limit 10`，将 N 个商品写入 `products`，`image_object` 列存 MinIO object 名 `products/{external_id}/{序号}.{ext}`；幂等可重复跑（已存在则 UPDATE）

- [ ] **Step 1: 写冒烟测试（需基础设施）**

新建 `scripts/manual_tests/test_crawl_ingest.py`：

```python
# scripts/manual_tests/test_crawl_ingest.py
# 运行前置：PG + MinIO 已启动，且已跑过 Task 1 迁移
# 运行：python -m pytest scripts/manual_tests/test_crawl_ingest.py -v -s
import asyncio

import pytest
from sqlalchemy import text

from backend.db.migrations import run_migrations
from backend.dependencies import AsyncSessionLocal
from scripts.crawl.adapters.books_toscrape import BooksToscrapeAdapter
from scripts.crawl.run_crawl import ingest_products


@pytest.mark.asyncio
async def test_ingest_two_products():
    await run_migrations()
    adapter = BooksToscrapeAdapter()
    await ingest_products(adapter, limit=2, skip_images=False)
    async with AsyncSessionLocal() as session:
        res = await session.execute(
            text("SELECT count(*) FROM products WHERE source = 'books_toscrape'")
        )
        count = res.fetchone()[0]
        assert count >= 1
        res = await session.execute(
            text("SELECT image_object FROM products WHERE source='books_toscrape' LIMIT 1")
        )
        obj = res.fetchone()[0]
        assert obj and obj.startswith("products/")
```

- [ ] **Step 2: 运行确认失败**

Run: `$env:MIMO_PYTHON -m pytest scripts/manual_tests/test_crawl_ingest.py -v -s`
Expected: FAIL，`ModuleNotFoundError: scripts.crawl.run_crawl`

- [ ] **Step 3: 实现 CLI**

新建 `scripts/crawl/run_crawl.py`：

```python
# scripts/crawl/run_crawl.py
# 用法：python -m scripts.crawl.run_crawl --limit 10 [--skip-images]
# 流程：适配器产出 URL → 限速抓取 → 解析 → 下载图片入 MinIO → upsert PG products
import argparse
import asyncio
from urllib.parse import urlparse

import requests
from sqlalchemy import text

from backend.core import storage
from backend.core.logger import get_logger
from backend.dependencies import AsyncSessionLocal
from scripts.crawl.adapters.books_toscrape import BooksToscrapeAdapter

logger = get_logger(__name__)

_UPSERT_SQL = """
    INSERT INTO products
        (tenant_id, external_id, source, title, category, price, currency,
         description, params, image_object, rating, url)
    VALUES
        (:tenant_id, :external_id, :source, :title, :category, :price, :currency,
         :description, :params, :image_object, :rating, :url)
    ON CONFLICT (source, external_id) DO UPDATE SET
        title = EXCLUDED.title,
        category = EXCLUDED.category,
        price = EXCLUDED.price,
        description = EXCLUDED.description,
        params = EXCLUDED.params,
        image_object = EXCLUDED.image_object,
        rating = EXCLUDED.rating,
        url = EXCLUDED.url,
        updated_at = NOW()
"""

_IMAGE_EXT = {".jpg": ".jpg", ".jpeg": ".jpg", ".png": ".png", ".webp": ".webp"}


def _content_type(ext: str) -> str:
    return {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(
        ext, "application/octet-stream"
    )


async def _download_image(url: str, external_id: str, index: int, session: requests.Session) -> str | None:
    path = urlparse(url).path
    ext = next((e for e in _IMAGE_EXT if path.lower().endswith(e)), None)
    if ext is None:
        return None
    html_bytes = await asyncio.to_thread(_sync_get_bytes, url, session)
    if html_bytes is None:
        return None
    object_name = f"products/{external_id}/{index}{_IMAGE_EXT[ext]}"
    await asyncio.to_thread(
        storage.upload_product_image, object_name, html_bytes, _content_type(_IMAGE_EXT[ext])
    )
    return object_name


def _sync_get_bytes(url: str, session: requests.Session) -> bytes | None:
    from scripts.crawl.base_adapter import USER_AGENT, MIN_INTERVAL_SECONDS
    import random
    import time

    time.sleep(MIN_INTERVAL_SECONDS + random.uniform(0.0, 1.0))
    try:
        resp = session.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        logger.warning("crawl.image_failed", url=url, error=str(e))
        return None


async def ingest_products(adapter, limit: int, skip_images: bool = False, tenant_id: str = "tenant_default") -> int:
    """爬取并入库；返回成功条数。幂等（ON CONFLICT UPDATE）。"""
    storage.ensure_bucket()
    session = requests.Session()
    count = 0
    urls = []
    for url in adapter.iter_product_urls():
        urls.append(url)
        if len(urls) >= limit:
            break

    async with AsyncSessionLocal() as db:
        for url in urls:
            html = await asyncio.to_thread(adapter.throttled_get, url, session)
            rec = adapter.parse_product(html, url)
            image_object = None
            if not skip_images and rec.image_urls:
                image_object = await _download_image(
                    rec.image_urls[0], rec.external_id, 0, session
                )
            import json
            await db.execute(
                text(_UPSERT_SQL),
                {
                    "tenant_id": tenant_id,
                    "external_id": rec.external_id,
                    "source": adapter.site_name,
                    "title": rec.title,
                    "category": rec.category,
                    "price": rec.price,
                    "currency": rec.currency,
                    "description": rec.description,
                    "params": json.dumps(rec.params, ensure_ascii=False),
                    "image_object": image_object,
                    "rating": rec.rating,
                    "url": rec.url,
                },
            )
            await db.commit()
            count += 1
            logger.info("crawl.ingested", title=rec.title, price=rec.price, n=count)
    return count


def main():
    parser = argparse.ArgumentParser(description="商品爬虫入库")
    parser.add_argument("--limit", type=int, default=10, help="最多爬取商品数")
    parser.add_argument("--skip-images", action="store_true", help="跳过图片下载")
    args = parser.parse_args()

    adapter = BooksToscrapeAdapter()
    n = asyncio.run(ingest_products(adapter, args.limit, args.skip_images))
    print(f"✅ 完成：入库/更新 {n} 个商品")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行冒烟测试**

Run（PG、MinIO 已启动）: `$env:MIMO_PYTHON -m pytest scripts/manual_tests/test_crawl_ingest.py -v -s`
Expected: PASS，PG 中 `products` ≥1 行，`image_object` 有值

- [ ] **Step 5: 跑一批真实数据**

Run: `$env:MIMO_PYTHON -m scripts.crawl.run_crawl --limit 30`
Expected: 控制台逐条 `crawl.ingested`；总耗时约 `30 × (2~3s × 2)` ≈ 2~4 分钟（限速导致，属预期）
验证: `SELECT count(*), count(image_object) FROM products;` 两数接近

---

### Task 6: 种子评价生成（LLM）

**Files:**
- Create: `scripts/seed_product_reviews.py`
- Test: `scripts/manual_tests/test_seed_reviews.py`（新建，需 PG + DeepSeek Key）

**Interfaces:**
- Consumes: Task 1 表 `product_reviews`；`backend.core.llm_factory.LLMFactory`（已存在，统一封装 DeepSeek）
- Produces: 命令 `python -m scripts.seed_product_reviews --per-product 30 [--limit 5]`；写入 `source='generated'` 评价；**幂等**（已有 ≥N 条 generated 评价的商品跳过）

- [ ] **Step 1: 写冒烟测试**

新建 `scripts/manual_tests/test_seed_reviews.py`：

```python
# scripts/manual_tests/test_seed_reviews.py
# 需要：PG 已有商品（跑过 run_crawl）、.env.local 有 DEEPSEEK_API_KEY
import asyncio

import pytest
from sqlalchemy import text

from backend.dependencies import AsyncSessionLocal
from scripts.seed_product_reviews import seed_reviews_for_all


@pytest.mark.asyncio
async def test_seed_creates_reviews():
    await seed_reviews_for_all(per_product=3, limit=1)
    async with AsyncSessionLocal() as session:
        res = await session.execute(
            text("""
                SELECT count(*) FROM product_reviews r
                JOIN products p ON p.id = r.product_id
                WHERE r.source = 'generated'
            """)
        )
        assert res.fetchone()[0] >= 3
```

- [ ] **Step 2: 运行确认失败**

Run: `$env:MIMO_PYTHON -m pytest scripts/manual_tests/test_seed_reviews.py -v -s`
Expected: FAIL，`ModuleNotFoundError: scripts.seed_product_reviews`

- [ ] **Step 3: 实现生成脚本**

新建 `scripts/seed_product_reviews.py`：

```python
# scripts/seed_product_reviews.py
# 用法：python -m scripts.seed_product_reviews --per-product 30 --limit 10
# 为商品生成模拟评价（source='generated'），供 M4 评价分析 Agent 使用。
# 注意：生成的评价是演示数据，价格/参数类信息若出现在评价中以库内为准。
import argparse
import asyncio
import json
import re

from sqlalchemy import text

from backend.core.llm_factory import LLMFactory
from backend.core.logger import get_logger
from backend.dependencies import AsyncSessionLocal

logger = get_logger(__name__)

_PROMPT = """你是电商平台的真实买家。请为下面这件商品写 {n} 条中文买家评价。
商品：{title}
类目：{category}
简介：{desc}

要求：
1. 每条 30~80 字，口吻各异（满意/中性/不满都要有，比例约 6:3:1）
2. rating 字段 1~5 星，与口吻一致
3. author 用化名
4. 只输出 JSON 数组，格式：[{{"author":"...","rating":4,"content":"..."}}]
5. 不要编造具体价格数字与规格参数，只谈主观体验
"""


async def _gen_reviews(llm, product: dict) -> list[dict]:
    prompt = _PROMPT.format(
        n=product["n"],
        title=product["title"],
        category=product.get("category") or "通用",
        desc=(product.get("description") or "")[:300],
    )
    resp = await llm.ainvoke(prompt)
    text_out = resp.content if hasattr(resp, "content") else str(resp)
    match = re.search(r"\[.*\]", text_out, re.S)
    if not match:
        raise ValueError(f"no JSON array in LLM reply: {text_out[:200]}")
    items = json.loads(match.group(0))
    return [
        {
            "author": str(it.get("author") or "匿名"),
            "rating": max(1, min(5, int(it.get("rating") or 5))),
            "content": str(it.get("content") or ""),
        }
        for it in items
        if it.get("content")
    ]


async def seed_reviews_for_all(per_product: int = 30, limit: int | None = None) -> int:
    llm = LLMFactory.get_chat_llm()
    async with AsyncSessionLocal() as db:
        res = await db.execute(text("""
            SELECT p.id, p.title, p.category, p.description,
                   (SELECT count(*) FROM product_reviews r
                    WHERE r.product_id = p.id AND r.source='generated') AS existing
            FROM products p
            WHERE p.is_active = TRUE
            ORDER BY p.created_at
        """))
        rows = res.fetchall()
        total = 0
        for row in rows:
            product = {
                "id": row[0], "title": row[1], "category": row[2],
                "description": row[3], "existing": row[4],
                "n": per_product - int(row[4]),
            }
            if limit is not None and total >= limit:
                break
            if product["n"] <= 0:
                logger.info("seed.skip", title=product["title"], reason="enough reviews")
                continue
            try:
                items = await _gen_reviews(llm, product)
            except Exception as e:
                logger.warning("seed.llm_failed", title=product["title"], error=str(e))
                continue
            for it in items:
                await db.execute(
                    text("""
                        INSERT INTO product_reviews (product_id, author, rating, content, source)
                        VALUES (:pid, :author, :rating, :content, 'generated')
                    """),
                    {"pid": product["id"], "author": it["author"],
                     "rating": it["rating"], "content": it["content"]},
                )
            await db.commit()
            total += 1
            logger.info("seed.done", title=product["title"], added=len(items))
        return total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-product", type=int, default=30)
    parser.add_argument("--limit", type=int, default=None, help="最多处理几个商品")
    args = parser.parse_args()
    n = asyncio.run(seed_reviews_for_all(args.per_product, args.limit))
    print(f"✅ 完成：{n} 个商品生成评价")


if __name__ == "__main__":
    main()
```

注：`LLMFactory.get_chat_llm()` 为占位名，实现时先 `rg "def get|class LLMFactory" backend/core/llm_factory.py` 核对实际方法名（常见为 `get_llm()` / `create_chat_model()`），以实际为准替换——**只改这一处调用**。

- [ ] **Step 4: 运行冒烟测试**

Run: `$env:MIMO_PYTHON -m pytest scripts/manual_tests/test_seed_reviews.py -v -s`
Expected: PASS；`product_reviews` 出现 3+ 行 `generated` 记录

- [ ] **Step 5: 为前 5 个商品批量生成**

Run: `$env:MIMO_PYTHON -m scripts.seed_product_reviews --per-product 30 --limit 5`
Expected: 5 个商品各 30 条，控制台 `seed.done` 5 次

---

### Task 7: Milvus 商品知识集合

**Files:**
- Create: `scripts/init_milvus_product.py`
- Test: 手动验证（Run 命令 + 断言输出）

**Interfaces:**
- Consumes: `backend.config.get_settings().milvus_host/milvus_port`；现有 `scripts/init_milvus.py` 的 schema/index 构建模式（参考不改）
- Produces: 集合 `product_knowledge`，字段：`id`(VARCHAR,PK), `embedding`(FLOAT_VECTOR,1024), `sparse_embedding`, `content`, `tenant_id`, `chunk_index`, `product_id`, `source_name`；**不动**旧集合 `knowledge_domain`

- [ ] **Step 1: 实现建集合脚本**

新建 `scripts/init_milvus_product.py`：

```python
# scripts/init_milvus_product.py
# 执行：python scripts/init_milvus_product.py
# 商品知识库独立集合（旧 knowledge_domain 课程集合保留，M2 切换 QA 后再清理）。
from pymilvus import MilvusClient, DataType

from backend.config import get_settings

MILVUS_URI = f"http://{get_settings().milvus_host}:{get_settings().milvus_port}"
VECTOR_DIM = 1024
COLLECTION_NAME = "product_knowledge"


def build_schema(client: MilvusClient):
    schema = client.create_schema(auto_id=False, enable_dynamic_field=True)
    schema.add_field("id",               DataType.VARCHAR, is_primary=True, max_length=64)
    schema.add_field("embedding",        DataType.FLOAT_VECTOR, dim=VECTOR_DIM)
    schema.add_field("sparse_embedding", DataType.SPARSE_FLOAT_VECTOR)
    schema.add_field("content",          DataType.VARCHAR, max_length=4096)
    schema.add_field("tenant_id",        DataType.VARCHAR, max_length=64)
    schema.add_field("chunk_index",      DataType.INT64)
    schema.add_field("product_id",       DataType.VARCHAR, max_length=64)
    schema.add_field("source_name",      DataType.VARCHAR, max_length=256)
    schema.add_field("updated_at",       DataType.INT64)
    return schema


def build_index_params(client: MilvusClient):
    ip = client.prepare_index_params()
    ip.add_index(field_name="embedding", index_type="HNSW", metric_type="COSINE",
                 params={"M": 16, "efConstruction": 256})
    ip.add_index(field_name="sparse_embedding", index_type="SPARSE_INVERTED_INDEX",
                 metric_type="IP", params={"drop_ratio_build": 0.2})
    ip.add_index(field_name="tenant_id", index_type="INVERTED")
    ip.add_index(field_name="product_id", index_type="INVERTED")
    return ip


def main():
    print(f"连接 Milvus：{MILVUS_URI}")
    client = MilvusClient(uri=MILVUS_URI)
    if client.has_collection(COLLECTION_NAME):
        print(f"🗑️  删除旧集合 '{COLLECTION_NAME}'...")
        client.drop_collection(COLLECTION_NAME)
    client.create_collection(
        collection_name=COLLECTION_NAME,
        schema=build_schema(client),
        index_params=build_index_params(client),
    )
    print(f"✅ 集合 '{COLLECTION_NAME}' 创建完成（含索引，已加载）")
    print("当前集合：", client.list_collections())


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 运行验证**

Run: `$env:MIMO_PYTHON scripts/init_milvus_product.py`
Expected: `✅ 集合 'product_knowledge' 创建完成`；`list_collections` 同时含 `knowledge_domain` 与 `product_knowledge`

---

### Task 8: 商品知识索引构建

**Files:**
- Create: `scripts/build_product_knowledge.py`
- Test: `scripts/manual_tests/test_product_knowledge.py`（新建，需 PG + Milvus + 本地嵌入模型）

**Interfaces:**
- Consumes: Task 1 `products` 表；Task 7 集合 `product_knowledge`；现有 `backend.core.knowledge_base.BGEMEmbedder`（dense+sparse 双输出，进程内单例）
- Produces: 命令 `python -m scripts.build_product_knowledge --limit 10`；每个商品切成「标题+类目+价格行」「参数 JSON 行」「描述段落」若干 chunk，写入集合；`id = f"prod_{product_id}_{chunk_index}"`（幂等覆盖写）

- [ ] **Step 1: 写冒烟测试**

新建 `scripts/manual_tests/test_product_knowledge.py`：

```python
# scripts/manual_tests/test_product_knowledge.py
# 需要：PG 有商品、Milvus product_knowledge 已建、本地 bge-m3 权重可用
import asyncio

from sqlalchemy import text

from backend.dependencies import AsyncSessionLocal
from scripts.build_product_knowledge import build_for_products


def test_build_and_query():
    asyncio.run(_run())


async def _run():
    async with AsyncSessionLocal() as db:
        res = await db.execute(text("SELECT id FROM products WHERE is_active LIMIT 1"))
        row = res.fetchone()
        assert row, "no product in PG — run crawl first"
        product_id = str(row[0])

    n = await build_for_products(limit=1)
    assert n >= 1

    # 标量过滤 query 而非向量 search：只验证「写入成功」，不依赖嵌入质量
    from backend.config import get_settings
    from pymilvus import MilvusClient
    client = MilvusClient(uri=f"http://{get_settings().milvus_host}:{get_settings().milvus_port}")
    res = client.query(
        collection_name="product_knowledge",
        filter=f'product_id == "{product_id}"',
        output_fields=["chunk_index", "content"],
        limit=5,
    )
    assert len(res) >= 1
```

- [ ] **Step 2: 运行确认失败**

Run: `$env:MIMO_PYTHON -m pytest scripts/manual_tests/test_product_knowledge.py -v -s`
Expected: FAIL，`ModuleNotFoundError: scripts.build_product_knowledge`

- [ ] **Step 3: 实现构建脚本**

新建 `scripts/build_product_knowledge.py`：

```python
# scripts/build_product_knowledge.py
# 用法：python -m scripts.build_product_knowledge --limit 10
# 商品 → 文本 chunk → BGE-M3(dense+sparse) → 写入 product_knowledge（幂等覆盖）
import argparse
import asyncio
import json
import time

from sqlalchemy import text

from backend.core.knowledge_base import BGEMEmbedder
from backend.core.logger import get_logger
from backend.dependencies import AsyncSessionLocal
from pymilvus import MilvusClient

from backend.config import get_settings

logger = get_logger(__name__)
COLLECTION = "product_knowledge"


def _chunk_product(row) -> list[str]:
    """title/category/price 行 + 参数 + 描述段落 → chunk 列表。"""
    chunks = [
        f"{row['title']}｜类目：{row['category'] or '未分类'}｜价格：{row['price']} {row['currency']}"
    ]
    params = row["params"] or {}
    if params:
        # 参数按 6 个键一块切，避免超长
        items = list(params.items())
        for i in range(0, len(items), 6):
            part = "；".join(f"{k}：{v}" for k, v in items[i:i + 6])
            chunks.append(f"{row['title']} 规格参数：{part}")
    desc = (row["description"] or "").strip()
    if desc:
        step = 800
        for i in range(0, len(desc), step):
            chunks.append(f"{row['title']} 商品介绍：{desc[i:i + step]}")
    return chunks


async def build_for_products(limit: int | None = None, tenant_id: str = "tenant_default") -> int:
    embedder = BGEMEmbedder.get_instance()
    client = MilvusClient(uri=f"http://{get_settings().milvus_host}:{get_settings().milvus_port}")

    async with AsyncSessionLocal() as db:
        sql = """
            SELECT id, title, category, price, currency, description, params
            FROM products WHERE is_active = TRUE ORDER BY created_at
        """
        if limit:
            sql += f" LIMIT {int(limit)}"
        res = await db.execute(text(sql))
        rows = res.mappings().all()

    count = 0
    for row in rows:
        pid = str(row["id"])
        chunks = _chunk_product(row)
        ids, dense, sparse, contents = [], [], [], []
        for idx, content in enumerate(chunks):
            ids.append(f"prod_{pid}_{idx}")
            contents.append(content[:4096])
            d, s = embedder.encode(content)          # dense+sparse 双输出
            dense.append(d)
            sparse.append(s)
            # 同 id 重复插入会报错，先删后插（幂等重建）
            try:
                client.delete(COLLECTION, filter=f'id == "prod_{pid}_{idx}"')
            except Exception:
                pass
        # 批量插入
        now = int(time.time())
        client.insert(COLLECTION, data=[
            {
                "id": ids[i], "embedding": dense[i], "sparse_embedding": sparse[i],
                "content": contents[i], "tenant_id": tenant_id, "chunk_index": i,
                "product_id": pid, "source_name": row["title"][:256], "updated_at": now,
            }
            for i in range(len(ids))
        ])
        count += 1
        logger.info("kb.product_indexed", title=row["title"], chunks=len(chunks))
    return count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    n = asyncio.run(build_for_products(args.limit))
    print(f"✅ 完成：{n} 个商品已入向量索引")


if __name__ == "__main__":
    main()
```

注：`BGEMEmbedder.encode` 的真实签名（是否返回 `(dense, sparse)` 元组、是否需 `encode_documents`）以 `backend/core/knowledge_base.py` 实际实现为准，参考 `scripts/build_knowledge_base.py` 现有调用方式对齐——**只改本脚本的调用行**。

- [ ] **Step 4: 运行冒烟测试**

Run: `$env:MIMO_PYTHON -m pytest scripts/manual_tests/test_product_knowledge.py -v -s`
Expected: PASS

- [ ] **Step 5: 为已入库商品全量建索引**

Run: `$env:MIMO_PYTHON -m scripts.build_product_knowledge`
Expected: 每商品打印 `kb.product_indexed`；`product_knowledge` 行数 > 商品数（每商品多 chunk）

---

### Task 9: `/products` API（列表/详情/图片）

**Files:**
- Create: `backend/api/v1/products.py`
- Modify: `backend/api/router.py:5-15`（import 与 include_router 各加一行）
- Test: `scripts/manual_tests/test_products_api.py`（新建，需后端运行）

**Interfaces:**
- Consumes: Task 1 `products` 表；Task 2 `storage.download_product_image`；`backend.dependencies.get_current_user`（沿用现有 JWT 依赖）
- Produces（后续任务与前端 M2 依赖的精确契约）:
  - `GET /api/v1/products?page=1&page_size=20&category=&keyword=` → `{"total": int, "items": [{"id": str(uuid), "title": str, "category": str|null, "price": str, "currency": str, "rating": int|null, "image_url": str|null}]}`
  - `GET /api/v1/products/{product_id}` → `{"id", "title", "category", "price", "currency", "description", "params": dict, "rating", "url", "source", "image_url", "review_count": int}`
  - `GET /api/v1/products/{product_id}/image` → 图片二进制流（`Content-Type` 来自 MinIO）
  - `image_url` 字段值固定为 `"/api/v1/products/{id}/image"`（无图则 `null`）
  - 404：商品不存在 / 未登录 401（`get_current_user` 现有行为）

- [ ] **Step 1: 写冒烟测试**

新建 `scripts/manual_tests/test_products_api.py`：

```python
# scripts/manual_tests/test_products_api.py
# 运行前置：后端 uvicorn 运行中 + 已爬取商品 + 已有登录账号（seed_data.py 的 student）
# 运行：python -m pytest scripts/manual_tests/test_products_api.py -v -s
import httpx
import pytest

BASE = "http://localhost:8000"


def _token() -> str:
    r = httpx.post(f"{BASE}/api/v1/auth/login", json={
        "email": "student@eduagent.com", "password": "Student@123456",
    })
    if r.status_code != 200:
        pytest.skip(f"login failed: {r.status_code} {r.text[:200]}")
    body = r.json()
    return body.get("access_token") or body.get("token")


def _headers():
    return {"Authorization": f"Bearer {_token()}"}


def test_product_list():
    r = httpx.get(f"{BASE}/api/v1/products", params={"page": 1, "page_size": 5}, headers=_headers())
    assert r.status_code == 200, r.text
    body = r.json()
    assert "total" in body and "items" in body
    if body["items"]:
        item = body["items"][0]
        for key in ("id", "title", "price", "currency", "image_url"):
            assert key in item


def test_product_detail_and_image():
    r = httpx.get(f"{BASE}/api/v1/products", params={"page_size": 1}, headers=_headers())
    items = r.json()["items"]
    if not items:
        pytest.skip("no products — run crawler first")
    pid = items[0]["id"]
    r = httpx.get(f"{BASE}/api/v1/products/{pid}", headers=_headers())
    assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["params"] is None or isinstance(detail["params"], dict)
    assert "review_count" in detail

    if detail["image_url"]:
        r = httpx.get(f"{BASE}{detail['image_url']}", headers=_headers())
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/")


def test_product_not_found():
    r = httpx.get(
        f"{BASE}/api/v1/products/00000000-0000-0000-0000-000000000000",
        headers=_headers(),
    )
    assert r.status_code == 404
```

- [ ] **Step 2: 运行确认失败（后端未挂新路由 → 404/405）**

Run: `$env:MIMO_PYTHON -m pytest scripts/manual_tests/test_products_api.py -v -s`
Expected: FAIL（404 on list endpoint）

- [ ] **Step 3: 实现 products 路由**

新建 `backend/api/v1/products.py`：

```python
# backend/api/v1/products.py
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import text

from backend.core import storage
from backend.core.logger import get_logger
from backend.dependencies import AsyncSessionLocal, get_current_user

router = APIRouter()
logger = get_logger(__name__)


@router.get("")
async def list_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = None,
    keyword: str | None = None,
    current_user: dict = Depends(get_current_user),
):
    """商品列表：类目筛选 + 关键词搜索 + 分页。"""
    filters, params = ["is_active = TRUE"], {}
    if category:
        filters.append("category = :category")
        params["category"] = category
    if keyword:
        filters.append("(title ILIKE :kw OR description ILIKE :kw)")
        params["kw"] = f"%{keyword}%"
    where = " AND ".join(filters)

    async with AsyncSessionLocal() as db:
        total = (await db.execute(
            text(f"SELECT count(*) FROM products WHERE {where}"), params
        )).scalar()
        rows = (await db.execute(
            text(f"""
                SELECT id, title, category, price, currency, rating, image_object
                FROM products WHERE {where}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {**params, "limit": page_size, "offset": (page - 1) * page_size},
        )).mappings().all()

    return {
        "total": total,
        "items": [
            {
                "id": str(r["id"]),
                "title": r["title"],
                "category": r["category"],
                "price": str(r["price"]),
                "currency": r["currency"],
                "rating": r["rating"],
                "image_url": f"/api/v1/products/{r['id']}/image" if r["image_object"] else None,
            }
            for r in rows
        ],
    }


@router.get("/{product_id}")
async def get_product(product_id: str, current_user: dict = Depends(get_current_user)):
    """商品详情（含参数、评价数）。"""
    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            text("""
                SELECT id, title, category, price, currency, description, params,
                       rating, url, source, image_object,
                       (SELECT count(*) FROM product_reviews r WHERE r.product_id = p.id) AS review_count
                FROM products p
                WHERE id = :pid AND is_active = TRUE
            """),
            {"pid": product_id},
        )).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="product not found")

    params = row["params"]
    if isinstance(params, str):
        params = json.loads(params)
    return {
        "id": str(row["id"]),
        "title": row["title"],
        "category": row["category"],
        "price": str(row["price"]),
        "currency": row["currency"],
        "description": row["description"],
        "params": params or {},
        "rating": row["rating"],
        "url": row["url"],
        "source": row["source"],
        "image_url": f"/api/v1/products/{row['id']}/image" if row["image_object"] else None,
        "review_count": row["review_count"],
    }


@router.get("/{product_id}/image")
async def get_product_image(product_id: str, current_user: dict = Depends(get_current_user)):
    """商品主图：从 MinIO 读出并透传（MVP 直连，后续可换预签名 URL）。"""
    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            text("SELECT image_object FROM products WHERE id = :pid"), {"pid": product_id}
        )).first()
    if row is None or not row[0]:
        raise HTTPException(status_code=404, detail="image not found")
    try:
        data, content_type = storage.download_product_image(row[0])
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="image object missing")
    return Response(content=data, media_type=content_type)
```

- [ ] **Step 4: 挂载路由**

`backend/api/router.py` 第 5 行 import 改为：

```python
from backend.api.v1 import auth, qa, exam, resume, interview, unified_chat, products
```

include_router 块末尾追加：

```python
api_router.include_router(products.router, prefix="/products", tags=["商品"])   # M1 轻量外壳
```

（Task 10 会在此 import 与块中继续追加 `orders`。）

- [ ] **Step 5: 运行冒烟测试**

重启后端后 Run: `$env:MIMO_PYTHON -m pytest scripts/manual_tests/test_products_api.py -v -s`
Expected: 3 passed（无商品时 detail 用例 skip 属预期，先跑 Task 5 爬虫）

- [ ] **Step 6: 回归现有接口**

Run: `Invoke-WebRequest http://localhost:8000/health`，再访问 `http://localhost:8000/docs` 查看 `/api/v1/products` 出现
Expected: health ok；docs 中 products 三接口可见；原 qa/exam 等路由不受影响

---

### Task 10: `/orders` API（模拟下单/查询/支付）

**Files:**
- Create: `backend/api/v1/orders.py`
- Modify: `backend/api/router.py:5`（import 追加 `orders`）与 include_router 块（追加 orders 行）
- Test: `scripts/manual_tests/test_orders_api.py`（新建，需后端运行）

**Interfaces:**
- Consumes: Task 1 `orders` 表；Task 9 的商品数据（下单时读 `products.price` 快照）
- Produces:
  - `POST /api/v1/orders` body `{"product_id": str, "quantity": int>=1, "receiver": str, "address": str}` → `{"id", "status": "created", "unit_price", "total_amount", "currency"}`；404 商品不存在；价格**从库读取**，请求不携带价格
  - `GET /api/v1/orders?page=1&page_size=20` → 当前用户订单列表 `{"total", "items": [{"id","product_id","product_title","quantity","unit_price","total_amount","currency","receiver","address","status","created_at"}]}`
  - `GET /api/v1/orders/{order_id}` → 单个订单（同结构 + 404）
  - `POST /api/v1/orders/{order_id}/pay` → 模拟支付，`status: created → paid`；已非 created 状态返回 409
  - 401 未登录

- [ ] **Step 1: 写冒烟测试**

新建 `scripts/manual_tests/test_orders_api.py`：

```python
# scripts/manual_tests/test_orders_api.py
# 运行前置：后端运行中 + 有商品 + student 账号
import httpx
import pytest

BASE = "http://localhost:8000"


def _headers() -> dict:
    r = httpx.post(f"{BASE}/api/v1/auth/login", json={
        "email": "student@eduagent.com", "password": "Student@123456",
    })
    if r.status_code != 200:
        pytest.skip(f"login failed: {r.status_code}")
    token = r.json().get("access_token") or r.json().get("token")
    return {"Authorization": f"Bearer {token}"}


def _first_product_id(headers: dict) -> str:
    r = httpx.get(f"{BASE}/api/v1/products", params={"page_size": 1}, headers=headers)
    items = r.json().get("items", [])
    if not items:
        pytest.skip("no products — run crawler first")
    return items[0]["id"]


def test_order_lifecycle():
    headers = _headers()
    pid = _first_product_id(headers)

    # 1) 下单
    r = httpx.post(f"{BASE}/api/v1/orders", json={
        "product_id": pid, "quantity": 2,
        "receiver": "测试用户", "address": "上海市测试路 1 号",
    }, headers=headers)
    assert r.status_code == 200, r.text
    order = r.json()
    assert order["status"] == "created"
    assert order["quantity"] == 2
    # total = unit_price * 2（价格来自库，非请求）
    assert float(order["total_amount"]) == float(order["unit_price"]) * 2
    order_id = order["id"]

    # 2) 模拟支付
    r = httpx.post(f"{BASE}/api/v1/orders/{order_id}/pay", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "paid"

    # 3) 重复支付 → 409
    r = httpx.post(f"{BASE}/api/v1/orders/{order_id}/pay", headers=headers)
    assert r.status_code == 409

    # 4) 列表含该订单
    r = httpx.get(f"{BASE}/api/v1/orders", headers=headers)
    assert r.status_code == 200
    ids = [o["id"] for o in r.json()["items"]]
    assert order_id in ids

    # 5) 详情
    r = httpx.get(f"{BASE}/api/v1/orders/{order_id}", headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == "paid"


def test_order_price_cannot_be_tampered():
    headers = _headers()
    pid = _first_product_id(headers)
    r = httpx.post(f"{BASE}/api/v1/orders", json={
        "product_id": pid, "quantity": 1,
        "receiver": "x", "address": "y",
        "unit_price": 0.01,   # 恶意字段应被忽略（pydantic 不含此字段）
    }, headers=headers)
    assert r.status_code == 200, r.text
    # 单价必须来自库：与商品列表价格一致
    p = httpx.get(f"{BASE}/api/v1/products/{pid}", headers=headers).json()
    assert float(r.json()["unit_price"]) == float(p["price"])
```

- [ ] **Step 2: 运行确认失败**

Run: `$env:MIMO_PYTHON -m pytest scripts/manual_tests/test_orders_api.py -v -s`
Expected: FAIL（下单 404，路由不存在）

- [ ] **Step 3: 实现 orders 路由**

新建 `backend/api/v1/orders.py`：

```python
# backend/api/v1/orders.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from backend.core.logger import get_logger
from backend.dependencies import AsyncSessionLocal, get_current_user

router = APIRouter()
logger = get_logger(__name__)


class OrderCreateRequest(BaseModel):
    product_id: str
    quantity: int = Field(..., ge=1, le=99)
    receiver: str = Field(..., min_length=1, max_length=128)
    address: str = Field(..., min_length=1, max_length=512)


def _order_row_to_dict(r) -> dict:
    return {
        "id": str(r["id"]),
        "product_id": str(r["product_id"]),
        "product_title": r["product_title"],
        "quantity": r["quantity"],
        "unit_price": str(r["unit_price"]),
        "total_amount": str(r["total_amount"]),
        "currency": r["currency"],
        "receiver": r["receiver"],
        "address": r["address"],
        "status": r["status"],
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
    }


_ORDER_SELECT = """
    SELECT o.id, o.product_id, p.title AS product_title, o.quantity,
           o.unit_price, o.total_amount, o.currency, o.receiver, o.address,
           o.status, o.created_at
    FROM orders o
    JOIN products p ON p.id = o.product_id
"""


@router.post("")
async def create_order(req: OrderCreateRequest, current_user: dict = Depends(get_current_user)):
    """模拟下单：单价从库读取（不接受请求价格），status=created。"""
    async with AsyncSessionLocal() as db:
        product = (await db.execute(
            text("SELECT price, currency FROM products WHERE id = :pid AND is_active"),
            {"pid": req.product_id},
        )).first()
        if product is None:
            raise HTTPException(status_code=404, detail="product not found")
        unit_price, currency = product[0], product[1]
        total = round(float(unit_price) * req.quantity, 2)
        row = (await db.execute(
            text("""
                INSERT INTO orders
                    (tenant_id, user_id, product_id, quantity, unit_price, total_amount,
                     currency, receiver, address, status)
                VALUES (:tenant, :uid, :pid, :qty, :unit, :total, :cur, :recv, :addr, 'created')
                RETURNING id, status, unit_price, total_amount, currency
            """),
            {
                "tenant": current_user["tenant_id"],
                "uid": current_user["user_id"],
                "pid": req.product_id,
                "qty": req.quantity,
                "unit": unit_price,
                "total": total,
                "cur": currency,
                "recv": req.receiver,
                "addr": req.address,
            },
        )).mappings().first()
        await db.commit()
    logger.info("order.created", order_id=str(row["id"]), qty=req.quantity)
    return {
        "id": str(row["id"]),
        "status": row["status"],
        "unit_price": str(row["unit_price"]),
        "total_amount": str(row["total_amount"]),
        "currency": row["currency"],
    }


@router.get("")
async def list_orders(
    current_user: dict = Depends(get_current_user),
):
    """当前用户的订单列表（新→旧）。"""
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            text(_ORDER_SELECT + " WHERE o.user_id = :uid ORDER BY o.created_at DESC LIMIT 100"),
            {"uid": current_user["user_id"]},
        )).mappings().all()
    return {"total": len(rows), "items": [_order_row_to_dict(r) for r in rows]}


@router.get("/{order_id}")
async def get_order(order_id: str, current_user: dict = Depends(get_current_user)):
    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            text(_ORDER_SELECT + " WHERE o.id = :oid AND o.user_id = :uid"),
            {"oid": order_id, "uid": current_user["user_id"]},
        )).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="order not found")
    return _order_row_to_dict(row)


@router.post("/{order_id}/pay")
async def pay_order(order_id: str, current_user: dict = Depends(get_current_user)):
    """模拟支付：created → paid；重复/非法状态 409。"""
    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            text("SELECT status FROM orders WHERE id = :oid AND user_id = :uid"),
            {"oid": order_id, "uid": current_user["user_id"]},
        )).first()
        if row is None:
            raise HTTPException(status_code=404, detail="order not found")
        if row[0] != "created":
            raise HTTPException(status_code=409, detail=f"cannot pay order in status {row[0]}")
        await db.execute(
            text("UPDATE orders SET status = 'paid' WHERE id = :oid"),
            {"oid": order_id},
        )
        await db.commit()
    logger.info("order.paid", order_id=order_id)
    return {"id": order_id, "status": "paid"}
```

- [ ] **Step 4: 挂载路由**

`backend/api/router.py` 第 5 行 import 改为：

```python
from backend.api.v1 import auth, qa, exam, resume, interview, unified_chat, products, orders
```

include_router 块末尾追加：

```python
api_router.include_router(orders.router, prefix="/orders", tags=["订单"])      # M1 轻量外壳
```

- [ ] **Step 5: 运行冒烟测试**

重启后端后 Run: `$env:MIMO_PYTHON -m pytest scripts/manual_tests/test_orders_api.py -v -s`
Expected: 2 passed

- [ ] **Step 6: 全量 M1 回归**

Run 顺序（一次性验证 M1 全链路）：

```powershell
$env:MIMO_PYTHON -m pytest tests/ -v                          # 单测全绿
$env:MIMO_PYTHON -m scripts.crawl.run_crawl --limit 5         # 幂等爬虫再跑通
$env:MIMO_PYTHON -m scripts.seed_product_reviews --limit 1    # 评价幂等跳过/补生成
$env:MIMO_PYTHON -m scripts.build_product_knowledge --limit 3 # 向量重建
$env:MIMO_PYTHON -m pytest scripts/manual_tests/test_products_api.py scripts/manual_tests/test_orders_api.py -v
```

Expected: 全部通过；`http://localhost:8000/docs` 可见 `/api/v1/products`、`/api/v1/orders`；旧 `/api/v1/qa` 等路由正常。

---

## M1 完成定义（DoD）

- [ ] 7 张电商表存在且幂等迁移可重复执行
- [ ] `python -m scripts.crawl.run_crawl --limit 30` 入库 30 商品（图片入 MinIO）
- [ ] 5 个商品 × 30 条种子评价入库（`source='generated'`）
- [ ] `product_knowledge` 集合存在且已商品已入索引，旧 `knowledge_domain` 未动
- [ ] `/api/v1/products` 列表/详情/图片、`/api/v1/orders` 下单/列表/详情/支付全部冒烟通过
- [ ] 现有 EduAgent 四个 Agent 的 `/docs` 路由与 health 回归正常

## 明确不做（M1 范围外，勿顺手实现）

- 前端任何页面（M2：ProductList/Detail 视图）
- QA/意图分类器切换到商品知识库（M2）
- `service_tickets` 的业务逻辑（M4，仅 Task 1 建表）
- `recommendation_sessions/results` 的业务逻辑（M5，仅 Task 1 建表）
- 旧教育表与旧 Milvus 集合的删除（M5 清理）


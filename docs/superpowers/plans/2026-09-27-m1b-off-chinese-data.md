# M1b 中文商品数据（Open Food Facts）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把商品数据源从英文书目切换为 Open Food Facts 中国区真实中文商品（首批 100 个），LLM 补全价格/详情/评价，重建向量索引，使 `/products` 全链路只呈现中文商品。

**Architecture:** 纯数据层切换，不改 API/前端/表结构：① 旧英文商品软下架（`is_active=FALSE`）；② 新增 OFF API 拉取入库脚本（字段映射 + 图片入 MinIO）；③ DeepSeek 补价格与详情文案；④ 复用既有种子脚本生成中文评价并回填 rating；⑤ 重建 `product_knowledge` 集合（仅 active 商品）+ 全量回归。

**Tech Stack:** Open Food Facts Search API v2（免鉴权）、DeepSeek（经 `LLMFactory`）、MinIO、pymilvus、pytest。

**Spec:** `docs/superpowers/specs/2026-09-27-ecommerce-rework-design.md` §1/§3.2/§3.3（2026-09-27 变更后）

## Global Constraints

- Python 解释器：`& "D:\ProgramTools\Anaconda3\envs\Edu_Agent\python.exe" -m ...`（conda Edu_Agent）。
- OFF API 礼貌约束：单请求间隔 ≥2s 随机抖动、显式 UA、失败重试；增量幂等靠 `UNIQUE(source, external_id)` upsert。
- 价格/文案/评价均为 LLM 生成的**演示数据**，入库后以库为准（spec §6.1）；价格 `currency='CNY'`。
- 旧英文商品**只下架不删除**（`is_active=FALSE`），其订单/评价等 FK 数据不动。
- 不改任何表结构、不改 API 路由、不动 `scripts/crawl/`（保留作适配器参考）。
- `requirements.txt` 已有依赖不升级；不执行 git 命令。
- LLM 调用用 `LLMFactory.get_llm("summarize")`（M1 Task 6 已验证的真实入口），`await llm.ainvoke(prompt)` 取 `.content`。

## OFF API 实测事实（2026-09-27 验证，直接采用）

- 搜索端点：`GET https://world.openfoodfacts.org/api/v2/search?countries_tags_en=china&page_size={n}&page={p}&fields={csv}`
- 实测 `fields=code,product_name,product_name_zh,brands,categories,image_front_url` 返回 `count=1684`，`product_name_zh` 为真实中文名（如「百岁山 饮用天然矿泉水」）
- 追加字段 `ingredients_text_zh,quantity,product_quantity,nutriments` 一并请求（个别商品缺省为 null，入库降级）
- 响应结构：`{"count":…,"page":…,"page_size":…,"products":[…]}`
- 客户端过滤：仅保留 `product_name_zh` 非空的商品

---

### Task 1: 下架英文书目商品

**Files:**
- Create: `scripts/retire_source.py`
- Test: `scripts/manual_tests/test_retire_source.py`

**Interfaces:**
- Consumes: 表 `products`（`source='books_toscrape'` 共 29 行，均 `is_active=TRUE`）
- Produces: `retire_source(source: str) -> int`（返回下架行数，幂等——重复执行返回 0）；下架后所有 `is_active=TRUE` 查询不再返回英文商品

- [ ] **Step 1: 写失败测试**

新建 `scripts/manual_tests/test_retire_source.py`：

```python
# scripts/manual_tests/test_retire_source.py
# 需要 PG 运行；验证 retire_source 幂等且只动指定 source
import asyncio

from sqlalchemy import text

from backend.dependencies import AsyncSessionLocal
from scripts.retire_source import retire_source


def test_retire_books_idempotent():
    asyncio.run(_run())


async def _run():
    n1 = await retire_source("books_toscrape")
    n2 = await retire_source("books_toscrape")
    assert n1 >= 1, "expected at least one active book to retire"
    assert n2 == 0, "second run must be a no-op"
    async with AsyncSessionLocal() as s:
        active_books = (await s.execute(text(
            "SELECT count(*) FROM products WHERE source='books_toscrape' AND is_active"
        ))).scalar()
        assert active_books == 0
        # 其他 source 不受影响（OFF 尚未入库时为 0 行，不作断言）
        total = (await s.execute(text(
            "SELECT count(*) FROM products WHERE source='books_toscrape'"
        ))).scalar()
        assert total >= n1, "rows must exist (soft delete, not hard delete)"
```

- [ ] **Step 2: 运行确认失败**

Run: `& $py -m pytest scripts/manual_tests/test_retire_source.py -v`
Expected: FAIL，`ModuleNotFoundError: scripts.retire_source`（`$py = D:\ProgramTools\Anaconda3\envs\Edu_Agent\python.exe`）

- [ ] **Step 3: 实现**

新建 `scripts/retire_source.py`：

```python
# scripts/retire_source.py
# 用法：python -m scripts.retire_source --source books_toscrape
# 软下架指定来源商品（is_active=FALSE），不删除行（订单/评价 FK 不受影响）。幂等。
import argparse
import asyncio

from sqlalchemy import text

from backend.core.logger import get_logger
from backend.dependencies import AsyncSessionLocal

logger = get_logger(__name__)


async def retire_source(source: str) -> int:
    async with AsyncSessionLocal() as s:
        res = await s.execute(
            text("UPDATE products SET is_active = FALSE, updated_at = NOW() "
                 "WHERE source = :src AND is_active"),
            {"src": source},
        )
        await s.commit()
        n = res.rowcount or 0
    logger.info("retire.done", source=source, count=n)
    return n


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    args = parser.parse_args()
    print(f"✅ 下架 {asyncio.run(retire_source(args.source))} 个商品")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `& $py -m pytest scripts/manual_tests/test_retire_source.py -v`
Expected: PASS（n1=29，n2=0）

- [ ] **Step 5: 验证 API 只见中文（此时列表应为空，属预期）**

启动后端，带 token `GET /api/v1/products`，Expected: `{"total": 0, "items": []}`（OFF 未入库）。验证后停后端。

---

### Task 2: OFF 拉取入库

**Files:**
- Create: `scripts/ingest_off.py`
- Test: `scripts/manual_tests/test_ingest_off.py`

**Interfaces:**
- Consumes: Task 1 后的 `products` 表；`backend.core.storage`（Task M1-2 已有）；OFF API（见 Global Constraints 实测事实）
- Produces:
  - `async def ingest_off(limit: int = 100, tenant_id: str = "tenant_default") -> int`——拉取→过滤中文名→下载主图入 MinIO→upsert `products`；`source='openfoodfacts'`、`external_id=code`、`currency='CNY'`、`price=NULL`（Task 3 补）、`params` 含 brands/quantity/ingredients/nutriments
  - 命令 `python -m scripts.ingest_off --limit 100`
  - 幂等：重复跑走 `ON CONFLICT (source, external_id) DO UPDATE`

- [ ] **Step 1: 写冒烟测试**

新建 `scripts/manual_tests/test_ingest_off.py`：

```python
# scripts/manual_tests/test_ingest_off.py
# 需要：PG + MinIO 运行、网络可达 world.openfoodfacts.org（限速，3 个商品约 30s）
import asyncio

from sqlalchemy import text

from backend.dependencies import AsyncSessionLocal
from scripts.ingest_off import ingest_off


def test_ingest_three_chinese_products():
    asyncio.run(_run())


async def _run():
    n = await ingest_off(limit=3)
    assert n >= 3
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(text(
            "SELECT title, currency, image_object, price FROM products "
            "WHERE source='openfoodfacts' AND is_active LIMIT 5"
        ))).fetchall()
        assert len(rows) >= 3
        for title, currency, image_object, price in rows:
            assert any('一' <= ch <= '鿿' for ch in title), f"not Chinese: {title}"
            assert currency == "CNY"
            assert image_object and image_object.startswith("products/")
            assert price is None, "price must stay NULL until enrich (Task 3)"
```

- [ ] **Step 2: 运行确认失败**

Run: `& $py -m pytest scripts/manual_tests/test_ingest_off.py -v`
Expected: FAIL，`ModuleNotFoundError: scripts.ingest_off`

- [ ] **Step 3: 实现**

新建 `scripts/ingest_off.py`：

```python
# scripts/ingest_off.py
# 用法：python -m scripts.ingest_off --limit 100
# Open Food Facts 中国区商品拉取入库（免鉴权 API；礼貌限速 ≥2s；价格留空由 enrich 补）
import argparse
import asyncio
import json
import random
import time
from urllib.parse import urlparse

import httpx
from sqlalchemy import text

from backend.core import storage
from backend.core.logger import get_logger
from backend.dependencies import AsyncSessionLocal

logger = get_logger(__name__)

SEARCH_URL = "https://world.openfoodfacts.org/api/v2/search"
FIELDS = ("code,product_name_zh,brands,categories,quantity,product_quantity,"
          "ingredients_text_zh,nutriments,image_front_url")
USER_AGENT = "ShopPilotDemo/0.1 (local MVP; open data import)"
PAGE_SIZE = 50

_UPSERT = """
    INSERT INTO products
        (tenant_id, external_id, source, title, category, price, currency,
         description, params, image_object, rating, url)
    VALUES
        (:tenant_id, :external_id, 'openfoodfacts', :title, :category, NULL, 'CNY',
         NULL, :params, :image_object, NULL, :url)
    ON CONFLICT (source, external_id) DO UPDATE SET
        title = EXCLUDED.title,
        category = EXCLUDED.category,
        params = EXCLUDED.params,
        image_object = EXCLUDED.image_object,
        url = EXCLUDED.url,
        updated_at = NOW()
"""

_IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")


def _throttle():
    time.sleep(2.0 + random.uniform(0.0, 1.0))


async def _fetch_page(client: httpx.AsyncClient, page: int) -> list[dict]:
    _throttle()
    resp = await client.get(SEARCH_URL, params={
        "countries_tags_en": "china",
        "page_size": PAGE_SIZE,
        "page": page,
        "fields": FIELDS,
    }, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    return resp.json().get("products", [])


def _pick_category(raw: str | None) -> str | None:
    if not raw:
        return None
    # OFF categories 形如 "Waters, bottled"，取首段作大类
    return raw.split(",")[0].strip() or None


def _clean_params(p: dict) -> dict:
    out = {}
    if p.get("brands"):
        out["品牌"] = str(p["brands"])[:200]
    if p.get("quantity"):
        out["规格"] = str(p["quantity"])[:100]
    if p.get("ingredients_text_zh"):
        out["配料"] = str(p["ingredients_text_zh"])[:500]
    nutri = p.get("nutriments") or {}
    if isinstance(nutri, dict):
        keep = {k: v for k, v in nutri.items()
                if k.endswith("_100g") and isinstance(v, (int, float))}
        if keep:
            out["营养成分(每100g)"] = {k.replace("_100g", ""): round(float(v), 2)
                                       for k, v in list(keep.items())[:8]}
    return out


async def _download_image(client: httpx.AsyncClient, url: str, external_id: str) -> str | None:
    path = urlparse(url).path.lower()
    ext = next((e for e in _IMG_EXT if path.endswith(e)), None)
    if ext is None:
        return None
    _throttle()
    try:
        resp = await client.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        logger.warning("off.image_failed", code=external_id, error=str(e))
        return None
    object_name = f"products/{external_id}/0{ext}"
    ctype = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
             "png": "image/png", "webp": "image/webp"}[ext.lstrip(".")]
    await asyncio.to_thread(storage.upload_product_image, object_name, resp.content, ctype)
    return object_name


async def ingest_off(limit: int = 100, tenant_id: str = "tenant_default") -> int:
    storage.ensure_bucket()
    collected: list[dict] = []
    page = 1
    async with httpx.AsyncClient() as client:
        while len(collected) < limit:
            batch = await _fetch_page(client, page)
            if not batch:
                break
            for p in batch:
                title = (p.get("product_name_zh") or "").strip()
                if title and p.get("code"):
                    collected.append(p)
                if len(collected) >= limit:
                    break
            page += 1
        logger.info("off.fetched", count=len(collected), pages=page - 1)

        count = 0
        async with AsyncSessionLocal() as db:
            for p in collected:
                code = str(p["code"])
                image_object = None
                if p.get("image_front_url"):
                    image_object = await _download_image(client, p["image_front_url"], code)
                await db.execute(text(_UPSERT), {
                    "tenant_id": tenant_id,
                    "external_id": code,
                    "title": str(p["product_name_zh"]).strip()[:500],
                    "category": _pick_category(p.get("categories")),
                    "params": json.dumps(_clean_params(p), ensure_ascii=False),
                    "image_object": image_object,
                    "url": f"https://world.openfoodfacts.org/product/{code}",
                })
                await db.commit()
                count += 1
                logger.info("off.ingested", code=code,
                            title=str(p["product_name_zh"])[:40], n=count)
    return count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    n = asyncio.run(ingest_off(args.limit))
    print(f"✅ 完成：入库/更新 {n} 个中文商品（价格待 enrich）")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行冒烟测试**

Run: `& $py -m pytest scripts/manual_tests/test_ingest_off.py -v`（限速 + 下载，约 1~2 分钟）
Expected: PASS（标题为中文、CNY、图片入 MinIO、price 为 None）

- [ ] **Step 5: 批量入库**

Run: `& $py -m scripts.ingest_off --limit 100`（约 100×2.5s×2 请求 ≈ 8~10 分钟，超时给 20 分钟）
Verify: `SELECT count(*), count(image_object) FROM products WHERE source='openfoodfacts' AND is_active;` → 第一列 ≥90，第二列接近第一列

---

### Task 3: LLM 补价格与详情文案

**Files:**
- Create: `scripts/enrich_off_products.py`
- Test: `scripts/manual_tests/test_enrich_off.py`

**Interfaces:**
- Consumes: Task 2 的 OFF 商品（`price IS NULL AND description IS NULL`）；`LLMFactory.get_llm("summarize")`
- Produces:
  - `async def enrich(limit: int | None = None) -> int`——每商品一次 LLM 调用，输出 JSON `{"price": float, "description": str}`，UPDATE 回 `price/description`；幂等（只处理 `price IS NULL`）
  - 命令 `python -m scripts.enrich_off_products --limit 5`
  - **硬性**：价格区间按类目控制在 3.0~199.0 元（LLM 输出越界时 clamp），保留两位小数

- [ ] **Step 1: 写冒烟测试**

新建 `scripts/manual_tests/test_enrich_off.py`：

```python
# scripts/manual_tests/test_enrich_off.py
# 需要：PG 有 OFF 商品（Task 2）、DEEPSEEK_API_KEY 可用；真实 LLM 调用 1 次
import asyncio

from sqlalchemy import text

from backend.dependencies import AsyncSessionLocal
from scripts.enrich_off_products import enrich


def test_enrich_one_product():
    asyncio.run(_run())


async def _run():
    n = await enrich(limit=1)
    assert n >= 1
    async with AsyncSessionLocal() as s:
        row = (await s.execute(text(
            "SELECT price, description FROM products "
            "WHERE source='openfoodfacts' AND price IS NOT NULL LIMIT 1"
        ))).fetchone()
        assert row is not None, "no enriched product"
        assert row[0] is not None and 3.0 <= float(row[0]) <= 199.0
        assert row[1] and len(row[1]) >= 20
```

- [ ] **Step 2: 运行确认失败**

Run: `& $py -m pytest scripts/manual_tests/test_enrich_off.py -v`
Expected: FAIL（`ModuleNotFoundError`；若此前恰有 price 非空商品则为其他失败——Task 1 已下架英文书，英文书 price 非空但 source 不同，本测试只查 openfoodfacts，故预期 ModuleNotFoundError）

- [ ] **Step 3: 实现**

新建 `scripts/enrich_off_products.py`：

```python
# scripts/enrich_off_products.py
# 用法：python -m scripts.enrich_off_products [--limit N]
# 为 OFF 商品生成演示价格（CNY）与中文详情文案；只处理 price IS NULL 的行，幂等。
import argparse
import asyncio
import json
import re

from sqlalchemy import text

from backend.core.llm_factory import LLMFactory
from backend.core.logger import get_logger
from backend.dependencies import AsyncSessionLocal

logger = get_logger(__name__)

_PROMPT = """你是电商平台的商品编辑。为下面这件真实商品生成演示用售价与详情文案。
商品：{title}
品牌/规格/配料/营养：{params}
类目：{category}

只输出 JSON，格式：{{"price": 数字, "description": "60~120字中文详情文案"}}
要求：
1. price 为人民币演示价，按类目常识在 3.0~199.0 之间（饮料零食取低端，礼盒/粮油取中高端），保留两位小数
2. description 口吻为电商详情页，客观介绍卖点，不编造功效/认证
3. 不要输出 JSON 以外的任何内容
"""


def _clamp(price: float) -> float:
    return round(max(3.0, min(199.0, price)), 2)


async def enrich(limit: int | None = None) -> int:
    llm = LLMFactory.get_llm("summarize")
    async with AsyncSessionLocal() as db:
        sql = """
            SELECT id, title, category, params FROM products
            WHERE source = 'openfoodfacts' AND is_active AND price IS NULL
            ORDER BY created_at
        """
        if limit:
            sql += f" LIMIT {int(limit)}"
        rows = (await db.execute(text(sql))).mappings().all()

        done = 0
        for row in rows:
            prompt = _PROMPT.format(
                title=row["title"],
                params=json.dumps(row["params"] or {}, ensure_ascii=False)[:800],
                category=row["category"] or "日用百货",
            )
            try:
                resp = await llm.ainvoke(prompt)
                raw = resp.content if hasattr(resp, "content") else str(resp)
                match = re.search(r"\{.*\}", raw, re.S)
                if not match:
                    raise ValueError(f"no JSON object: {raw[:150]}")
                data = json.loads(match.group(0))
                price = _clamp(float(data["price"]))
                desc = str(data["description"]).strip()
                if len(desc) < 10:
                    raise ValueError("description too short")
            except Exception as e:
                logger.warning("enrich.failed", title=row["title"], error=str(e))
                continue
            await db.execute(
                text("UPDATE products SET price = :p, description = :d, updated_at = NOW() "
                     "WHERE id = :id"),
                {"p": price, "d": desc, "id": row["id"]},
            )
            await db.commit()
            done += 1
            logger.info("enrich.done", title=row["title"][:30], price=price, n=done)
        return done


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    print(f"✅ 完成：{asyncio.run(enrich(args.limit))} 个商品补全价格与文案")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行冒烟测试**

Run: `& $py -m pytest scripts/manual_tests/test_enrich_off.py -v`（1 次 LLM 调用，超时 3 分钟）
Expected: PASS

- [ ] **Step 5: 全量补全**

Run: `& $py -m scripts.enrich_off_products`（约 100 次 LLM 调用，预计 10~20 分钟，超时给 40 分钟）
Verify: `SELECT count(*) FROM products WHERE source='openfoodfacts' AND is_active AND price IS NULL;` → 0（个别失败商品允许残留 ≤5，报告说明）

---

### Task 4: 评价生成、rating 回填与向量重建 + 全量回归

**Files:**
- Create: `scripts/backfill_product_rating.py`
- Modify: 无（复用 `scripts/seed_product_reviews.py`、`scripts/init_milvus_product.py`、`scripts/build_product_knowledge.py`——均只运行不修改）
- Test: `scripts/manual_tests/test_off_pipeline.py`（新建，整链路断言）

**Interfaces:**
- Consumes: Task 1~3 产物；现有 `seed_product_reviews`（其查询 `WHERE p.is_active = TRUE`，天然只处理 OFF 商品）；`init_milvus_product`（drop+重建集合）、`build_product_knowledge`（只索引 active）
- Produces: `backfill_rating() -> int`（用评价均分 UPDATE active 商品的 rating，幂等）；命令 `python -m scripts.backfill_product_rating`

- [ ] **Step 1: 写整链路测试**

新建 `scripts/manual_tests/test_off_pipeline.py`：

```python
# scripts/manual_tests/test_off_pipeline.py
# M1b 收官断言：中文商品/价格/评价/rating/向量/英文下架 全链路
# 需要：Task 1~4 步骤全部跑完后执行（不依赖后端进程）
import asyncio

from sqlalchemy import text

from backend.dependencies import AsyncSessionLocal


def test_off_pipeline_ready():
    asyncio.run(_run())


async def _run():
    async with AsyncSessionLocal() as s:
        # 1. active 商品全部是中文 OFF 商品
        active = (await s.execute(text(
            "SELECT source, count(*) FROM products WHERE is_active GROUP BY source"
        ))).fetchall()
        sources = {r[0]: r[1] for r in active}
        assert sources.get("books_toscrape", 0) == 0, "books must be retired"
        assert sources.get("openfoodfacts", 0) >= 80, sources

        # 2. 价格与文案覆盖率 ≥95%
        total = sources["openfoodfacts"]
        priced = (await s.execute(text(
            "SELECT count(*) FROM products WHERE source='openfoodfacts' AND is_active "
            "AND price IS NOT NULL AND description IS NOT NULL"
        ))).scalar()
        assert priced / total >= 0.95, f"enrich coverage {priced}/{total}"

        # 3. 每个 active 商品评价 ≥30 且 rating 已回填
        weak = (await s.execute(text(
            "SELECT count(*) FROM products p WHERE p.is_active AND p.rating IS NULL"
        ))).scalar()
        assert weak == 0, f"{weak} products missing rating"
        short = (await s.execute(text(
            "SELECT count(*) FROM (SELECT p.id FROM products p "
            "LEFT JOIN product_reviews r ON r.product_id = p.id AND r.source='generated' "
            "WHERE p.is_active GROUP BY p.id HAVING count(r.id) < 30) t"
        ))).scalar()
        assert short == 0, f"{short} products with <30 reviews"

        # 4. 评价内容为中文
        sample = (await s.execute(text(
            "SELECT content FROM product_reviews r JOIN products p ON p.id=r.product_id "
            "WHERE p.source='openfoodfacts' ORDER BY r.created_at DESC LIMIT 1"
        ))).scalar()
        assert sample and any('一' <= ch <= '鿿' for ch in sample)
```

- [ ] **Step 2: 运行确认失败**

Run: `& $py -m pytest scripts/manual_tests/test_off_pipeline.py -v`
Expected: FAIL（`books must be retired` 若 Task 1 没跑，或评价/rating 缺失——记录当前失败原因）

- [ ] **Step 3: 实现 rating 回填**

新建 `scripts/backfill_product_rating.py`：

```python
# scripts/backfill_product_rating.py
# 用法：python -m scripts.backfill_product_rating
# 用 generated 评价均分回填 active 商品的 rating（1~5，一位小数）。幂等可重复跑。
import asyncio

from sqlalchemy import text

from backend.core.logger import get_logger
from backend.dependencies import AsyncSessionLocal

logger = get_logger(__name__)


async def backfill_rating() -> int:
    async with AsyncSessionLocal() as db:
        res = await db.execute(text("""
            UPDATE products p SET rating = sub.avg_rating, updated_at = NOW()
            FROM (
                SELECT product_id, ROUND(AVG(rating))::int AS avg_rating
                FROM product_reviews WHERE source = 'generated'
                GROUP BY product_id
            ) sub
            WHERE p.id = sub.product_id AND p.is_active
              AND (p.rating IS NULL OR p.rating <> sub.avg_rating)
        """))
        await db.commit()
        n = res.rowcount or 0
    logger.info("rating.backfilled", count=n)
    return n


def main():
    print(f"✅ 回填 {asyncio.run(backfill_rating())} 个商品 rating")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 生成评价并回填（真实 LLM 批量调用）**

```powershell
& $py -m scripts.seed_product_reviews --per-product 30   # ~100 次调用，预计 20~40 分钟，超时给 90 分钟
& $py -m scripts.backfill_product_rating
```
Expected: `seed.done` 约 100 次；回填数 ≥80。个别 LLM 失败商品按 seed 脚本既有逻辑跳过——若 `<30 条评价` 的商品 >5 个，重跑一次 seed（幂等补齐）。

- [ ] **Step 5: 重建向量集合**

```powershell
& $py scripts/init_milvus_product.py        # drop + 重建（仅商品数据，安全）
& $py -m scripts.build_product_knowledge    # 只索引 is_active 商品（既有 WHERE）
```
Expected: 集合行数 ≥ 活跃商品数 × 4；`distinct product_id` = 活跃商品数（英文书 chunk 已随 drop 清除）
注：直跑 `scripts/` 文件需 `PYTHONPATH=.`，或改用等效模块调用——若 `init_milvus_product` 报 import 错，用 `$env:PYTHONPATH="."; & $py scripts\init_milvus_product.py`。

- [ ] **Step 6: 整链路测试**

Run: `& $py -m pytest scripts/manual_tests/test_off_pipeline.py -v`
Expected: PASS

- [ ] **Step 7: API 回归 + M1 全量单测**

启动后端：
```powershell
& $py -m pytest tests/ -v                                                     # 期望 7 passed
& $py -m pytest scripts/manual_tests/test_products_api.py scripts/manual_tests/test_orders_api.py -v
```
Expected: 单测全绿；products 冒烟 3 passed（列表含中文标题、图片 200、详情 params 为中文键）；orders 冒烟 2 passed。
人工抽查：`GET /api/v1/products?page_size=5` 全为中文商品、价格为 `¥` 风格数值字符串；`/docs` 正常；停后端。

---

## M1b 完成定义（DoD）

- [ ] active 商品 ≥80，全部 `source='openfoodfacts'`、中文标题、`currency='CNY'`
- [ ] ≥95% active 商品有价格（3~199 元）与中文详情文案
- [ ] 每 active 商品 ≥30 条中文 generated 评价，rating 已回填
- [ ] `product_knowledge` 仅含 active 商品 chunk，英文书 chunk 清零
- [ ] `tests/` 7 passed + products/orders API 冒烟 5 passed
- [ ] 旧英文商品行仍存在（`is_active=FALSE`），其订单数据未动

## 明确不做（M1b 范围外）

- 前端页面（M2）
- QA 意图/检索切换（M2）
- 删除旧英文商品行/旧评价（保留可追溯）
- 修改 `scripts/crawl/` 英文爬虫代码（保留参考）
- OFF 增量同步/定时更新（MVP 一次性导入）

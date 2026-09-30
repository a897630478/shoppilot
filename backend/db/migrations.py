# backend/db/migrations.py
#
# 启动时自动执行的 Schema 补丁（全部幂等，可重复运行）。
# 规则：
#   - 只写 ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS 等幂等 DDL
#   - 禁止写 DROP / TRUNCATE 等破坏性变更
#   - 每次 init_db.sql 新增字段，同步在 _MIGRATIONS 里追加一条
import asyncio

from sqlalchemy import text
from backend.dependencies import AsyncSessionLocal
from backend.core.logger import get_logger

logger = get_logger(__name__)

# ── 所有需要补丁的 DDL，按时间顺序追加。SQL 必须幂等（IF NOT EXISTS）──
# 注：教育表补丁已在 M5b 教育数据清理时移除（表已 DROP，补丁只会刷警告）
_MIGRATIONS: list[tuple[str, str]] = [
    # ── 电商改造 M1（spec: 2026-09-27-ecommerce-rework-design.md §3.1）──
    # 注：asyncpg 走 prepared statement，一次 execute 只能跑一条语句，
    # 故 CREATE TABLE 与每条 CREATE INDEX 各自独立成条（计划文档已注明此回退）。
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
        """,
    ),
    (
        "idx_products_category",
        "CREATE INDEX IF NOT EXISTS idx_products_category ON products (category)",
    ),
    (
        "idx_products_title",
        "CREATE INDEX IF NOT EXISTS idx_products_title ON products (title)",
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
        """,
    ),
    (
        "idx_product_reviews_product_id",
        "CREATE INDEX IF NOT EXISTS idx_product_reviews_product_id ON product_reviews (product_id)",
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
        """,
    ),
    (
        "idx_orders_user_id",
        "CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders (user_id)",
    ),
    (
        "idx_orders_status",
        "CREATE INDEX IF NOT EXISTS idx_orders_status ON orders (status)",
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
        """,
    ),
    (
        "idx_service_tickets_status",
        "CREATE INDEX IF NOT EXISTS idx_service_tickets_status ON service_tickets (status)",
    ),
    (
        "idx_service_tickets_order_id",
        "CREATE INDEX IF NOT EXISTS idx_service_tickets_order_id ON service_tickets (order_id)",
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
        """,
    ),
    (
        "idx_review_reports_product_id",
        "CREATE INDEX IF NOT EXISTS idx_review_reports_product_id ON review_reports (product_id)",
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
        """,
    ),
    (
        "idx_rec_sessions_user_id",
        "CREATE INDEX IF NOT EXISTS idx_rec_sessions_user_id ON recommendation_sessions (user_id)",
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
        """,
    ),
    (
        "idx_rec_results_session_id",
        "CREATE INDEX IF NOT EXISTS idx_rec_results_session_id ON recommendation_results (session_id)",
    ),
    (
        # books.toscrape 部分 slug 超 128 字符，加宽避免长商品 ID 拒收（重复执行为无害 no-op）
        "products.external_id_widen",
        "ALTER TABLE products ALTER COLUMN external_id TYPE VARCHAR(256)",
    ),
    (
        # M5a：导购会话摘要列（save_memory UPSERT 用）
        "recommendation_sessions.summary",
        "ALTER TABLE recommendation_sessions ADD COLUMN IF NOT EXISTS summary TEXT",
    ),
    (
        # FAQ 补录：运营端填写的标准答案（入向量库的正文）
        "knowledge_pending_queue.answer",
        "ALTER TABLE knowledge_pending_queue ADD COLUMN IF NOT EXISTS answer TEXT",
    ),
    (
        # 真实购物评论数据集来源（拆两条：asyncpg 单语句限制）
        "product_reviews.drop_source_check",
        "ALTER TABLE product_reviews DROP CONSTRAINT IF EXISTS product_reviews_source_check",
    ),
    (
        "product_reviews.add_source_check_dataset",
        "ALTER TABLE product_reviews ADD CONSTRAINT product_reviews_source_check "
        "CHECK (source IN ('generated', 'crawled', 'dataset'))",
    ),
]


async def run_migrations() -> None:
    """
    在应用启动时执行所有 Schema 补丁。
    单条失败只记录警告，不阻断启动流程。
    """
    async with AsyncSessionLocal() as session:
        for desc, sql in _MIGRATIONS: # 再遍历每一个补丁
            try:
                await session.execute(text(sql))
                await session.commit()
                logger.debug("db.migration_applied", column=desc)
            except Exception as e:
                await session.rollback()
                err = str(e)
                if "already exists" not in err:
                    logger.warning("db.migration_failed", column=desc, error=err)

    logger.info("db.migrations_done", count=len(_MIGRATIONS))



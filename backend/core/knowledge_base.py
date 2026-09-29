from typing import Optional
import os
backend_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
print(f'backend_path: {backend_path}')

from pymilvus import MilvusClient, AnnSearchRequest, WeightedRanker

from backend.config import get_settings
from backend.core.logger import get_logger


logger = get_logger(__name__)


# ──────────────────────────────────────────────────────────────
# BGE-M3 本地嵌入模型（进程内单例，dense + sparse 双输出）
# ──────────────────────────────────────────────────────────────

class BGEMEmbedder:
    """
    BGE-M3 本地嵌入模型单例。

    一次推理同时输出：
      - dense 向量（1024 维浮点数组，用于语义相似度检索）
      - sparse 向量（{token_id: weight} 字典，用于关键词精确检索）

    进程内单例：首次调用 get_instance() 时加载模型（约5-15秒），
    后续调用直接返回同一实例，不重复加载。

    用法：
        embedder = BGEMEmbedder.get_instance()
        dense, sparse = embedder.encode_query("什么是 Spring IOC？")
    """

    _instance: Optional["BGEMEmbedder"] = None   # 单例持有

    def __init__(self, model_path: str):
        # ── 兼容性补丁：FlagEmbedding 1.3.x 依赖 transformers 内部函数 ──
        # transformers>=5.0 移除了 is_torch_fx_available，
        # 但当前锁定 transformers==4.51.0 不受影响。
        # 此补丁作为保险，避免未来升级时报 ImportError。
        import importlib.util as _ilu
        from transformers.utils import import_utils as _tf_iu
        if not hasattr(_tf_iu, "is_torch_fx_available"):
            _tf_iu.is_torch_fx_available = (
                lambda: _ilu.find_spec("torch.fx") is not None
            )

        import torch
        from FlagEmbedding import BGEM3FlagModel

        logger.info("bge_m3.loading", model_path=model_path)

        # ── fp16 仅在 CUDA 上启用，MPS（Apple M系列）不启用 ──
        # MPS 在 BGE-M3 attention 矩阵乘法上会触发 LLVM ERROR，
        # CPU 模式下用 fp32，速度稍慢但稳定。
        # _device = "cuda:0" if torch.cuda.is_available() else "cpu"
        _use_fp16 = torch.cuda.is_available()

        self._model = BGEM3FlagModel(
            model_name_or_path=model_path,
            use_fp16=_use_fp16,
            # device=_device,
        )
        logger.info("bge_m3.loaded", use_fp16=_use_fp16)

    @classmethod
    def get_instance(cls) -> "BGEMEmbedder":
        """获取单例（首次调用时加载模型，后续复用）"""
        if cls._instance is None:
            bge_m3_model_path = os.path.join(backend_path, get_settings().bge_m3_model_path)
            cls._instance = BGEMEmbedder(bge_m3_model_path)
        return cls._instance
    def encode(
        self,
        texts: list[str],
        batch_size: int = 12,
    ) -> tuple[list[list[float]], list[dict]]:
        """
        批量编码文本，同时返回 dense 和 sparse 两种向量。

        Args:
            texts:      待编码的文本列表
            batch_size: 单次推理批大小，越大速度越快但显存占用越多；
                        12 是 16GB 显存 / 统一内存下的经验值

        Returns:
            (dense_vecs, sparse_vecs)
              dense_vecs:  list of 1024-dim float 向量，每项对应 texts[i]
              sparse_vecs: list of {token_id: weight} 字典，每项对应 texts[i]
        """
        output = self._model.encode(
            texts,
            batch_size=batch_size,
            max_length=8192,            # BGE-M3 支持最长 8192 token，覆盖大多数 chunk
            return_dense=True,          # 输出稠密语义向量
            return_sparse=True,         # 输出稀疏关键词向量
            return_colbert_vecs=False,  # ColBERT 多向量表示，本项目不用
        )
        # print(f'output: {output}')
        # print("=="*40)
        dense_vecs = output["dense_vecs"].tolist()   # numpy → Python list
        # print(f'dense_vecs: {dense_vecs}')
        # print("==" * 40)
        # sparse: numpy.float16 → Python float
        # 必须转换！LangGraph MemorySaver 用 msgpack 序列化 State，
        # msgpack 不支持 numpy.float16，会在运行时抛 TypeError。
        sparse_vecs = [{int(k): float(v) for k, v in d.items()}
                       for d in output["lexical_weights"]]
        # print(f'sparse_vecs: {sparse_vecs}')
        return dense_vecs, sparse_vecs

    def encode_query(self, text: str) -> tuple[list[float], dict]:
        """
        编码单条查询，返回 (dense_vec, sparse_vec)。

        查询时调用此方法（而非 encode），batch_size=1 避免不必要的 padding。

        Returns:
            (dense_vec, sparse_vec)
              dense_vec:  1024-dim float 列表
              sparse_vec: {token_id: weight} 字典
        """
        dense_list, sparse_list = self.encode([text], batch_size=1)
        return dense_list[0], sparse_list[0]


COLLECTION_NAME = "product_knowledge"   # 商品导购问答检索集合


class KnowledgeBaseClient:
    """
    Milvus 知识库客户端（MilvusClient 版）。

    单 Collection 设计（product_knowledge），按 tenant_id / product_id 字段过滤。

    单例连接：_client 是类变量，整个进程只创建一次 MilvusClient 连接。
    """

    _client: Optional["MilvusClient"] = None
    _loaded: bool = False

    # HNSW 搜索时的候选集大小，精度/速度平衡点（5.6 节 _hybrid_search 使用）
    ANN_EF = 64

    def __init__(self):
        if KnowledgeBaseClient._client is None:
            settings = get_settings()
            uri = f"http://{settings.milvus_host}:{settings.milvus_port}"
            KnowledgeBaseClient._client = MilvusClient(uri=uri)
            logger.info("milvus.connected", uri=uri)

        if not KnowledgeBaseClient._loaded:
            try:
                KnowledgeBaseClient._client.load_collection(COLLECTION_NAME)
            except Exception:
                pass   # 集合尚未创建时忽略（先跑 init_milvus_product.py）
            KnowledgeBaseClient._loaded = True
    VECTOR_TOP_K = 10  # Hybrid 召回的候选数量，传给 Reranker 精排

    def _hybrid_search(
            self,
            query_embedding: list[float],
            query_sparse: dict,
            top_k: int,
            filters: Optional[str] = None,
    ) -> list[dict]:
        """
        对 product_knowledge 做 Hybrid 检索（Dense + Sparse → WeightedRanker 融合）。

        两个 AnnSearchRequest 分别构造 Dense 和 Sparse 检索请求，
        由 Milvus 在服务端并行执行后，用 WeightedRanker 加权融合排序。

        Args:
            query_embedding: Dense Query 向量（1024 维，来自 encode_query）
            query_sparse:    Sparse Query 向量（{token_id: weight}，来自 encode_query）
            top_k:           每路召回数量（融合后同样取 top_k）
            filters:         Milvus bool 表达式，如 'tenant_id == "xxx"'

        Returns:
            候选文档列表，每项含 "content" / "score" / "metadata"。
            score 是 WeightedRanker 的加权排序信号，不是概率，
            直接交给 5.7 节的 Reranker 做精细打分。
        """
        try:
            # ── Dense ANN 检索请求 ─────────────────────────────────────
            # COSINE 度量匹配 BGE-M3 dense 向量（L2 归一化后等价于余弦相似度）
            # ef=64：HNSW 搜索时的候选集大小，越大精度越高，64 是精度/速度平衡点
            dense_req = AnnSearchRequest(
                data=[query_embedding],
                anns_field="embedding",
                param={
                    "metric_type": "COSINE",
                    "params": {"ef": self.ANN_EF},
                },
                limit=top_k,
                expr=filters,
            )

            # ── Sparse 关键词检索请求 ──────────────────────────────────
            # IP（内积）是 BGE-M3 lexical_weights 的标准度量
            sparse_req = AnnSearchRequest(
                data=[query_sparse],
                anns_field="sparse_embedding",
                param={"metric_type": "IP"},
                limit=top_k,
                expr=filters,
            )

            # product_knowledge 集合真实字段（无 course_id/document_id/chunk_type）
            output_fields = [
                "content", "source_name", "product_id", "chunk_index",
            ]

            # ── WeightedRanker(0.7, 0.3) ──────────────────────────────
            # 第一个权重对应第一个请求（Dense），第二个对应第二个请求（Sparse）
            # 两路结果在 Milvus 服务端并行检索，融合后返回
            results = self._client.hybrid_search(
                collection_name=COLLECTION_NAME,
                reqs=[dense_req, sparse_req],
                ranker=WeightedRanker(0.7, 0.3),
                limit=top_k,
                output_fields=output_fields,
            )
            # print(f'results: {results}')
            # print(f'results: {type(results)}')
            # print(f'results: {results[0]}')
            # print(f'results: {len(results[0])}')
            candidates = []
            for hit in results[0]:
                # print(f'hit-->{hit}')
                candidates.append({
                    "content": hit["entity"].get("content") or "",
                    "score":   hit.get("distance") or 0.0,
                    "metadata": {
                        "source_name": hit["entity"].get("source_name") or "",
                        "product_id":  hit["entity"].get("product_id")  or "",
                        "chunk_index": hit["entity"].get("chunk_index") or 0,
                    },
                })
            logger.info(
                "knowledge_base.hybrid_search_done",
                candidates=len(candidates),
            )
            return candidates
        except Exception as e:
            logger.error("knowledge_base.hybrid_search_failed", error=str(e))
            return []

    @staticmethod
    def _build_filter(tenant_id: str, product_id: Optional[str] = None) -> str:
        """
        构建 Milvus bool 过滤表达式。
        对 tenant_id / product_id 做转义，防止 filter 表达式注入。
        """
        safe_tenant = tenant_id.replace('"', '\\"')
        expr = f'tenant_id == "{safe_tenant}"'
        if product_id:
            safe_product = product_id.replace('"', '\\"')
            expr += f' and product_id == "{safe_product}"'
        return expr


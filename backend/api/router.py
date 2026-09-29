# backend/api/router.py
# API 路由总入口（M5b：教育模块已移除，仅保留电商能力）

from fastapi import APIRouter
from backend.api.v1 import auth, qa, unified_chat, products, orders, reviews, service, guide, faq

api_router = APIRouter()                              # 总路由

# 把每个子 router 带前缀 + 标签聚合进来
api_router.include_router(auth.router,          prefix="/auth",      tags=["认证"])
api_router.include_router(unified_chat.router,  prefix="/chat",      tags=["AI助手"])   # 统一入口
api_router.include_router(qa.router,            prefix="/qa",        tags=["商品问答"])  # 导购问答（RAG）
api_router.include_router(products.router,      prefix="/products",  tags=["商品"])      # M1 轻量外壳
api_router.include_router(orders.router,        prefix="/orders",    tags=["订单"])      # M1 轻量外壳
api_router.include_router(reviews.router,       prefix="/reviews",   tags=["评价分析"])  # M4a
api_router.include_router(service.router,       prefix="/service",   tags=["售后客服"])  # M4b
api_router.include_router(guide.router,         prefix="/guide",     tags=["智能导购"])  # M5a
api_router.include_router(faq.router,           prefix="/faq",       tags=["FAQ补录"])   # 收尾补全

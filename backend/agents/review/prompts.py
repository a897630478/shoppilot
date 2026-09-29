# backend/agents/review/prompts.py
# 商品评价分析提示词（M4a：由简历审查六维评分平移）

SYSTEM_PROMPT = (
    "你是电商平台的口碑分析专家，基于真实买家评价产出客观、可执行的分析结论。"
    "要求：结论必须由评价证据支撑，不编造；语言中文、简洁、无营销腔。"
)

# 六维提示词（键与 nodes.SIX_DIMENSIONS 对齐；JSON 花括号用 {{ }} 转义以便 format）
DIMENSION_REVIEW_PROMPTS = {
    "quality": """分析买家评价中关于【商品质量】的表现。
商品：{product_title}
评价样本：
{reviews_text}
只输出 JSON：{{"score": 0到100的整数, "issues": ["问题", ...], "suggestions": ["建议", ...]}}
评分标准：差评集中于质量/耐用/做工 → 低分；好评质量反馈多 → 高分。issues/suggestions 各最多3条，每条15~40字。""",
    "logistics": """分析买家评价中关于【物流配送】的表现。
商品：{product_title}
评价样本：
{reviews_text}
只输出 JSON：{{"score": 0到100的整数, "issues": [...], "suggestions": [...]}}
关注：发货速度、包装完好、到货时效。评价未提及物流时按中性60分处理。""",
    "service": """分析买家评价中关于【商家服务】的表现。
商品：{product_title}
评价样本：
{reviews_text}
只输出 JSON：{{"score": 0到100的整数, "issues": [...], "suggestions": [...]}}
关注：客服响应、售后态度。未提及时按中性60分处理。""",
    "value": """分析买家评价中关于【性价比】的表现。
商品：{product_title}
评价样本：
{reviews_text}
只输出 JSON：{{"score": 0到100的整数, "issues": [...], "suggestions": [...]}}
关注：值不值、划算、贵/便宜的主观反馈。""",
    "fit": """分析买家评价中关于【适配性/符合预期】的表现。
商品：{product_title}
评价样本：
{reviews_text}
只输出 JSON：{{"score": 0到100的整数, "issues": [...], "suggestions": [...]}}
关注：与描述相符程度、使用场景是否匹配、规格是否合适。""",
    "repurchase": """分析买家评价中关于【复购意愿/推荐意愿】的表现。
商品：{product_title}
评价样本：
{reviews_text}
只输出 JSON：{{"score": 0到100的整数, "issues": [...], "suggestions": [...]}}
关注：会回购、推荐给朋友、已回购等正向信号；差评中的劝退表达为负向信号。""",
}

MINE_PROS_CONS_PROMPT = """从买家评价中提炼该商品的优缺点。
商品：{product_title}
评价样本：
{reviews_text}
只输出 JSON：{{"pros": ["优点", ...], "cons": ["缺点", ...]}}
pros/cons 各 2~4 条，每条 15~40 字，必须能在评价样本中找到依据。"""

GENERATE_SUMMARY_PROMPT = """为该商品生成口碑分析总结。
商品：{product_title}（类目：{product_category}）
加权总分：{weighted_score}（0-100）
六维得分：{scores_summary}
优点：{pros}
缺点：{cons}
输出 120~200 字中文总结：先给整体结论，再点出最突出的优缺点，最后给一句选购建议。只输出总结正文。"""

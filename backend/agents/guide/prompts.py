# backend/agents/guide/prompts.py
# 多轮导购提示词（M5a：由模拟面试平移）

SYSTEM_PROMPT = (
    "你是 ShopPilot 商城的资深导购顾问。通过自然的多轮对话了解顾客需求，"
    "基于真实商品数据给出推荐。要求：价格与商品名以你拿到的数据为准，绝不编造；"
    "每轮只问 1 个问题或给出一条回应，保持对话节奏；语气热情但不啰嗦。"
)

NEEDS_EXTRACT_PROMPT = """从顾客最新发言抽取需求信息。
已有需求：{needs}；已有预算：{budget}
顾客最新发言：{answer}
只输出 JSON：{{"needs": "更新后的需求概括", "budget": 数字或null, "preferences": ["标签"]}}"""

OPENING_PROMPT = """基于顾客的开场白生成导购开场回应（60~100字）：先复述理解的需求，再问出第一个关键问题（品类/使用场景）。
顾客开场：{answer}"""

STAGE_PROMPTS = {
    "needs_discovery": """当前阶段：需求探询。已知信息：{needs}
顾客最新发言：{answer}
生成回应：确认已知信息，追问仍缺的关键维度（用途/品类/特殊要求），只问一个问题，40~80字。""",
    "budget_confirm": """当前阶段：预算与偏好确认。已知需求：{needs}，预算：{budget}
顾客最新发言：{answer}
生成回应：确认预算是否已明确；若明确则说明将据此筛选并进入选品，40~80字。""",
    "matching": """当前阶段：商品匹配。需求：{needs}，预算：{budget}
候选商品：
{candidates_block}
顾客最新发言：{answer}
生成回应：介绍最匹配的 2~3 个候选（名称+价格+一句卖点），并问顾客想先看哪个或还需要什么条件，80~150字。""",
    "compare_qa": """当前阶段：对比答疑。需求：{needs}
候选商品：
{candidates_block}
顾客最新发言：{answer}
基于候选与商品知识如实回答对比/疑问，必要时给出倾向性建议，60~120字。""",
    "recommend_close": """当前阶段：推荐收尾。需求：{needs}，预算：{budget}
候选商品：
{candidates_block}
顾客最新发言：{answer}
生成最终推荐语（60~100字）：明确给出 1~3 个推荐及理由，引导顾客查看商品详情。""",
}

REPORT_PROMPT = """生成最终推荐报告。
需求：{needs}，预算：{budget}，偏好：{preferences}
候选商品（product_id|标题|价格）：
{candidates_block}
对话摘要：{history_summary}
只输出 JSON：{{"summary": "80~150字总结", "recommendations": [{{"product_id": "...", "reason": "20~50字理由"}}]}}
recommendations 只能引用上面出现过的 product_id，1~5 条，按契合度排序。"""

# srs_calculator_supabase.py
from datetime import date, timedelta
import math
from .config import TODAY, A_THRESHOLD, K_TARGET

# --- SRS 核心算法函数 ---

def calculate_review_factor_R(item, today=None):
    """计算复习需求因子 R：逾期天数"""
    if today is None:
        today = TODAY
    next_due_date = item['LRD'] + timedelta(days=item['CI'])
    overdue_days = (today - next_due_date).days
    return max(0, overdue_days)

def calculate_application_factor_A(item, today=None):
    """计算应用饥渴因子 A：自上次使用以来的天数"""
    if today is None:
        today = TODAY
    days_since_applied = (today - item['LAD']).days
    return days_since_applied

def calculate_priority_score_P(item, today=None):
    """
    计算优先级分数 P，使用 'referenceCount' (N) 作为惩罚因子
    """
    A = calculate_application_factor_A(item, today)
    R = calculate_review_factor_R(item, today)
    C = 2 if item['is_core'] else 1 
    
    # N (Total Reference Count): 引用次数越多，掌握度越高，P 应该越低
    N = item.get('referenceCount', 0) 
    
    # 1. 饥渴强制使用 (Logic不变)
    if A > A_THRESHOLD:
        return 10000 + A
    
    # 2. 未到期 (R=0)
    if R == 0:
        return 0
        
    # 3. 计算掌握度惩罚因子 S (Study Factor)
    # S = log2(N + 1)
    S = math.log2(N + 1)

    # 4. 计算原始 P
    P_base = R * C + (A // 5) 
    
    # 5. 应用 N 因子惩罚：次数越多，优先级越低
    # 使用 max(1, ...) 确保在 R>0 时，P 至少为 1
    P_final = max(1, P_base - S) 
    
    # 如果惩罚后 P 变成了 0 或更小，我们至少保持它为 1 (确保它在 R>0 时能被选中)
    return P_final

def calculate_state_after_review(card, today=None): 
    """
    【场景 A：主动复习】
    用户在 SRS 界面点击了“已学习”。
    结果：LRD 更新为今天，CI 保持不变，LAD 不动。
    """
    if today is None:
        today = TODAY
    
    return {
        'ci': card['CI'],
        'lrd': today,
        'lad': card['LAD'],  # 保持原样
        'referenceCount': card.get('referenceCount', 0) # 保持原样
    }

def calculate_state_after_application(card, today=None):
    """
    【场景 B：实战引用】
    用户在写 Module 2 或其他内容时引用了此卡。
    结果：LAD 更新为今天，referenceCount + 1，LRD 和 CI 不动。
    """
    if today is None:
        today = TODAY
    
    return {
        'ci': card['CI'],      # 保持原样
        'lrd': card['LRD'],    # 保持原样
        'lad': today,          # 更新应用日期
        'referenceCount': card.get('referenceCount', 0) + 1 # 引用次数增加
    }

def generate_must_use_list(cards, today=None, k_target=K_TARGET):
    """
    生成"今日必用"清单
    
    参数:
        cards (list): 所有卡片列表
        today (date): 当前日期（可选）
        k_target (int): 目标数量
    
    返回:
        list: 今日必学卡片列表
    """
    if today is None:
        today = TODAY
    
    k_force = []
    candidates = []

    for item in cards:
        P = calculate_priority_score_P(item, today)
        
        if P >= 10000:
            k_force.append((P, item))
        elif P > 0:
            candidates.append((P, item))

    k_force.sort(key=lambda x: x[0], reverse=True)
    k_remaining = max(0, k_target - len(k_force))
    candidates.sort(key=lambda x: x[0], reverse=True)
    k_priority = [item for p, item in candidates[:k_remaining]]
    
    final_list = [item for p, item in k_force] + k_priority
    
    # 打印输出
    print("-" * 50)
    print(f"📅 运行日期: {today} | 目标: {k_target} | 强制锁定: {len(k_force)}")
    print("-" * 50)
    
    for i, item in enumerate(final_list, 1):
        P_score = calculate_priority_score_P(item, today)
        R_val = calculate_review_factor_R(item, today)
        A_val = calculate_application_factor_A(item, today)
        
        print(f"[{i}] {item.get('key_module', 'Unknown')} (ID: {item['id']})")
        print(f"    - P: {P_score} | R(逾期): {R_val} | A(饥渴): {A_val} 天 | CI: {item['CI']}")
    print("-" * 50)
    
    return final_list


# ==========================================================
# 独立运行时的测试代码
# ==========================================================

# ==========================================================
# 独立运行时的 Mock 测试代码 (脱离数据库)
# ==========================================================

if __name__ == "__main__":
    from datetime import date, timedelta
    
    # 模拟今天
    test_today = date(2025, 12, 15) 
    print(f"🚀 开始 SRS 算法 Mock 测试 | 模拟今日日期: {test_today}")
    print("=" * 60)

    # 1. 构造 Mock 数据 (不再调用 get_all_cards_srs_state_supabase)
    mock_cards = [
        {
            'card_id': 'MOCK_001',
            'key_module': '逾期未用核心词',
            'CI': 5,
            'LRD': test_today - timedelta(days=10), # 10天前复习，已逾期
            'LAD': test_today - timedelta(days=10), # 10天前使用
            'is_core': True,
            'referenceCount': 0
        },
        {
            'card_id': 'MOCK_002',
            'key_module': '高频使用熟练词',
            'CI': 5,
            'LRD': test_today - timedelta(days=20), # 严重逾期
            'LAD': test_today - timedelta(days=1),  # 但昨天才刚刚在 Mod2 用过
            'is_core': False,
            'referenceCount': 15 # 已经被引用过很多次
        },
        {
            'card_id': 'MOCK_003',
            'key_module': '饥渴词 (长期未用)',
            'CI': 100,
            'LRD': test_today - timedelta(days=10), # 远未到期
            'LAD': test_today - timedelta(days=40), # 但超过了 A_THRESHOLD (30天)
            'is_core': False,
            'referenceCount': 2
        }
    ]

    # 2. 测试 P 分数计算
    print("【第一阶段：优先级 P 分数分析】")
    for card in mock_cards:
        p = calculate_priority_score_P(card, test_today)
        a = calculate_application_factor_A(card, test_today)
        r = calculate_review_factor_R(card, test_today)
        print(f"卡片: {card['key_module']}")
        print(f" -> P:{p:.2f} | R(逾期):{r}天 | A(饥渴):{a}天 | N(引用):{card['referenceCount']}")
    print("-" * 30)

    # 3. 模拟逻辑分离更新
    target_card = mock_cards[0]
    print(f"【第二阶段：逻辑分离测试 - 针对卡片: {target_card['key_module']}】")
    
    # 场景 A：只做复习
    state_review = calculate_state_after_review(target_card, test_today)
    print(f"✅ 动作：主动复习 (Review)")
    print(f"   结果 -> LRD: {state_review['lrd']} (应为今天), LAD: {state_review['lad']} (应保持原样)")

    # 场景 B：只做引用 (Mod2 调用)
    state_app = calculate_state_after_application(target_card, test_today)
    print(f"✅ 动作：实战引用 (Application)")
    print(f"   结果 -> LRD: {state_app['lrd']} (应保持原样), LAD: {state_app['lad']} (应为今天), N: {state_app['referenceCount']} (应加1)")
    
    print("=" * 60)
    print("📊 结论：通过 Mock 数据可以看到，LRD 和 LAD 的更新已经完全解耦。")
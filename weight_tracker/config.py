# config.py

from datetime import date, timedelta

# ==========================================================
# 🚨 关键配置区域 🚨
# ==========================================================

# 1. 您的 Neon 项目 URL
DATABASE_URL = "postgresql://neondb_owner:npg_orFfz1Kcp4he@ep-winter-mud-ai8mbpf4-pooler.c-4.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

# --- SRS 配置 ---
# TODAY 用于 SRS 计算的基准日，在生产环境应为 date.today()
TODAY = date.today()
A_THRESHOLD = 30 # 应用饥渴因子阈值
K_TARGET = 5     # 每日必用模块目标数量

# --- 内部配置 ---
MODULE_TO_TABLE = {
    'mod1': 'mod1_cards', 
    'mod2': 'mod2_cards', 
}

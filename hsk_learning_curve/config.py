# config.py

from datetime import date, timedelta

# ==========================================================
# 🚨 关键配置区域 🚨
# ==========================================================

# 1. 您的 Supabase 项目 URL
SUPABASE_URL = "https://aefuqtzueqwjfhebfhrg.supabase.co" 

# 2. 您的 Supabase Anon Public Key
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFlZnVxdHp1ZXF3amZoZWJmaHJnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjU3MjkxODEsImV4cCI6MjA4MTMwNTE4MX0.ydj2OKZX9ciJXXaStoXDqWXzG_xxyy7w-EXn2IooAfA" 

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

# --- 请求头：包含 Supabase 认证信息 ---
HEADERS = {
    'Content-Type': 'application/json',
    'apikey': SUPABASE_KEY,
    'Authorization': f'Bearer {SUPABASE_KEY}',
    'Prefer': 'return=representation' # 强制 Supabase 返回插入/更新的数据
}
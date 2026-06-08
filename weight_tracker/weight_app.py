# weight_app.py
import psycopg2
import psycopg2.extras
from psycopg2.extras import Json
from flask import Blueprint, request, jsonify
DATABASE_URL = "postgresql://neondb_owner:npg_orFfz1Kcp4he@ep-winter-mud-ai8mbpf4-pooler.c-4.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
weight_bp = Blueprint('weight_tracker', __name__)

def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)

def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            # 完美的精简结构：id, username, record (存储纯粹的单条 JSON 对象)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS weight_logs (
                    id VARCHAR(50) NOT NULL,
                    username VARCHAR(50) NOT NULL,
                    record JSONB NOT NULL,
                    PRIMARY KEY (id)
                );
                CREATE INDEX IF NOT EXISTS idx_weight_logs_username ON weight_logs(username);
            """)
        conn.commit()

try:
    init_db()
except Exception as e:
    print(f"⚠️ 初始化 weight_logs 表失败: {e}")


# ── 1. 查：获取当前用户的全部记录，直接返回压平的 JSON 数组 ──
@weight_bp.route('/get_weight', methods=['GET'])
def get_weight():
    username = request.args.get('username', 'default_user')
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                # 提取 record 里的 timestamp 进行降序排序
                cur.execute("""
                    SELECT record FROM weight_logs 
                    WHERE username = %s 
                    ORDER BY record->>'timestamp' DESC
                """, (username,))
                rows = cur.fetchall()
        
        # 将数据压平，直接返回类似 [{id, weight...}, {...}] 的数组给前端
        result = [row['record'] for row in rows]
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── 2. 增 / 改：单条日志增量 Upsert ──
@weight_bp.route('/save_weight', methods=['POST'])
def save_weight():
    payload = request.json or {}
    username = payload.get('username', 'default_user')
    
    # 提取出单条 log 核心内容，如果前端传过来带有 username，可以在写入前清掉，保持 record 干净
    log_item = payload.get('record') or payload
    log_id = log_item.get('id')
    
    if not log_id:
        return jsonify({"error": "Missing log unique ID"}), 400

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO weight_logs (id, username, record)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (id) 
                    DO UPDATE SET record = EXCLUDED.record, username = EXCLUDED.username
                """, (log_id, username, Json(log_item)))
            conn.commit()
        return jsonify({"status": "success", "message": f"Log {log_id} saved under {username}"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── 3. 删：依据唯一主键 ID 进行物理删除 ──
@weight_bp.route('/delete_weight', methods=['POST'])
def delete_weight():
    payload = request.json or {}
    log_id = payload.get('id')
    
    if not log_id:
        return jsonify({"error": "Missing id to delete"}), 400
        
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM weight_logs WHERE id = %s", (log_id,))
            conn.commit()
        return jsonify({"status": "success", "message": f"Log {log_id} deleted"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
# weight_app.py
import psycopg2
import psycopg2.extras
from psycopg2.extras import Json
from flask import Blueprint, request, jsonify

DATABASE_URL = "postgresql://neondb_owner:npg_orFfz1Kcp4he@ep-winter-mud-ai8mbpf4-pooler.c-4.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
weight_bp = Blueprint('weight_tracker', __name__)
waist_bp = Blueprint('waist_tracker', __name__)


def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS weight_logs (
                    id VARCHAR(50) NOT NULL,
                    username VARCHAR(50) NOT NULL,
                    record JSONB NOT NULL,
                    PRIMARY KEY (id)
                );
                CREATE INDEX IF NOT EXISTS idx_weight_logs_username ON weight_logs(username);

                CREATE TABLE IF NOT EXISTS waist_logs (
                    id VARCHAR(50) NOT NULL,
                    username VARCHAR(50) NOT NULL,
                    record JSONB NOT NULL,
                    PRIMARY KEY (id)
                );
                CREATE INDEX IF NOT EXISTS idx_waist_logs_username ON waist_logs(username);
            """)
        conn.commit()


try:
    init_db()
except Exception as e:
    print(f"⚠️ 初始化 weight_logs / waist_logs 表失败: {e}")


def _get_logs(table_name):
    username = request.args.get('username', 'default_user')
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT record FROM {table_name}
                    WHERE username = %s
                    ORDER BY record->>'timestamp' DESC
                """, (username,))
                rows = cur.fetchall()

        result = [row['record'] for row in rows]
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _save_log(table_name, label):
    payload = request.json or {}
    username = payload.get('username', 'default_user')
    log_item = payload.get('record') or payload
    log_id = log_item.get('id')

    if not log_id:
        return jsonify({"error": "Missing log unique ID"}), 400

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    INSERT INTO {table_name} (id, username, record)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (id)
                    DO UPDATE SET record = EXCLUDED.record, username = EXCLUDED.username
                """, (log_id, username, Json(log_item)))
            conn.commit()
        return jsonify({"status": "success", "message": f"{label} log {log_id} saved under {username}"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _delete_log(table_name, label):
    payload = request.json or {}
    log_id = payload.get('id')

    if not log_id:
        return jsonify({"error": "Missing id to delete"}), 400

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"DELETE FROM {table_name} WHERE id = %s", (log_id,))
            conn.commit()
        return jsonify({"status": "success", "message": f"{label} log {log_id} deleted"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Weight routes ──────────────────────────────────────────────
@weight_bp.route('/get_weight', methods=['GET'])
def get_weight():
    return _get_logs('weight_logs')


@weight_bp.route('/save_weight', methods=['POST'])
def save_weight():
    return _save_log('weight_logs', 'Weight')


@weight_bp.route('/delete_weight', methods=['POST'])
def delete_weight():
    return _delete_log('weight_logs', 'Weight')


# ── Waist routes ───────────────────────────────────────────────
@waist_bp.route('/get_waist', methods=['GET'])
def get_waist():
    return _get_logs('waist_logs')


@waist_bp.route('/save_waist', methods=['POST'])
def save_waist():
    return _save_log('waist_logs', 'Waist')


@waist_bp.route('/delete_waist', methods=['POST'])
def delete_waist():
    return _delete_log('waist_logs', 'Waist')

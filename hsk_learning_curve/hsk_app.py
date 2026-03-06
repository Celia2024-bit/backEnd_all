import asyncio
import io
import json
import requests
import edge_tts
from flask import Blueprint, request, send_file, jsonify
import os
from google.cloud import texttospeech
from .config import DATABASE_URL
import psycopg2
import psycopg2.extras
from psycopg2.extras import Json

render_secret_path = "/etc/secrets/google-tts-key.json"

# Render 上的绝对路径
RENDER_PATH = "/etc/secrets/google-tts-key.json"
# Windows 本地的绝对路径
WINDOWS_PATH = r"C:\workspace\Personals\backEnd_all\google-tts-key.json"

# --- 逻辑部分 ---
if os.environ.get("RENDER"):
    # 如果在 Render 环境
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = RENDER_PATH
    print(f"正在使用 Render 环境凭据: {RENDER_PATH}")
else:
    # 否则默认为本地环境
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = WINDOWS_PATH
    print(f"正在使用 Windows 本地凭据: {WINDOWS_PATH}")
    

hsk_bp = Blueprint('hsk_learning_curve', __name__)

def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)

# --- 1. 账号相关 ---
@hsk_bp.route('/register', methods=['POST'])
def register():
    data = request.json
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM users WHERE username = %s", (data['username'],))
            if cur.fetchone():
                return jsonify({"message": "User exists"}), 400
            cur.execute(
                "INSERT INTO users (username, password) VALUES (%s, %s)",
                (data['username'], data['password'])
            )
        conn.commit()
    return jsonify({"status": "success"}), 201

@hsk_bp.route('/login', methods=['POST'])
def login():
    data = request.json
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM users WHERE username = %s AND password = %s",
                (data['username'], data['password'])
            )
            if cur.fetchone():
                return jsonify({"status": "success", "username": data['username']}), 200
    return jsonify({"status": "error"}), 401


# --- 2. 数据获取 ---
@hsk_bp.route('/get_user_progress', methods=['GET'])
def get_user_progress():
    username = request.args.get('username')
    if not username:
        return jsonify({"error": "username is required"}), 400

    level = request.args.get('level')
    with get_conn() as conn:
        with conn.cursor() as cur:
            # 确保你确实查询了 flagged_words 列！
            query = "SELECT level, record, flagged_words FROM user_progress WHERE username = %s"
            params = [username]
            if level:
                query += " AND level = %s"
                params.append(level)
            
            cur.execute(query, params)
            rows = cur.fetchall()

    # 打印一下调试信息，看看数据库到底有没有拿到数据
    print(f"Debug: 查询到 {len(rows)} 行数据: {rows}")

    progress_map = {}
    for r in rows:
        progress_map[str(r['level'])] = {
            "record": r['record'] if r['record'] is not None else {},
            "flagged_words": r['flagged_words'] if r['flagged_words'] is not None else []
        }
    return jsonify(progress_map), 200


@hsk_bp.route('/get_user_mastery', methods=['GET'])
def get_user_mastery():
    """单独获取用户单词熟练度数据"""
    username = request.args.get('username')
    if not username:
        return jsonify({"error": "username is required"}), 400

    level = request.args.get('level')
    with get_conn() as conn:
        with conn.cursor() as cur:
            if level:
                cur.execute(
                    "SELECT level, char, record FROM word_mastery WHERE username = %s AND level = %s",
                    (username, level)
                )
            else:
                cur.execute(
                    "SELECT level, char, record FROM word_mastery WHERE username = %s",
                    (username,)
                )
            rows = cur.fetchall()

    # 现在的 r['record'] 已经是字典了，无需 json.loads
    mastery = {}
    for r in rows:
        key = f"{r['level']}_{r['char']}"
        # 简化代码，直接赋值
        mastery[key] = r['record'] if r['record'] is not None else {}
        
    return jsonify(mastery), 200


# --- 3. 数据保存 ---
 # 确保导入了 Json

@hsk_bp.route('/save_progress', methods=['POST'])
def save_progress():
    data = request.json
    username = data.get('username')
    level = data.get('level')
    record = data.get('record')

    if not username or level is None or record is None:
        return jsonify({"error": "username, level, and record are required"}), 400

    with get_conn() as conn:
        with conn.cursor() as cur:
            # 使用 Json(record) 将字典包装起来
            cur.execute("""
                INSERT INTO user_progress (username, level, record)
                VALUES (%s, %s, %s)
                ON CONFLICT (username, level) DO UPDATE SET record = EXCLUDED.record
            """, (username, level, Json(record))) # <--- 这里修改了
        conn.commit()

    return jsonify({"status": "success"}), 200


@hsk_bp.route('/save_mastery', methods=['POST'])
def save_mastery():
    data = request.json
    username = data.get('username')
    char = data.get('char')
    level = data.get('level')
    record = data.get('record')

    if not username or not char or level is None or record is None:
        return jsonify({"error": "username, char, level, and record are required"}), 400

    with get_conn() as conn:
        with conn.cursor() as cur:
            # 直接传入 record，不需要 json.dumps()
            cur.execute("""
                INSERT INTO word_mastery (username, char, level, record)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (username, char, level) DO UPDATE SET record = EXCLUDED.record
            """, (username, char, level, Json(record)))
        conn.commit()

    return jsonify({"status": "success"}), 200


# --- 4. TTS ---
@hsk_bp.route('/tts')
def tts():
    text = request.args.get('text', '')
    speed = request.args.get('speed', '0')
    voice = request.args.get('voice', 'cmn-CN-Wavenet-A')

    try:
        client = texttospeech.TextToSpeechClient()

        synthesis_input = texttospeech.SynthesisInput(text=text)

        voice_params = texttospeech.VoiceSelectionParams(
            language_code="cmn-CN",
            name=voice
        )

        speaking_rate = 1.0 + (int(speed) / 100)
        speaking_rate = max(0.25, min(4.0, speaking_rate))

        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=speaking_rate
        )

        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice_params,
            audio_config=audio_config
        )

        audio_stream = io.BytesIO(response.audio_content)
        return send_file(audio_stream, mimetype="audio/mpeg")

    except Exception as e:
        print(f"错误: {e}")
        return jsonify({"error": str(e)}), 500


# --- 5. 用户自定义词库 (CRUD) ---
@hsk_bp.route('/custom/cards', methods=['POST'])
def add_custom_card():
    """添加新卡片"""
    data = request.json
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO user_custom_cards (username, char, pinyin, meaning, explanation)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                data.get('username'),
                data.get('char'),
                data.get('pinyin'),
                data.get('meaning'),
                data.get('explanation')
            ))
        conn.commit()
    return jsonify({"status": "success"}), 201


@hsk_bp.route('/custom/cards/list/<username>', methods=['GET'])
def get_custom_cards_list(username):
    """获取用户所有的自定义卡片（管理页面用）"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM user_custom_cards WHERE username = %s ORDER BY created_at DESC",
                (username,)
            )
            rows = cur.fetchall()
    return jsonify([dict(r) for r in rows]), 200


@hsk_bp.route('/custom/cards/item/<int:card_id>', methods=['PATCH', 'DELETE'])
def handle_single_card(card_id):
    """修改或删除特定卡片"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            if request.method == 'PATCH':
                data = request.json
                fields = ', '.join(f"{k} = %s" for k in data.keys())
                values = list(data.values()) + [card_id]
                cur.execute(f"UPDATE user_custom_cards SET {fields} WHERE id = %s", values)
                conn.commit()
                return jsonify({"status": "updated"}), 200

            elif request.method == 'DELETE':
                cur.execute("DELETE FROM user_custom_cards WHERE id = %s", (card_id,))
                conn.commit()
                return jsonify({"status": "deleted"}), 200


# flagged_words
@hsk_bp.route('/flag_word', methods=['POST'])
def flag_word():
    data = request.json
    username = data.get('username')
    level = data.get('level')
    flagged_word = data.get('flagged_word')

    if not all([username, level is not None, flagged_word]):
        return jsonify({"error": "Missing parameters"}), 400

    with get_conn() as conn:
        with conn.cursor() as cur:
            # 直接操作独立出来的 flagged_words 列
            cur.execute("""
                INSERT INTO user_progress (username, level, flagged_words)
                VALUES (%s, %s, jsonb_build_array(%s::text))
                ON CONFLICT (username, level) DO UPDATE SET 
                flagged_words = (
                    SELECT jsonb_agg(DISTINCT x)
                    FROM jsonb_array_elements(
                        COALESCE(user_progress.flagged_words, '[]'::jsonb) || jsonb_build_array(%s::text)
                    ) t(x)
                )
            """, (username, level, flagged_word, flagged_word))
        conn.commit()
    return jsonify({"status": "success", "added": flagged_word}), 200
    
@hsk_bp.route('/unflag_word', methods=['POST'])
def unflag_word():
    data = request.json
    username = data.get('username')
    level = data.get('level')
    flagged_word = data.get('flagged_word')

    if not all([username, level is not None, flagged_word]):
        return jsonify({"error": "Missing parameters"}), 400

    with get_conn() as conn:
        with conn.cursor() as cur:
            # - 操作符直接从 JSONB 数组中移除匹配的字符串值
            # 注意：现在 WHERE 条件也应该针对 flagged_words 是否包含该词
            cur.execute("""
                UPDATE user_progress 
                SET flagged_words = (COALESCE(flagged_words, '[]'::jsonb) - %s)
                WHERE username = %s AND level = %s
            """, (flagged_word, username, level))
        conn.commit()
    return jsonify({"status": "success", "removed": flagged_word}), 200
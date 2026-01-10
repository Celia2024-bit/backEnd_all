import asyncio
import io
import requests
import edge_tts
from flask import Blueprint, request, send_file, jsonify
from .config import SUPABASE_URL, HEADERS 

hsk_bp = Blueprint('hsk_learning_curve', __name__)

# --- 辅助函数：简化 Supabase 请求 ---
def supabase_request(method, path, json_data=None, params=None):
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    response = requests.request(method, url, headers=HEADERS, json=json_data, params=params)
    if response.status_code >= 400:
        print(f"Supabase Error ({path}):", response.text)
    return response

# --- 1. 账号相关 ---
@hsk_bp.route('/register', methods=['POST'])
def register():
    data = request.json
    check = supabase_request("GET", "users", params={"username": f"eq.{data['username']}"})
    if check.json():
        return jsonify({"message": "User exists"}), 400
    supabase_request("POST", "users", json_data=data)
    return jsonify({"status": "success"}), 201

@hsk_bp.route('/login', methods=['POST'])
def login():
    data = request.json
    params = {"username": f"eq.{data['username']}", "password": f"eq.{data['password']}"}
    res = supabase_request("GET", "users", params=params)
    if res.json():
        return jsonify({"status": "success", "username": data['username']}), 200
    return jsonify({"status": "error"}), 401

# --- 2. 数据获取（拆分后）---


@hsk_bp.route('/get_user_progress', methods=['GET'])
def get_user_progress():
    username = request.args.get('username')
    if not username:
        return jsonify({"error": "username is required"}), 400

    level = request.args.get('level')
    params = {"username": f"eq.{username}"}
    if level:
        params["level"] = f"eq.{level}"

    p_res = supabase_request("GET", "user_progress", params=params)
    rows = p_res.json() or []
    rows = [r for r in rows if r.get("record") is not None]

    progress_map = {}
    for r in rows:
        lvl = str(r.get("level"))
        progress_map[lvl] = r["record"]

    # 有 level：map 只会包含那个 level；若没找到则为空 {}
    return jsonify(progress_map), 200


@hsk_bp.route('/get_user_mastery', methods=['GET'])
def get_user_mastery():
    """单独获取用户单词熟练度数据"""
    username = request.args.get('username')
    if not username:
        return jsonify({"error": "username is required"}), 400
    level = request.args.get('level')  # 新增：支持按级别筛选，减少数据量
    
    # 构建查询参数：用户名 + 可选级别筛选
    params = {"username": f"eq.{username}"}
    if level:
        params["level"] = f"eq.{level}"
    
    m_res = supabase_request("GET", "word_mastery", params=params)
    mastery = {}
    for item in m_res.json():
        # 键格式：level_char（保持和前端兼容）
        key = f"{item.get('level')}_{item['char']}"
        mastery[key] = item['record']
        
    return jsonify(mastery), 200

# --- 3. 数据保存 ---

@hsk_bp.route('/save_progress', methods=['POST'])
def save_progress():
    data = request.json
    username = data.get('username')
    level = data.get('level')
    record = data.get('record')

    if not username or level is None:
        return jsonify({"error": "username and level are required"}), 400
    if record is None:
        return jsonify({"error": "record is required"}), 400

    payload = {
        "username": username,
        "level": level,
        "record": record
    }

    headers = {**HEADERS, "Prefer": "resolution=merge-duplicates"}
    res = requests.post(f"{SUPABASE_URL}/rest/v1/user_progress", headers=headers, json=payload)
    if res.status_code >= 400:
        return jsonify({"error": "save failed", "detail": res.text}), 500

    return jsonify({"status": "success"}), 200

@hsk_bp.route('/save_mastery', methods=['POST'])
def save_mastery():
    data = request.json
    # 必传参数校验
    required_fields = ['username', 'char', 'level', 'record']
    for field in required_fields:
        if not data.get(field):
            return jsonify({"error": f"{field} is required"}), 400
    
    payload = {
        "username": data.get('username'),
        "char": data.get('char'),
        "level": data.get('level'),
        "record": data.get('record')
    }
    headers = {**HEADERS, "Prefer": "resolution=merge-duplicates"}
    requests.post(f"{SUPABASE_URL}/rest/v1/word_mastery", headers=headers, json=payload)
    return jsonify({"status": "success"}), 200

# --- 4. TTS ---
@hsk_bp.route('/tts')
def tts():
    # 获取参数
    text = request.args.get('text', '')
    # 默认声音设置为 Yunjian (Male)
    voice_name = request.args.get('voice', 'Mandarin Male (Yunjian)')
    # 获取语速参数，默认 0 (正常速度)
    speed = request.args.get('speed', '0')

    # 1. 声音映射（参考 tts_engine.py 的 VOICE_DICT）
    VOICE_DICT = {
        "Mandarin Female (Xiaoyi)": "zh-CN-XiaoyiNeural",
        "Mandarin Female (Xiaoxiao)": "zh-CN-XiaoxiaoNeural",
        "Mandarin Male (Yunxi)": "zh-CN-YunxiNeural",
        "Mandarin Male (Yunjian)": "zh-CN-YunjianNeural",
        "Mandarin Male (Yunxia)": "zh-CN-YunxiaNeural",
        "Mandarin Male (Yunyang)": "zh-CN-YunyangNeural",
    }
    selected_voice = VOICE_DICT.get(voice_name, "zh-CN-YunjianNeural")

    # 2. 语速格式化（参考 tts_engine.py 的 rate_str 逻辑）
    try:
        speed_val = int(speed)
        # 限制范围在 -50% 到 +100% 之间，防止数值过大导致接口报错
        speed_val = max(-100, min(100, speed_val))
        rate_str = f"{speed_val:+d}%"
    except ValueError:
        rate_str = "+0%"

    try:
        # 异步生成逻辑
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # 传入 rate 和 voice 参数
        communicate = edge_tts.Communicate(text, selected_voice, rate=rate_str)
        audio_stream = io.BytesIO()
        
        async def stream():
            async for chunk in communicate.stream():
                if chunk["type"] == "audio": 
                    audio_stream.write(chunk["data"])
        
        loop.run_until_complete(stream())
        audio_stream.seek(0)
        
        return send_file(audio_stream, mimetype="audio/mpeg")
    except Exception as e: 
        print(f"TTS Error: {e}")
        return str(e), 500
        
# --- 5. 用户自定义词库 (CRUD + Review List) ---
@hsk_bp.route('/custom/cards', methods=['POST'])
def add_custom_card():
    """添加新卡片"""
    data = request.json
    payload = {
        "username": data.get('username'),
        "char": data.get('char'),
        "pinyin": data.get('pinyin'),
        "meaning": data.get('meaning'),
        "explanation": data.get('explanation')
    }

    response = supabase_request("POST", "user_custom_cards", json_data=payload)
    return jsonify({"status": "success"}), response.status_code

@hsk_bp.route('/custom/cards/list/<username>', methods=['GET'])
def get_custom_cards_list(username):
    """获取用户所有的自定义卡片（管理页面用）"""
    params = {
        "username": f"eq.{username}",
        "order": "created_at.desc" # 按创建时间倒序排列
    }
    response = supabase_request("GET", "user_custom_cards", params=params)
    return jsonify(response.json()), response.status_code

@hsk_bp.route('/custom/cards/item/<card_id>', methods=['PATCH', 'DELETE'])
def handle_single_card(card_id):
    """修改或删除特定卡片"""
    params = {"id": f"eq.{card_id}"}
    
    if request.method == 'PATCH':
        data = request.json
        # 允许更新 mastery, pinyin, meaning, explanation 等
        response = supabase_request("PATCH", "user_custom_cards", json_data=data, params=params)
        return jsonify({"status": "updated"}), response.status_code
        
    elif request.method == 'DELETE':
        response = supabase_request("DELETE", "user_custom_cards", params=params)
        return jsonify({"status": "deleted"}), response.status_code
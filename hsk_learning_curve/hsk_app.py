import asyncio
import io
import requests
import edge_tts
from flask import Blueprint, request, send_file, jsonify
import os
from google.cloud import texttospeech
from .config import SUPABASE_URL, HEADERS 
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
    text = request.args.get('text', '')
    speed = request.args.get('speed', '0')
    voice = request.args.get('voice', 'cmn-CN-Wavenet-A')  # 默认女声A
    
    try:
        client = texttospeech.TextToSpeechClient()
        
        synthesis_input = texttospeech.SynthesisInput(text=text)
        
        voice_params = texttospeech.VoiceSelectionParams(
            language_code="cmn-CN",
            name=voice  # 直接使用传入的语音名称
        )
        
        # 处理语速：-50 到 +50 转为 0.5 到 1.5 倍速
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
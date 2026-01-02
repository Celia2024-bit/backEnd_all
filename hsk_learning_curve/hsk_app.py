import asyncio
import io
import requests
import edge_tts
from flask import Blueprint, request, send_file, jsonify
# 确保 config.py 在同一目录下，或者在 Python 路径中
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

# --- 2. 数据获取 ---
@hsk_bp.route('/get_user_data', methods=['GET'])
def get_user_data():
    username = request.args.get('username')
    p_res = supabase_request("GET", "user_progress", params={"username": f"eq.{username}"})
    progress = p_res.json()[0] if p_res.json() else {"level": 1, "current_index": 0, "quiz_count": 20}
    
    m_res = supabase_request("GET", "word_mastery", params={"username": f"eq.{username}"})
    mastery = {item['char']: item['record'] for item in m_res.json()}
    return jsonify({"progress": progress, "mastery": mastery})

# --- 3. 数据保存 ---
@hsk_bp.route('/save_progress', methods=['POST'])
def save_progress():
    data = request.json
    username = data.get('username')
    payload = {
        "username": username,
        "level": data.get('level'),
        "quiz_count": data.get('quizCount'),
        "current_index": data.get('index')
    }
    # 使用 upsert
    headers = {**HEADERS, "Prefer": "resolution=merge-duplicates"}
    requests.post(f"{SUPABASE_URL}/rest/v1/user_progress", headers=headers, json=payload)
    return {"status": "success"}

@hsk_bp.route('/save_mastery', methods=['POST'])
def save_mastery():
    data = request.json
    payload = {
        "username": data.get('username'),
        "char": data.get('char'),
        "record": data.get('record')
    }
    headers = {**HEADERS, "Prefer": "resolution=merge-duplicates"}
    requests.post(f"{SUPABASE_URL}/rest/v1/word_mastery", headers=headers, json=payload)
    return {"status": "success"}

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
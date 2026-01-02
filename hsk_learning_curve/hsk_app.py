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
    text = request.args.get('text')
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        communicate = edge_tts.Communicate(text, 'zh-CN-YunjianNeural')
        audio_stream = io.BytesIO()
        async def stream():
            async for chunk in communicate.stream():
                if chunk["type"] == "audio": audio_stream.write(chunk["data"])
        loop.run_until_complete(stream())
        audio_stream.seek(0)
        return send_file(audio_stream, mimetype="audio/mpeg")
    except Exception as e: return str(e), 500
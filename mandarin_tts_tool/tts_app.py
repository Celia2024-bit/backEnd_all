# -*- coding:utf-8 -*-
from flask import Flask, request, jsonify, send_file, abort, Blueprint
from flask_cors import CORS
import os
import sys
import tempfile
from pathlib import Path

# 导入您提供的OCR和TTS引擎
from .ocr_engine import OCREngine
from .tts_engine import TTSEngine, VOICE_DICT

tts_bp = Blueprint('mandarin-tts-tool', __name__)

# 初始化引擎
ocr_engine = OCREngine()
tts_engine = TTSEngine(clear_cache_on_start=False)

# 配置缓存目录
CACHE_DIR = Path(__file__).parent / "audio_cache"
CACHE_DIR.mkdir(exist_ok=True)

@tts_bp.route('/split-text', methods=['POST'])
def split_text():
    """分句接口：接收文本，返回分句结果"""
    try:
        data = request.get_json()
        text = data.get('text', '').strip()
        if not text:
            return jsonify({"error": "文本不能为空"}), 400
        
        # 使用TTS引擎的分句功能
        sentences = tts_engine.text_to_sentences(text)
        return jsonify({
            "success": True,
            "sentences": sentences,
            "count": len(sentences)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@tts_bp.route('/generate-single-audio', methods=['POST'])
def generate_single_audio():
    """生成单句音频接口"""
    try:
        data = request.get_json()
        sentence = data.get('sentence', '').strip()
        voice = data.get('voice', 'Mandarin Female (Xiaoyi)')
        speed = int(data.get('speed', 0))
        
        if speed < -50 or speed > 100:
            return jsonify({"error": "语速范围必须在-50% ~ +100%之间"}), 400
        
        if not sentence:
            return jsonify({"error": "句子不能为空"}), 400
        
        # 验证语音是否有效
        if voice not in VOICE_DICT:
            voice = 'Mandarin Female (Xiaoyi)'
        
        # 生成音频
        audio_path = tts_engine.generate_single_sentence_audio(sentence, VOICE_DICT[voice], speed)
        
        if str(audio_path).startswith("Error"):
            return jsonify({"error": audio_path}), 500
        
        # 返回音频文件路径（或直接返回文件）
        return jsonify({
            "success": True,
            "audio_path": audio_path,
            "filename": os.path.basename(audio_path)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@tts_bp.route('/generate-full-audio', methods=['POST'])
def generate_full_audio():
    """生成全文音频接口"""
    try:
        data = request.get_json()
        text = data.get('text', '').strip()
        voice = data.get('voice', 'Mandarin Female (Xiaoyi)')
        speed = int(data.get('speed', 0))
        if speed < -50 or speed > 100:
            return jsonify({"error": "语速范围必须在-50% ~ +100%之间"}), 400
        
        if not text:
            return jsonify({"error": "文本不能为空"}), 400
        
        if voice not in VOICE_DICT:
            voice = 'Mandarin Female (Xiaoyi)'
        
        audio_path, sentences = tts_engine.generate_full_audio(text, VOICE_DICT[voice], speed)
        
        if str(audio_path).startswith("Error"):
            return jsonify({"error": audio_path}), 500
        
        return jsonify({
            "success": True,
            "audio_path": audio_path,
            "filename": os.path.basename(audio_path),
            "sentences": sentences
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@tts_bp.route('/ocr-image', methods=['POST'])
def ocr_image():
    """OCR识别接口：接收图片文件，返回识别文本"""
    try:
        if not request.files.get('image'):
            return jsonify({"error": "未上传图片"}), 400
        
        # 保存上传的图片到临时文件
        image_file = request.files['image']
        with tempfile.NamedTemporaryFile(suffix=os.path.splitext(image_file.filename)[1], delete=False) as temp_file:
            image_file.save(temp_file)
            temp_file_path = temp_file.name
        
        # 执行OCR识别
        result = ocr_engine.ocr_image(temp_file_path)
        
        # 删除临时文件
        os.unlink(temp_file_path)
        
        # 判断结果是否为错误
        if result.startswith(("Error:", "Warning:")):
            return jsonify({"error": result}), 500
        
        return jsonify({
            "success": True,
            "text": result
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@tts_bp.route('/audio/<filename>')
def serve_audio(filename):
    """提供音频文件访问"""
    audio_path = os.path.join(tts_engine._audio_dir, filename)
    if os.path.exists(audio_path):
        return send_file(audio_path, mimetype='audio/mpeg')
    abort(404)

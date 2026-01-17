from flask import Blueprint, request, jsonify
from groq import Groq
from werkzeug.utils import secure_filename
import os

whisper_bp = Blueprint('whisper', __name__)

# ========================
# Groq Whisper 配置
# ========================
ALLOWED_EXTENSIONS = {'mp3', 'wav', 'm4a', 'webm', 'ogg', 'flac'}
MAX_FILE_SIZE = 25 * 1024 * 1024  # 25MB

# 替换成你的 Groq API Key
api_key = os.environ.get("GROQ_API_KEY")
client = Groq(api_key=api_key)

# ========================
# 辅助函数
# ========================
def allowed_file(filename):
    """检查文件类型是否允许"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ========================
# API 端点
# ========================

@whisper_bp.route('/transcribe', methods=['POST'])
def transcribe():
    """
    Groq Whisper 语音转文字接口
    
    参数:
        - audio: 音频文件 (multipart/form-data)
        - language: 语言代码 (可选，默认 'en')
                   支持: en, fr, zh, es, de, ja 等
    
    返回:
        {
            "success": true,
            "transcription": "转录文本",
            "language": "en"
        }
    """
    # 检查是否有文件
    if 'audio' not in request.files:
        return jsonify({'error': '没有上传文件'}), 400
    
    file = request.files['audio']
    
    if file.filename == '':
        return jsonify({'error': '文件名为空'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({
            'error': '不支持的文件格式',
            'supported': list(ALLOWED_EXTENSIONS)
        }), 400
    
    # 获取语言参数
    language = request.form.get('language', 'en')
    
    try:
        filename = secure_filename(file.filename)
        
        # 调用 Groq Whisper API
        transcription = client.audio.transcriptions.create(
            file=(filename, file.read()),
            model="whisper-large-v3",
            language=language,
            response_format="json"
        )
        
        return jsonify({
            'success': True,
            'transcription': transcription.text,
            'language': language
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'转录失败: {str(e)}'
        }), 500


@whisper_bp.route('/languages', methods=['GET'])
def get_supported_languages():
    """
    获取支持的语言列表
    """
    languages = {
        'en': 'English',
        'fr': 'Français',
        'zh': '中文',
        'es': 'Español',
        'de': 'Deutsch',
        'ja': '日本語',
        'ko': '한국어',
        'ru': 'Русский',
        'ar': 'العربية',
        'pt': 'Português',
        'it': 'Italiano',
        'nl': 'Nederlands',
        'pl': 'Polski',
        'tr': 'Türkçe',
        'vi': 'Tiếng Việt',
        'th': 'ไทย',
        'hi': 'हिन्दी'
    }
    return jsonify(languages)


@whisper_bp.route('/health', methods=['GET'])
def health_check():
    """
    健康检查接口
    """
    return jsonify({
        'status': 'ok',
        'service': 'whisper',
        'model': 'whisper-large-v3',
        'provider': 'groq'
    })
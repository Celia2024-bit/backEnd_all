from flask import Flask, render_template
from flask_cors import CORS
from flashcard_english.flashcard_app import flashcard_bp
from mandarin_tts_tool.tts_app import tts_bp
from hsk_learning_curve.hsk_app import hsk_bp
from whisper_transcribe.whisper_app import whisper_bp

app = Flask(__name__)
CORS(app)

# ========================
# 主页路由
# ========================
@app.route('/')
def index():
    """Whisper 语音转文字主页"""
    return render_template('index.html')

@app.route('/hello')
def hello():
    return "Hello! The server is working!"

# ========================
# 注册所有蓝图
# ========================
app.register_blueprint(flashcard_bp, url_prefix='/api/flashcard')
app.register_blueprint(tts_bp, url_prefix='/api/tts')
app.register_blueprint(hsk_bp, url_prefix='/api/hsk')
app.register_blueprint(whisper_bp, url_prefix='/api/whisper')

if __name__ == "__main__":
    print("\n" + "="*60)
    print("🚀 服务器启动成功")
    print("="*60)
    print("\n📍 访问地址:")
    print("  - http://localhost:5000          (Whisper 前端)")
    print("  - http://localhost:5000/hello    (健康检查)")
    print("\n📡 API 端点:")
    print("  - /api/flashcard/*")
    print("  - /api/tts/*")
    print("  - /api/hsk/*")
    print("  - /api/whisper/*")
    print("\n" + "="*60 + "\n")
    
    app.run(host='0.0.0.0', port=5000, debug=True)
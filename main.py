from flask import Flask
from flask_cors import CORS
from flashcard_english.flashcard_app import flashcard_bp
from mandarin_tts_tool.tts_app import tts_bp

app = Flask(__name__)
CORS(app)
@app.route('/hello')
def hello():
    return "Hello! The server is working!"

# 注册蓝图
app.register_blueprint(flashcard_bp, url_prefix='/api/flashcard')
app.register_blueprint(tts_bp, url_prefix='/api/tts')

if __name__ == "__main__":
    # 统一监听 8000 端口
    app.run(host='0.0.0.0', port=5000)
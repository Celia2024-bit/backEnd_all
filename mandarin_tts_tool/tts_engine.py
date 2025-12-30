# -*- coding:utf-8 -*-
import os
import sys
import re
import hashlib
import asyncio
import edge_tts
import time
import shutil
import ssl
import certifi
from pathlib import Path

# --- 跨平台配置 ---
# Windows/macOS通用语音字典
VOICE_DICT = {
    "Mandarin Female (Xiaoyi)": "zh-CN-XiaoyiNeural",  # Cartoon, Novel
    "Mandarin Female (Xiaoxiao)": "zh-CN-XiaoxiaoNeural",  # News, Novel
    "Mandarin Male (Yunxi)": "zh-CN-YunxiNeural",  # Novel
    "Mandarin Male (Yunjian)": "zh-CN-YunjianNeural",  # Sports, Novel
    "Mandarin Male (Yunxia)": "zh-CN-YunxiaNeural",  # Cartoon, Novel
    "Mandarin Male (Yunyang)": "zh-CN-YunyangNeural",  # News
    "Northeast Mandarin Female (Xiaobei)": "zh-CN-liaoning-XiaobeiNeural",  # Dialect
    "Shaanxi Mandarin Female (Xiaoni)": "zh-CN-shaanxi-XiaoniNeural",  # Dialect
}

# --- 核心修复：SSL证书（跨平台）---
def fix_ssl_context():
    """修复SSL证书验证（macOS打包必加，Windows兼容）"""
    try:
        cert_path = certifi.where()
        def patched_create_default_context(*args, **kwargs):
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.load_verify_locations(cert_path)
            return ctx
        ssl.create_default_context = patched_create_default_context
        print(f"SSL context fixed with cert: {cert_path}")
    except Exception as e:
        print(f"Warning: Failed to fix SSL context: {e}")

# --- 核心修复：异步函数执行（跨平台）---
def run_async_task(func, *args):
    """同步执行异步函数（解决打包后asyncio.run()报错问题）"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(func(*args))

# --- 跨平台路径工具 ---
def get_audio_dir(app_name="MandarinTTS", sub_dir="audio_cache"):
    """
    获取跨平台可写的音频缓存目录
    - Windows: %APPDATA%\MandarinTTS\audio_cache
    - macOS: ~/Library/Application Support/MandarinTTS/audio_cache
    - 开发环境: 当前目录/audio_cache
    """
    if getattr(sys, 'frozen', False):
        # 打包后环境
        if sys.platform == "win32":
            # Windows
            base_dir = Path(os.getenv("APPDATA")) / app_name
        elif sys.platform == "darwin":
            # macOS
            base_dir = Path.home() / "Library" / "Application Support" / app_name
        else:
            # Linux（备用）
            base_dir = Path.home() / ".config" / app_name
        audio_dir = base_dir / sub_dir
    else:
        # 开发环境
        audio_dir = Path(sub_dir)
    
    # 创建目录（兼容Python3.6+）
    audio_dir.mkdir(parents=True, exist_ok=True)
    return str(audio_dir)

# 初始化SSL修复（必须在最开始执行）
fix_ssl_context()

# 全局音频目录（跨平台）
AUDIO_DIR = get_audio_dir()

class TTSEngine:
    """
    跨平台TTS引擎（兼容macOS/Windows，支持打包/开发环境）
    """
    def __init__(self, audio_dir=None, clear_cache_on_start=True):
        # 使用跨平台路径
        self._audio_dir = audio_dir or AUDIO_DIR
        Path(self._audio_dir).mkdir(parents=True, exist_ok=True)

        # 清空缓存（可选）
        if clear_cache_on_start:
            self._clear_cache()
    
    def _clear_cache(self):
        """清空缓存（跨平台兼容）"""
        try:
            cache_dir = Path(self._audio_dir)
            if not cache_dir.exists():
                return
            
            for item in cache_dir.iterdir():
                try:
                    if item.is_file():
                        item.unlink()
                    elif item.is_dir():
                        shutil.rmtree(item)
                except Exception as e:
                    print(f"Warning: Failed to delete {item}: {e}")
            print(f"Cache cleared: {self._audio_dir}")
        except Exception as e:
            print(f"Warning: Failed to clear cache directory: {e}")
        
    def text_to_sentences(self, text):
        """分句逻辑（保持不变）"""
        if not text:
            return []
            
        delimiters = r'[。？！；]'
        sentences = re.split(delimiters, text)
        
        result = []
        text_to_consume = text 
        
        for sentence in sentences:
            sentence = sentence.strip()
            if sentence:
                sentence_start_index = text_to_consume.find(sentence)
                if sentence_start_index == -1:
                    continue

                delimiter_search_area = text_to_consume[sentence_start_index + len(sentence):]
                match = re.search(delimiters, delimiter_search_area)
                delimiter = match.group(0) if match else ''
                
                result.append(sentence + delimiter)
                
                if match:
                    delimiter_end_index = delimiter_search_area.find(delimiter) + len(delimiter)
                    text_to_consume = delimiter_search_area[delimiter_end_index:]
                else:
                    text_to_consume = ""
             
        return [s.strip() for s in result if s.strip()]

    def _get_safe_text(self, text):
        """
        生成安全的哈希名（兼容Windows文件名限制）
        - 使用SHA256（比SHA1更安全）
        - 限制长度，避免Windows路径过长
        """
        normalized_text = "".join(text.split())
        # 兼容Python3.6+的哈希方式
        hash_obj = hashlib.sha256(normalized_text.encode('utf-8'))
        return hash_obj.hexdigest()[:16]  # 缩短哈希长度（避免路径过长）

    async def _async_generate(self, text, voice, rate, filepath):
        """异步生成音频（保持核心逻辑，增加异常捕获）"""
        try:
            rate_str = f"{rate:+d}%" if isinstance(rate, int) else f"{rate}%"
            communicate = edge_tts.Communicate(text, voice, rate=rate_str)
            await communicate.save(filepath)
            print(f"Generated audio: {filepath}")
        except Exception as e:
            print(f"Error generating audio for '{text[:20]}...': {e}")
            raise  # 重新抛出异常，让上层处理

    def _get_audio_file_path(self, text, voice, rate, prefix="full"):
        """生成跨平台安全的文件路径"""
        voice_key = voice.replace('-', '_').replace(':', '_')  # 替换Windows非法字符
        safe_hash = self._get_safe_text(text)
        # 限制文件名长度（Windows最大255字符）
        filename = f"{prefix}_{voice_key}_{rate}_{safe_hash}.mp3"
        # 使用Path拼接（跨平台兼容）
        return str(Path(self._audio_dir) / filename)
        
    # --- 完整音频生成（替换asyncio.run为run_async_task）---
    def generate_full_audio(self, text, voice, rate):
        if not text.strip():
            return "Error: Input text is empty.", []

        sentences = self.text_to_sentences(text)
        full_text_clean = "".join(sentences)
        
        cached_path = self._get_audio_file_path(full_text_clean, voice, rate, prefix="full")

        if Path(cached_path).exists():
            print(f"TTS Full Cache Hit: Found audio at {cached_path}")
            return cached_path, sentences
        
        print(f"TTS Full Cache Miss: Generating new audio to {cached_path}")
        
        try:
            # 替换asyncio.run为跨平台的run_async_task
            run_async_task(self._async_generate, full_text_clean, voice, rate, cached_path)
            return cached_path, sentences
        except Exception as e:
            return f"Error: TTS Generation Failed: {str(e)}", []
            
    # --- 单句音频生成 ---
    def generate_single_sentence_audio(self, sentence, voice, rate):
        if not sentence.strip():
            return "Error: Input sentence is empty."

        cached_path = self._get_audio_file_path(sentence, voice, rate, prefix="single")

        if Path(cached_path).exists():
            print(f"TTS Single Cache Hit: Found audio at {cached_path}")
            return cached_path
        
        print(f"TTS Single Cache Miss: Generating new single audio to {cached_path}")
        
        try:
            run_async_task(self._async_process_single_sentence, sentence, voice, rate)
            return cached_path
        except Exception as e:
            return f"Error: TTS Generation Failed: {str(e)}"

    async def _async_process_single_sentence(self, sentence, voice, rate):
        """异步处理单句（保持不变）"""
        if not sentence.strip():
            return "Error: Input sentence is empty."

        cached_path = self._get_audio_file_path(sentence, voice, rate, prefix="single")

        if Path(cached_path).exists():
            return cached_path
        
        print(f"TTS Single Cache Miss: Generating new single audio to {cached_path}")
        
        try:
            await self._async_generate(sentence, voice, rate, cached_path)
            return cached_path
        except Exception as e:
            return f"Error: TTS Generation Failed: {str(e)}"
        
    # --- 批量处理（替换asyncio.run为run_async_task）---
    def process_all_sentences_sync(self, sentences, voice, rate):
        """同步包装批量处理（供外部调用）"""
        return run_async_task(self.process_all_sentences, sentences, voice, rate)

    async def process_all_sentences(self, sentences, voice, rate):
        """异步批量处理（保持核心逻辑）"""
        if not sentences:
            return True
        
        print(f"Starting concurrent batch generation for {len(sentences)} sentences...")
        
        tasks = [self._async_process_single_sentence(s, voice, rate) for s in sentences]
        
        # Run all generation tasks concurrently using asyncio.gather
        results = await asyncio.gather(*tasks)
        
        # Check results
        success = True
        for i, result in enumerate(results):
            if result.startswith("Error"):
                print(f"Error during pre-caching sentence {i+1}: {result}")
                success = False
                
        return success


# --- 测试代码（适配跨平台）---
if __name__ == "__main__":
    print("--- Testing TTSEngine Module (Cross-Platform) ---")
    print(f"Python Version: {sys.version}")
    print(f"OS Platform: {sys.platform}")
    print(f"Audio Directory: {AUDIO_DIR}")
    
    # 测试文本
    test_text = """
我想谈一谈中国在过去四十年中的非凡发展。我选择这个主题，是因为中国如今在许多领域已经成为世界领军者，尤其是在经济和科技方面。我也希望讨论一下促成这一成功的一些原因。首先需要理解的是，四十年前的中国还是一个非常贫穷的国家，许多人生活在贫困线以下。当时的主要产业是农业。政府 认识到，为了与其他国家竞争，中国必须实现发展。因此，在世纪年代初，政府决定进行一系列经济改革。政府大力投资基础设施，升级或新建了许多设施，例如北京新机场和公路网络。如今，中国拥有世界上最大的高速铁路网络，使主要城市之间的连接变得非常快捷和便利。人员和货物能够快速在全国流 动，从而创造大量就业机会。这些资金来自享受特别经济区税收优惠的外国投资者。政府也在人民身上投入，尤其是在教育和性别平等方面。例如，中国如今拥有一些世界顶尖的大学。技术创新是中国迅速发展的主要原因之大型外国公司若想在华投资，必须分享其技术；而中国企业也获得政府的财政支持。科技研究与创新受到鼓励，所有这些都推动了中国的快速发展
    """.strip()
    
    test_sentence = "我想谈一谈中国在过去四十年中的非凡发展。"
    test_voice = VOICE_DICT["Mandarin Female (Xiaoxiao)"]
    test_rate = 0
    
    # 初始化引擎（使用跨平台路径）
    test_engine = TTSEngine(audio_dir=get_audio_dir(sub_dir="test_audio_cache"))
    
    print(f"Test Voice: {test_voice}")
    print(f"Test Audio Dir: {test_engine._audio_dir}")

    # 1. 测试分句
    print("\n1. Testing Sentence Splitting:")
    sentences = test_engine.text_to_sentences(test_text)
    print(f"Total Sentences: {len(sentences)}")
    for i, s in enumerate(sentences[:5]):  # 只打印前5句，避免日志过长
        print(f"  [{i+1}] {s}")
    
    # 2. 测试完整音频生成（缓存未命中）
    print("\n2. Testing Full Audio Generation (Cache Miss):")
    start_time_full = time.time()
    path1, list1 = test_engine.generate_full_audio(test_text, test_voice, test_rate)
    end_time_full = time.time()
    print(f"Full Path 1: {path1}")
    print(f"Full Time Taken: {end_time_full - start_time_full:.2f}s")

    # 3. 测试完整音频缓存（命中）
    print("\n3. Testing Full Audio Retrieval (Cache Hit):")
    start_time_cache = time.time()
    path2, list2 = test_engine.generate_full_audio(test_text, test_voice, test_rate)
    end_time_cache = time.time()
    print(f"Full Path 2: {path2}")
    print(f"Cache Time Taken: {end_time_cache - start_time_cache:.2f}s")
    
    # 4. 测试单句生成（缓存未命中）
    print("\n4. Testing Single Sentence Generation (Cache Miss):")
    start_time_single = time.time()
    path3 = test_engine.generate_single_sentence_audio(test_sentence, test_voice, test_rate)
    end_time_single = time.time()
    print(f"Single Path 1: {path3}")
    print(f"Single Time Taken: {end_time_single - start_time_single:.2f}s")
    
    # 5. 测试单句缓存（命中）
    print("\n5. Testing Single Sentence Retrieval (Cache Hit):")
    start_time_single_cache = time.time()
    path4 = test_engine.generate_single_sentence_audio(test_sentence, test_voice, test_rate)
    end_time_single_cache = time.time()
    print(f"Single Path 2: {path4}")
    print(f"Single Cache Time Taken: {end_time_single_cache - start_time_single_cache:.2f}s")
    
    # 6. 测试批量生成（缓存未命中）
    print("\n6. Testing Batch Sentence Processing (Cache Miss):")
    start_time_batch = time.time()
    # 替换asyncio.run为同步包装函数
    batch_success_1 = test_engine.process_all_sentences_sync(sentences, test_voice, test_rate)
    end_time_batch = time.time()
    print(f"Batch Processing Success (1): {batch_success_1}")
    print(f"Batch Time Taken (1): {end_time_batch - start_time_batch:.2f}s")

    # 7. 测试批量缓存（命中）
    print("\n7. Testing Batch Sentence Processing (Cache Hit):")
    start_time_batch_cache = time.time()
    batch_success_2 = test_engine.process_all_sentences_sync(sentences, test_voice, test_rate)
    end_time_batch_cache = time.time()
    print(f"Batch Processing Success (2): {batch_success_2}")
    print(f"Batch Time Taken (2): {end_time_batch_cache - start_time_batch_cache:.2f}s")

    # 最终验证
    print("\n--- Final Verification ---")
    success = True
    if path1.startswith("Error") or path3.startswith("Error"):
        print("Status: FAILED. TTS Engine reported an error during generation.")
        success = False
    elif path1 == path2 and path3 == path4 and (end_time_cache - start_time_cache) < 0.5:
        print("Status: SUCCESS. Full and Single TTS logic is sound, and caching works efficiently.")
    else:
        print("Status: FAILED. Path mismatch or slow cache retrieval detected.")
        success = False
        
    if not batch_success_1 or not batch_success_2:
        print("Status: FAILED. Batch processing reported an error.")
        success = False
    elif (end_time_batch_cache - start_time_batch_cache) < 0.5:
        print("Status: SUCCESS. Batch processing is fast on cache hit.")
    else:
        print("Status: FAILED. Cache retrieval was slow.")
        success = False

    print(f"\nOverall Test Status: {'SUCCESS' if success else 'FAILED'}")

    # 可选清理
    # if input("Clean up test cache? (y/n): ").lower() == 'y':
    #     shutil.rmtree(test_engine._audio_dir, ignore_errors=True)
    #     print("Test cache cleaned.")
import requests
from flask import Flask, request, jsonify, Blueprint, current_app
from flask_cors import CORS
import os
import json
import time
from .config import SUPABASE_URL, SUPABASE_KEY, MODULE_TO_TABLE, HEADERS
from datetime import date, timedelta
from .srs_calculator_supabase import (
    calculate_state_after_review,
    calculate_state_after_application,
    generate_must_use_list,
    calculate_priority_score_P
)


# ==========================================================
# SRS 算法后端函数（自动计算 ci, lrd, lad）
# ==========================================================

def get_all_cards_srs_state_supabase(module_id='mod1'):
    """从 Supabase 读取所有卡片的 SRS 状态"""
    try:
        records = supabase_fetch(
            'GET',
            module_id,
            params={'select': 'cardid,data,ci,lrd,lad,is_core,rc'}
        )
        
        card_list = []
        for record in records:
            card_data = record.get('data', {})
            
            card_dict = {
                'card_id': record.get('cardid'),
                'id': record.get('cardid'),
                'key_module': card_data.get('title', ''),
                'CI': record.get('ci') or 5,
                'LRD': date.fromisoformat(record.get('lrd')) if record.get('lrd') else date.today(),
                'LAD': date.fromisoformat(record.get('lad')) if record.get('lad') else date.today(),
                'is_core': bool(record.get('is_core', 0)),
                'referenceCount': record.get('rc') or 0
            }
            
            card_list.append(card_dict)
        
        return card_list
        
    except Exception as e:
        print(f"❌ 读取 SRS 状态时出错: {e}")
        return []


def update_card_srs_state_supabase(module_id, card_id, ci, lrd, lad, is_core,rc=None):
    """将 SRS 算法计算后的新状态写回 Supabase"""
    try:
        lrd_str = lrd.isoformat() if hasattr(lrd, 'isoformat') else str(lrd)
        lad_str = lad.isoformat() if hasattr(lad, 'isoformat') else str(lad)
        
        data_to_update = {
            'ci': ci,
            'lrd': lrd_str,
            'lad': lad_str,
            'is_core': 1 if is_core else 0
        }
        
        if rc is not None:
            data_to_update['rc'] = rc
         
        result = supabase_fetch(
            'PATCH',
            module_id,
            params={'cardid': f'eq.{card_id}'},
            json_data=data_to_update
        )
        
        if result and len(result) > 0:
            print(f"💾 卡片 {card_id} SRS 状态已更新: CI={ci}, LRD={lrd_str}, LAD={lad_str}")
            return True
        else:
            print(f"❌ 更新失败：未找到卡片 {card_id}")
            return False
            
    except Exception as e:
        print(f"❌ 更新 SRS 状态时出错: {e}")
        return False


# --- Flask 应用初始化 ---
flashcard_bp = Blueprint('flashCard_english', __name__)

def supabase_fetch(method, module_id, params=None, json_data=None):
    """
    封装对 Supabase PostgREST API 的 HTTP 请求
    """
    table_name = MODULE_TO_TABLE.get(module_id)
    if not table_name:
        raise ValueError(f"未知模块: {module_id}")
        
    url = f"{SUPABASE_URL}/rest/v1/{table_name}"
    
    response = requests.request(
        method=method,
        url=url,
        headers=HEADERS,
        params=params, 
        json=json_data  
    )

    if not response.ok:
        error_msg = response.text or response.reason
        # 抛出 Supabase API 错误
        raise Exception(f"Supabase API Error {response.status_code}: {error_msg}")
        
    try:
        return response.json()
    except requests.exceptions.JSONDecodeError:
        return []

def transform_from_supabase(records):
    """
    将 Supabase 返回的记录转换为前端所需的卡片格式
    """
    cards = []
    for record in records:
        if isinstance(record, dict) and 'cardid' in record and 'data' in record:
            # 合并 cardid 和 data 字段内容，确保 cardid 存在
            cards.append({**record['data'], 'cardid': record['cardid']})
    return cards

# --- 辅助函数：处理初始数据导入 ---
def initialize_data(module_id):
    # 1. 检查 Supabase 表中是否有数据
    try:
        table_name = MODULE_TO_TABLE[module_id]
        
        # 🚨 修正检查逻辑：只尝试获取一条记录 🚨
        check_response = requests.get(
            f"{SUPABASE_URL}/rest/v1/{table_name}",
            headers=HEADERS,
            params={'select': 'cardid', 'limit': 1} # 只获取 'cardid' 字段的一条记录
        )
        check_response.raise_for_status()
        
        # 检查返回的 JSON 列表是否为空
        if len(check_response.json()) > 0:
            return # 表格已有数据，跳过导入
            
    except Exception as e:
        print(f"❌ 初始数据检查失败（{module_id}）: {e}")
        return

    # 2. 如果表为空，则从本地 JSON 文件加载数据
    try:
        filename = f'{module_id}_cards.json'
        with open(filename, 'r', encoding='utf-8') as f:
            initial_data = json.load(f)
        
        data_to_insert = []
        for card in initial_data:
            # 准备插入 Supabase 的格式：将整个卡片对象放到 data 字段，cardid 单独提取
            data_to_insert.append({
                'cardid': card.get('cardid'),
                'data': card
            })
            
        if data_to_insert:
            # 3. 批量插入到 Supabase (使用 on_conflict 避免初始数据重复插入失败)
            # 注意：Supabase API 的批量 POST 行为可能需要额外处理，这里使用最简模型
            requests.post(
                f"{SUPABASE_URL}/rest/v1/{table_name}",
                headers=HEADERS,
                json=data_to_insert,
                params={'on_conflict': 'cardid'} 
            ).raise_for_status()
            
            print(f"📥 成功将 {module_id} 的 {len(initial_data)} 条初始数据导入 Supabase")
        
    except FileNotFoundError:
        print(f"⚠️ 警告: 找不到初始数据文件 {filename}，跳过导入。")
    except Exception as e:
        print(f"❌ 初始数据导入失败（{module_id}）: {e}")


# --- 应用程序上下文中的初始化检查 ---
# 首次收到请求时触发连接和数据检查
@flashcard_bp.before_app_request
def check_initial_data():
    if not hasattr(current_app, 'initial_data_checked'):
        print("--- 尝试连接 Supabase 并检查初始数据 ---")
        # 如果这里失败，前端的 API 调用也会失败，并返回 500
        initialize_data('mod1')
        initialize_data('mod2')
        current_app.initial_data_checked = True 


# ==========================================================
# API 路由定义 
# ==========================================================

# 1. GET: 获取所有卡片 (对应 loadCardsData)
@flashcard_bp.route('/<module_id>/cards', methods=['GET'])
def get_all_cards(module_id):
    """GET /mod1/cards"""
    try:
        # 获取所有 cardid 和 data 字段
        supabase_records = supabase_fetch('GET', module_id, params={'select': 'cardid,data'})
        cards = transform_from_supabase(supabase_records)
        
        return jsonify(cards), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# 2. POST: 添加新卡片 (对应 addCard)
@flashcard_bp.route('/<module_id>/cards', methods=['POST'])
def add_card(module_id):
    """POST /mod1/cards - 添加新卡片"""
    try:
        new_card_data = request.json
        card_id = new_card_data.get('cardid') 
        
        if not card_id:
            # 🔥 智能逻辑：找出现有卡片中最大的编号
            existing_cards = supabase_fetch(
                'GET', 
                module_id, 
                params={'select': 'cardid'}
            )
            
            # 提取所有编号
            max_number = 0
            for card in existing_cards:
                card_id_str = card.get('cardid', '')
                if card_id_str.startswith(f"{module_id}_card_"):
                    try:
                        number = int(card_id_str.split('_')[-1])
                        max_number = max(max_number, number)
                    except ValueError:
                        pass
            
            # 生成新的编号（最大编号 + 1）
            next_number = max_number + 1
            card_id = f"{module_id}_card_{next_number}"

        # ⭐ 设置初始 SRS 状态
        TODAY = date.today()
        initial_ci = 5
        initial_lrd = (TODAY - timedelta(days=5)).isoformat()
        initial_lad = (TODAY - timedelta(days=1)).isoformat()
        initial_is_core = 1
        
        # ⭐ 插入数据时包含 SRS 字段
        data_to_insert = {
            'cardid': card_id,
            'data': new_card_data,
            'ci': initial_ci,           # ⭐ 添加初始间隔
            'lrd': initial_lrd,         # ⭐ 添加初始复习日期
            'lad': initial_lad,         # ⭐ 添加初始应用日期
            'is_core': initial_is_core,   # ⭐ 添加核心标记
            'rc' :  0
        }

        # 插入数据
        result = supabase_fetch('POST', module_id, json_data=data_to_insert)
        
        if not result or len(result) == 0:
            raise Exception("Supabase 插入卡片失败。请检查 RLS 策略或数据库唯一约束。")
        
        # 返回新卡片（包含 SRS 状态）
        new_card = {
            **result[0]['data'], 
            'cardid': result[0]['cardid'],
            'ci': result[0]['ci'],
            'lrd': result[0]['lrd'],
            'lad': result[0]['lad'],
            'is_core': result[0]['is_core'],
            'rc' : result[0]['rc']
        }
        
        print(f"✅ 新卡片 {card_id} 已添加，初始 SRS 状态: CI={initial_ci}, LRD={initial_lrd}, LAD={initial_lad}")
        
        return jsonify({"success": True, "card": new_card}), 201

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# 3. PUT: 更新卡片 (对应 updateCard)
@flashcard_bp.route('/<module_id>/cards/<card_id>', methods=['PUT'])
def update_card(module_id, card_id):
    """PUT /mod1/cards/mod1_card_1"""
    try:
        updates = request.json
        updates.pop('cardid', None)
        
        # 构建更新内容：只更新 Supabase 表中的 data 字段
        # 注意：这里需要确保 Supabase 的 RLS (行级安全) 策略允许更新。
        data_to_update = {'data': updates}

        # PATCH 到 Supabase，使用 params 进行过滤 (WHERE cardid = 'eq.card_id')
        result = supabase_fetch(
            'PATCH', 
            module_id, 
            params={'cardid': f'eq.{card_id}'}, 
            json_data=data_to_update
        )

        if not result:
            return jsonify({'error': f'未找到卡片: {card_id} 或更新失败 (可能是 RLS 策略阻止)'}), 404
        
        # 重新获取更新后的卡片信息
        updated_card = transform_from_supabase(result)[0]
        return jsonify({"success": True, "card": updated_card}), 200

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# 4. DELETE: 删除卡片 (对应 deleteCard)
@flashcard_bp.route('/<module_id>/cards/<card_id>', methods=['DELETE'])
def delete_card(module_id, card_id):
    """DELETE /mod1/cards/mod1_card_1"""
    try:
        # DELETE 请求，使用 params 进行过滤 (WHERE cardid = 'eq.card_id')
        supabase_fetch(
            'DELETE', 
            module_id, 
            params={'cardid': f'eq.{card_id}'}
        )
            
        return jsonify({"success": True}), 200

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# 5. POST: 重置为原始 JSON 数据 (对应 resetToOriginal)
@flashcard_bp.route('/<module_id>/reset', methods=['POST'])
def reset_cards(module_id):
    """POST /mod1/reset"""
    try:
        # 1. 清空 Supabase 表中的所有数据
        supabase_fetch('DELETE', module_id, params={'cardid': 'not.is.null'}) 
        
        # 2. 从本地 JSON 文件重新导入数据
        filename = f'{module_id}_cards.json'
        with open(filename, 'r', encoding='utf-8') as f:
            initial_data = json.load(f)
            
        data_to_insert = [
            {'cardid': card.get('cardid'), 'data': card}
            for card in initial_data
        ]
        
        if data_to_insert:
            # 3. 批量插入
            requests.post(
                f"{SUPABASE_URL}/rest/v1/{MODULE_TO_TABLE[module_id]}",
                headers=HEADERS,
                json=data_to_insert,
                params={'on_conflict': 'cardid'}
            ).raise_for_status()

        count = len(initial_data)
        return jsonify({"success": True, "message": f"模块 {module_id} 已重置", "count": count})
    except Exception as e:
        return jsonify({"success": False, "error": f"重置失败: {e}"}), 500

# 6. POST: 导入卡片数据 (对应 importCardsFromFile)
@flashcard_bp.route('/<module_id>/import', methods=['POST'])
def import_cards(module_id):
    """POST /mod1/import"""
    try:
        data = request.json
        cards_to_import = data.get('cards')
        
        if not isinstance(cards_to_import, list):
            return jsonify({'error': '导入数据必须是 JSON 数组'}), 400

        # 1. 清空当前 Supabase 表
        supabase_fetch('DELETE', module_id, params={'cardid': 'not.is.null'})

        # 2. 批量插入新数据
        data_to_insert = [
            {'cardid': card.get('cardid'), 'data': card}
            for card in cards_to_import
        ]

        if data_to_insert:
            requests.post(
                f"{SUPABASE_URL}/rest/v1/{MODULE_TO_TABLE[module_id]}",
                headers=HEADERS,
                json=data_to_insert,
                params={'on_conflict': 'cardid'}
            ).raise_for_status()


        count = len(cards_to_import)
        return jsonify({"success": True, "count": count})
    except Exception as e:
        return jsonify({"success": False, "error": f"导入失败: {e}"}), 500

@flashcard_bp.route('/<module_id>/srs/today', methods=['GET'])
def get_today_cards(module_id):
    """GET /mod1/srs/today - 获取今日必学卡片"""
    try:
        # 1. 从 Supabase 读取数据
        cards = get_all_cards_srs_state_supabase(module_id)
        
        # 🔍 调试打印：看看数据库一共吐出来多少东西
        print(f"\n--- 🔍 SRS 调试开始 ({module_id}) ---")
        print(f"1. 数据库总卡片数: {len(cards) if cards else 0}")
        if cards and len(cards) > 0:
            print(f"   第一张卡片样例: {cards[0]}") # 检查字段名是否为 CI, LRD 等

        if not cards:
            print("⚠️ 警告: 数据库返回为空")
            return jsonify({
                "success": False,
                "error": "没有找到卡片数据"
            }), 404
        
        # 2. 调用 SRS 算法生成今日清单
        today_cards = generate_must_use_list(cards)
        
        # 🔍 调试打印：看看算法过滤后剩下多少
        print(f"2. 经过算法过滤后的今日必学数: {len(today_cards)}")
        
        # 3. 返回结果
        result = []
        for card in today_cards:
            p_score = calculate_priority_score_P(card)
            # 🔍 打印每一张入选卡片的详情，确认字段匹配
            print(f"   ✅ 入选: {card.get('card_id')} | CI: {card.get('CI')} | Score: {p_score}")
            
            result.append({
                "card_id": card['card_id'],
                "title": card['key_module'],
                "p_score": p_score,
                "ci": card['CI'],
                "lrd": card['LRD'].isoformat() if hasattr(card['LRD'], 'isoformat') else str(card['LRD']),
                "lad": card['LAD'].isoformat() if hasattr(card['LAD'], 'isoformat') else str(card['LAD']),
                "is_core": card['is_core']
            })
        
        print(f"--- 🔍 SRS 调试结束 ---\n")
        
        return jsonify({
            "success": True,
            "date": date.today().isoformat(),
            "count": len(result),
            "cards": result
        }), 200
        
    except Exception as e:
        import traceback
        print(f"❌ 后端报错: {str(e)}")
        traceback.print_exc() # 打印完整的错误堆栈，精确定位哪一行崩了
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

# --- 场景 A: 专门复习接口 ---
@flashcard_bp.route('/<module_id>/srs/learn/<card_id>', methods=['POST'])
def learn_card(module_id, card_id):
    try:
        cards = get_all_cards_srs_state_supabase(module_id)
        card = next((c for c in cards if c['card_id'] == card_id), None)
        
        new_state = calculate_state_after_review(card)
        
        success = update_card_srs_state_supabase(
            module_id, card_id, 
            new_state['ci'], new_state['lrd'], new_state['lad'], 
            card['is_core'], new_state['referenceCount']
        )
        # 修改点：返回 new_state 以供测试断言
        return jsonify({
            "success": success, 
            "type": "review", 
            "new_state": {
                "ci": new_state['ci'],
                "lrd": new_state['lrd'].isoformat() if hasattr(new_state['lrd'], 'isoformat') else new_state['lrd'],
                "lad": new_state['lad'].isoformat() if hasattr(new_state['lad'], 'isoformat') else new_state['lad'],
                "rc": new_state['referenceCount']
            }
        }), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# --- 场景 B: 实战应用接口 ---
@flashcard_bp.route('/<module_id>/srs/use/<card_id>', methods=['POST'])
def use_card(module_id, card_id):
    try:
        cards = get_all_cards_srs_state_supabase(module_id)
        card = next((c for c in cards if c['card_id'] == card_id), None)
        
        new_state = calculate_state_after_application(card)
        
        success = update_card_srs_state_supabase(
            module_id, card_id, 
            new_state['ci'], new_state['lrd'], new_state['lad'], 
            card['is_core'], new_state['referenceCount']
        )
        # 修改点：返回 new_state 以供测试断言
        return jsonify({
            "success": success, 
            "type": "application", 
            "new_state": {
                "ci": new_state['ci'],
                "lrd": new_state['lrd'].isoformat() if hasattr(new_state['lrd'], 'isoformat') else new_state['lrd'],
                "lad": new_state['lad'].isoformat() if hasattr(new_state['lad'], 'isoformat') else new_state['lad'],
                "rc": new_state['referenceCount']
            }
        }), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

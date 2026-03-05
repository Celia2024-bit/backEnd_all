import json
import psycopg2
import psycopg2.extras
from flask import Flask, request, jsonify, Blueprint, current_app
from flask_cors import CORS
import os
import time
from .config import MODULE_TO_TABLE, DATABASE_URL
from datetime import date, timedelta
from .srs_calculator_supabase import (
    calculate_state_after_review,
    calculate_state_after_application,
    generate_must_use_list,
    calculate_priority_score_P
)

# --- 数据库连接 ---
def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


# ==========================================================
# SRS 算法后端函数
# ==========================================================

def get_all_cards_srs_state_supabase(module_id='mod1'):
    """从 Neon 读取所有卡片的 SRS 状态"""
    try:
        table_name = MODULE_TO_TABLE.get(module_id)
        if not table_name:
            raise ValueError(f"未知模块: {module_id}")

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT cardid, data, ci, lrd, lad, is_core, rc FROM "{table_name}"'
                )
                records = cur.fetchall()

        card_list = []
        for record in records:
            card_data = record.get('data') or {}
            if isinstance(card_data, str):
                card_data = json.loads(card_data)

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


def update_card_srs_state_supabase(module_id, card_id, ci, lrd, lad, is_core, rc=None):
    """将 SRS 算法计算后的新状态写回 Neon"""
    try:
        table_name = MODULE_TO_TABLE.get(module_id)
        lrd_str = lrd.isoformat() if hasattr(lrd, 'isoformat') else str(lrd)
        lad_str = lad.isoformat() if hasattr(lad, 'isoformat') else str(lad)

        with get_conn() as conn:
            with conn.cursor() as cur:
                if rc is not None:
                    cur.execute(
                        f'UPDATE "{table_name}" SET ci=%s, lrd=%s, lad=%s, is_core=%s, rc=%s WHERE cardid=%s',
                        (ci, lrd_str, lad_str, 1 if is_core else 0, rc, card_id)
                    )
                else:
                    cur.execute(
                        f'UPDATE "{table_name}" SET ci=%s, lrd=%s, lad=%s, is_core=%s WHERE cardid=%s',
                        (ci, lrd_str, lad_str, 1 if is_core else 0, card_id)
                    )
            conn.commit()

        print(f"💾 卡片 {card_id} SRS 状态已更新: CI={ci}, LRD={lrd_str}, LAD={lad_str}")
        return True

    except Exception as e:
        print(f"❌ 更新 SRS 状态时出错: {e}")
        return False


# --- Flask 应用初始化 ---
flashcard_bp = Blueprint('flashCard_english', __name__)


def initialize_data(module_id):
    """检查表是否有数据，若没有则从本地 JSON 导入"""
    try:
        table_name = MODULE_TO_TABLE[module_id]
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f'SELECT COUNT(*) FROM "{table_name}"')
                count = cur.fetchone()['count']

        if count > 0:
            return

    except Exception as e:
        print(f"❌ 初始数据检查失败（{module_id}）: {e}")
        return

    try:
        filename = f'{module_id}_cards.json'
        with open(filename, 'r', encoding='utf-8') as f:
            initial_data = json.load(f)

        with get_conn() as conn:
            with conn.cursor() as cur:
                for card in initial_data:
                    cur.execute(
                        f'INSERT INTO "{table_name}" (cardid, data) VALUES (%s, %s) ON CONFLICT (cardid) DO NOTHING',
                        (card.get('cardid'), json.dumps(card))
                    )
            conn.commit()

        print(f"📥 成功将 {module_id} 的 {len(initial_data)} 条初始数据导入 Neon")

    except FileNotFoundError:
        print(f"⚠️ 警告: 找不到初始数据文件 {filename}，跳过导入。")
    except Exception as e:
        print(f"❌ 初始数据导入失败（{module_id}）: {e}")


@flashcard_bp.before_app_request
def check_initial_data():
    if not hasattr(current_app, 'initial_data_checked'):
        print("--- 尝试连接 Neon 并检查初始数据 ---")
        initialize_data('mod1')
        initialize_data('mod2')
        current_app.initial_data_checked = True


# ==========================================================
# API 路由定义
# ==========================================================

# 1. GET: 获取所有卡片
@flashcard_bp.route('/<module_id>/cards', methods=['GET'])
def get_all_cards(module_id):
    try:
        table_name = MODULE_TO_TABLE.get(module_id)
        if not table_name:
            return jsonify({'error': f'未知模块: {module_id}'}), 400

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f'SELECT cardid, data FROM "{table_name}"')
                records = cur.fetchall()

        cards = []
        for r in records:
            data = r['data'] if isinstance(r['data'], dict) else json.loads(r['data'])
            cards.append({**data, 'cardid': r['cardid']})

        return jsonify(cards), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# 2. POST: 添加新卡片
@flashcard_bp.route('/<module_id>/cards', methods=['POST'])
def add_card(module_id):
    try:
        table_name = MODULE_TO_TABLE.get(module_id)
        new_card_data = request.json
        card_id = new_card_data.get('cardid')

        if not card_id:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(f'SELECT cardid FROM "{table_name}"')
                    existing = cur.fetchall()

            max_number = 0
            for card in existing:
                cid = card.get('cardid', '')
                if cid.startswith(f"{module_id}_card_"):
                    try:
                        number = int(cid.split('_')[-1])
                        max_number = max(max_number, number)
                    except ValueError:
                        pass
            card_id = f"{module_id}_card_{max_number + 1}"

        TODAY = date.today()
        initial_ci = 5
        initial_lrd = (TODAY - timedelta(days=5)).isoformat()
        initial_lad = (TODAY - timedelta(days=1)).isoformat()
        initial_is_core = 1

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'INSERT INTO "{table_name}" (cardid, data, ci, lrd, lad, is_core, rc) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *',
                    (card_id, json.dumps(new_card_data), initial_ci, initial_lrd, initial_lad, initial_is_core, 0)
                )
                result = cur.fetchone()
            conn.commit()

        data = result['data'] if isinstance(result['data'], dict) else json.loads(result['data'])
        new_card = {
            **data,
            'cardid': result['cardid'],
            'ci': result['ci'],
            'lrd': result['lrd'],
            'lad': result['lad'],
            'is_core': result['is_core'],
            'rc': result['rc']
        }

        print(f"✅ 新卡片 {card_id} 已添加")
        return jsonify({"success": True, "card": new_card}), 201

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# 3. PUT: 更新卡片
@flashcard_bp.route('/<module_id>/cards/<card_id>', methods=['PUT'])
def update_card(module_id, card_id):
    try:
        table_name = MODULE_TO_TABLE.get(module_id)
        updates = request.json
        updates.pop('cardid', None)

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'UPDATE "{table_name}" SET data=%s WHERE cardid=%s RETURNING cardid, data',
                    (json.dumps(updates), card_id)
                )
                result = cur.fetchone()
            conn.commit()

        if not result:
            return jsonify({'error': f'未找到卡片: {card_id}'}), 404

        data = result['data'] if isinstance(result['data'], dict) else json.loads(result['data'])
        updated_card = {**data, 'cardid': result['cardid']}
        return jsonify({"success": True, "card": updated_card}), 200

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# 4. DELETE: 删除卡片
@flashcard_bp.route('/<module_id>/cards/<card_id>', methods=['DELETE'])
def delete_card(module_id, card_id):
    try:
        table_name = MODULE_TO_TABLE.get(module_id)
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f'DELETE FROM "{table_name}" WHERE cardid=%s', (card_id,))
            conn.commit()
        return jsonify({"success": True}), 200

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# 5. POST: 重置为原始 JSON 数据
@flashcard_bp.route('/<module_id>/reset', methods=['POST'])
def reset_cards(module_id):
    try:
        table_name = MODULE_TO_TABLE.get(module_id)
        filename = f'{module_id}_cards.json'
        with open(filename, 'r', encoding='utf-8') as f:
            initial_data = json.load(f)

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f'DELETE FROM "{table_name}"')
                for card in initial_data:
                    cur.execute(
                        f'INSERT INTO "{table_name}" (cardid, data) VALUES (%s, %s) ON CONFLICT (cardid) DO NOTHING',
                        (card.get('cardid'), json.dumps(card))
                    )
            conn.commit()

        return jsonify({"success": True, "message": f"模块 {module_id} 已重置", "count": len(initial_data)})

    except Exception as e:
        return jsonify({"success": False, "error": f"重置失败: {e}"}), 500


# 6. POST: 导入卡片数据
@flashcard_bp.route('/<module_id>/import', methods=['POST'])
def import_cards(module_id):
    try:
        table_name = MODULE_TO_TABLE.get(module_id)
        data = request.json
        cards_to_import = data.get('cards')

        if not isinstance(cards_to_import, list):
            return jsonify({'error': '导入数据必须是 JSON 数组'}), 400

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f'DELETE FROM "{table_name}"')
                for card in cards_to_import:
                    cur.execute(
                        f'INSERT INTO "{table_name}" (cardid, data) VALUES (%s, %s) ON CONFLICT (cardid) DO NOTHING',
                        (card.get('cardid'), json.dumps(card))
                    )
            conn.commit()

        return jsonify({"success": True, "count": len(cards_to_import)})

    except Exception as e:
        return jsonify({"success": False, "error": f"导入失败: {e}"}), 500


# 7. GET: 获取今日必学卡片
@flashcard_bp.route('/<module_id>/srs/today', methods=['GET'])
def get_today_cards(module_id):
    try:
        cards = get_all_cards_srs_state_supabase(module_id)

        print(f"\n--- 🔍 SRS 调试开始 ({module_id}) ---")
        print(f"1. 数据库总卡片数: {len(cards) if cards else 0}")

        if not cards:
            return jsonify({"success": False, "error": "没有找到卡片数据"}), 404

        today_cards = generate_must_use_list(cards)
        print(f"2. 经过算法过滤后的今日必学数: {len(today_cards)}")

        result = []
        for card in today_cards:
            p_score = calculate_priority_score_P(card)
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
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# 8. POST: 专门复习接口
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


# 9. POST: 实战应用接口
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
import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from supabase import create_client, Client
import math
import random
import time

# --- 1. 初期設定 ---
st.set_page_config(layout="wide", page_title="WT Rank Battle")
url = st.secrets["SUPABASE_URL"]
key = st.secrets["SUPABASE_KEY"]
supabase = create_client(url, key)

GRID_SIZE = 15
MAX_TURNS = 10

# --- 2. データロード & セッション管理 ---
df = pd.read_csv("units.csv")

def get_db_session():
    return supabase.table("game_session").select("*").eq("id", 1).single().execute().data

def get_db_units():
    return supabase.table("unit_states").select("*").execute().data

# --- 3. 描画エンジン (名前表示付き) ---
def draw_enhanced_map(grid, units, my_team):
    fig, ax = plt.subplots(figsize=(10, 10))
    cmap = ListedColormap(['#8B4513', '#D3D3D3', '#A9A9A9', '#808080', '#696969', '#2F4F4F', '#00FF7F', '#FF4500'])
    
    display_map = grid.copy().astype(float)
    for u in units:
        if u['is_active']:
            color = 6 if u['team'] == my_team else 7
            display_map[u['pos_x'], u['pos_y']] = color
            # 名前を表示
            ax.text(u['pos_y'], u['pos_x'] - 0.5, u['unit_name'], 
                    color='yellow', fontsize=10, fontweight='bold', ha='center',
                    bbox=dict(facecolor='black', alpha=0.5, edgecolor='none'))

    ax.imshow(display_map, cmap=cmap, vmin=0, vmax=7, interpolation='nearest')
    # 高低差表示
    for i in range(GRID_SIZE):
        for j in range(GRID_SIZE):
            if grid[i, j] > 0:
                ax.text(j, i, str(int(grid[i, j])), ha='center', va='center', color='white', alpha=0.5)
    return fig

# --- 4. CPU AI ロジック ---
def run_cpu_logic(enemy_team, player_team, live_units):
    st.write(f"🤖 {enemy_team} (CPU) が思考中...")
    for u in live_units:
        if u['team'] == enemy_team and u['is_active']:
            # 最も近いプレイヤーの駒を探す
            targets = [p for p in live_units if p['team'] == player_team and p['is_active']]
            if targets:
                target = min(targets, key=lambda p: abs(p['pos_x']-u['pos_x']) + abs(p['pos_y']-u['pos_y']))
                # ターゲットに近づく
                new_x = u['pos_x'] + (1 if target['pos_x'] > u['pos_x'] else -1 if target['pos_x'] < u['pos_x'] else 0)
                new_y = u['pos_y'] + (1 if target['pos_y'] > u['pos_y'] else -1 if target['pos_y'] < u['pos_y'] else 0)
                
                # DB更新 (AIの移動)
                supabase.table("unit_states").update({
                    "pos_x": new_x, "pos_y": new_y, 
                    "submitted_move": {"action": "通常射撃", "trigger": "メイン1"}
                }).eq("unit_name", u['unit_name']).execute()

# --- 5. メイン UI ---
st.title("World Trigger: Online Rank Battle Simulator")

# サイドバー: 設定
with st.sidebar:
    st.header("🎮 試合設定")
    my_team = st.selectbox("自分の部隊", df['team'].unique(), index=1) # デフォルト玉狛
    op_type = st.radio("対戦相手", ["友人（オンライン）", "コンピューター（CPU）"])
    enemy_team = st.selectbox("敵の部隊", [t for t in df['team'].unique() if t != my_team])
    
    if st.button("試合開始（駒を配置）"):
        supabase.table("unit_states").delete().neq("id", 0).execute()
        selected_names = df[df['team'].isin([my_team, enemy_team])]['name'].tolist()
        insert_data = []
        for name in selected_names:
            row = df[df['name'] == name].iloc[0]
            insert_data.append({
                "unit_name": name, "team": row['team'], "hp": 100,
                "pos_x": random.randint(0, 14), "pos_y": random.randint(0, 14), "pos_z": 0,
                "is_active": True
            })
        supabase.table("unit_states").insert(insert_data).execute()
        supabase.table("game_session").update({"current_turn": 1, "phase": "input"}).eq("id", 1).execute()
        st.rerun()

# データ取得
live_session = get_db_session()
live_units = get_db_units()
current_units = [u for u in live_units if u['team'] in [my_team, enemy_team]]

col_map, col_cmd = st.columns([3, 2])

with col_map:
    st.subheader(f"Turn {live_session['current_turn']} / {MAX_TURNS}")
    if 'grid' not in st.session_state:
        st.session_state.grid = np.random.randint(0, 3, (GRID_SIZE, GRID_SIZE))
    st.pyplot(draw_enhanced_map(st.session_state.grid, current_units, my_team))

with col_cmd:
    st.subheader("行動プロット")
    my_active_units = [u for u in current_units if u['team'] == my_team and u['is_active']]
    
    for u in my_active_units:
        m_data = df[df['name'] == u['unit_name']].iloc[0]
        with st.expander(f"👤 {u['unit_name']} (HP: {int(u['hp'])})"):
            # 座標入力
            c1, c2 = st.columns(2)
            nx = c1.number_input("次X", 0, 14, u['pos_x'], key=f"x_{u['unit_name']}")
            ny = c2.number_input("次Y", 0, 14, u['pos_y'], key=f"y_{u['unit_name']}")
            
            # トリガー選択
            trig_options = [m_data[f'main{i}'] for i in range(1, 5) if m_data[f'main{i}'] != '-'] + \
                           [m_data[f'sub{i}'] for i in range(1, 5) if m_data[f'sub{i}'] != '-']
            selected_trig = st.selectbox("使用トリガー", trig_options, key=f"t_{u['unit_name']}")
            
            if st.button("行動確定", key=f"b_{u['unit_name']}"):
                supabase.table("unit_states").update({
                    "submitted_move": {"x": nx, "y": ny, "trigger": selected_trig},
                    "pos_x": nx, "pos_y": ny # タップ移動代わり
                }).eq("unit_name", u['unit_name']).execute()
                st.rerun()

    st.markdown("---")
    # 解決ボタン
    ready_count = sum(1 for u in current_units if u['submitted_move'] is not None and u['team'] == my_team)
    st.write(f"チェック完了: {ready_count} / {len(my_active_units)}")
    
    if st.button("🚨 ターンを解決する"):
        if op_type == "コンピューター（CPU）":
            run_cpu_logic(enemy_team, my_team, current_units)
        
        # ここで resolve_battle_logic() (前回提供したダメージ計算) を呼び出す
        st.success("戦闘解決中... ページをリロードしてください。")
        time.sleep(1)
        st.rerun()

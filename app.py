import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from supabase import create_client, Client
import math
import random

# --- 1. 初期設定 & 定数 ---
GRID_SIZE = 15
MAX_HEIGHT = 5
MAX_TURNS = 10

# Supabase接続
url = st.secrets["SUPABASE_URL"]
key = st.secrets["SUPABASE_KEY"]
supabase = create_client(url, key)

# --- 2. 数理モデル (Trion補正) ---
def get_unit_hp(trn, dfn):
    return trn * 2.5 + dfn * 1.5

def get_attack_power(u_master, trigger):
    # 近接はトリオン不問、射撃・狙撃はトリオン比例
    base = u_master['atk'] + 10
    if u_master['pos'] == 'Attacker':
        return base
    if trigger == 'アイビス':
        return 25 * (u_master['trn'] / 0.9) # 千佳の42倍火力を再現
    return base * (1 + u_master['trn'] / 15)

# --- 3. 描画エンジン ---
def draw_live_map(grid, units, my_team):
    fig, ax = plt.subplots(figsize=(8, 8))
    # 0:地面(茶), 1-5:ビル(灰), 6:自分(緑), 7:敵(赤)
    cmap = ListedColormap(['#8B4513', '#D3D3D3', '#A9A9A9', '#808080', '#696969', '#2F4F4F', '#00FF7F', '#FF4500'])
    
    display_map = grid.copy().astype(float)
    for u in units:
        if u['is_active']:
            display_map[u['pos_x'], u['pos_y']] = 6 if u['team'] == my_team else 7

    ax.imshow(display_map, cmap=cmap, vmin=0, vmax=7, interpolation='nearest')
    
    # 高低差の数値を表示
    for i in range(GRID_SIZE):
        for j in range(GRID_SIZE):
            if grid[i, j] > 0:
                ax.text(j, i, str(int(grid[i, j])), ha='center', va='center', color='white', fontsize=9, fontweight='bold')
    return fig

def draw_radar(units, my_team):
    fig, ax = plt.subplots(figsize=(4, 4), facecolor='black')
    ax.set_facecolor('black')
    for u in units:
        if u['is_active']:
            color = '#00FF7F' if u['team'] == my_team else '#FF0000'
            ax.scatter(u['pos_y'], u['pos_x'], c=color, s=40, edgecolors='white')
    ax.set_xlim(-0.5, 14.5); ax.set_ylim(14.5, -0.5)
    ax.grid(color='#003300', linewidth=0.5)
    ax.set_title("RADAR - TRION SIGNAL", color='#00FF7F', fontsize=10)
    return fig

# --- 4. 戦闘解決 (LoS / Escudo / Points) ---
def resolve_battle_logic():
    st.info("戦況を解決中...")
    units = supabase.table("unit_states").select("*").execute().data
    df_master = pd.read_csv("units.csv")
    session = supabase.table("game_session").select("*").eq("id", 1).single().execute().data
    
    logs = []
    
    # 全員の「エスクード」を先に処理（壁を生成）
    for u in units:
        if u['is_active'] and u['submitted_move'] and u['submitted_move'].get('action') == "エスクード":
            st.session_state.grid[u['pos_x'], u['pos_y']] = min(5, st.session_state.grid[u['pos_x'], u['pos_y']] + 2)
            logs.append(f"🛡️ {u['unit_name']} がエスクードを展開！(地点:{u['pos_x']},{u['pos_y']})")

    # 攻撃解決
    for u in units:
        if not u['is_active']: continue
        m = df_master[df_master['name'] == u['unit_name']].iloc[0]
        enemies = [e for e in units if e['team'] != u['team'] and e['is_active']]
        
        target = None
        min_dist = 999
        for e in enemies:
            dist = math.sqrt((u['pos_x']-e['pos_x'])**2 + (u['pos_y']-e['pos_y'])**2 + (u['pos_z']-e['pos_z'])**2)
            if dist <= m['rng']:
                # 射線判定 (バイパーは遮蔽無視)
                if m['main1'] == 'バイパー' or is_los_clear(u, e, st.session_state.grid):
                    if dist < min_dist:
                        min_dist = dist; target = e
        
        if target:
            atk = get_attack_power(m, m['main1'])
            dfn = df_master[df_master['name'] == target['unit_name']].iloc[0]['dfn'] + 4
            damage = max(1, int(atk - dfn))
            target['hp'] -= damage
            logs.append(f"💥 {u['unit_name']} -> {target['unit_name']} : {damage}dmg")
            if target['hp'] <= 0:
                target['is_active'] = False
                logs.append(f"💀 {target['unit_name']} ベイルアウト！ (+1 Point for {u['team']})")

    # DB更新
    for u in units:
        supabase.table("unit_states").update({
            "hp": u['hp'], "is_active": u['is_active'], "pos_x": u['pos_x'], "pos_y": u['pos_y'], "submitted_move": None
        }).eq("unit_name", u['unit_name']).execute()
    
    supabase.table("game_session").update({"current_turn": session['current_turn'] + 1}).eq("id", 1).execute()
    return logs

def is_los_clear(u, e, grid):
    # 簡易的なLoS判定（直線の高さをチェック）
    steps = max(abs(u['pos_x']-e['pos_x']), abs(u['pos_y']-e['pos_y']))
    for i in range(1, steps):
        tx = int(u['pos_x'] + (e['pos_x'] - u['pos_x']) * i / steps)
        ty = int(u['pos_y'] + (e['pos_y'] - u['pos_y']) * i / steps)
        if grid[tx, ty] > max(u['pos_z'], e['pos_z']): return False
    return True

# --- 5. メインUI ---
st.set_page_config(layout="wide", page_title="WT Rank Battle")
st.title("World Trigger: B-Rank Battle Simulator")

df = pd.read_csv("units.csv")
if 'grid' not in st.session_state:
    st.session_state.grid = np.random.randint(0, 3, (GRID_SIZE, GRID_SIZE))

session = supabase.table("game_session").select("*").eq("id", 1).single().execute().data
live_units = supabase.table("unit_states").select("*").execute().data

# サイドバー: 統計とレーダー
with st.sidebar:
    st.header(f"Turn: {session['current_turn']} / {MAX_TURNS}")
    my_team = st.selectbox("操作部隊を選択", df['team'].unique())
    st.pyplot(draw_radar(live_units, my_team))
    
    st.markdown("---")
    if st.button("初期化 (全隊員転送)"):
        # 初期化ロジック (省略: 前回のコードと同様)
        pass

# メイン画面
col_map, col_cmd = st.columns([3, 2])

with col_map:
    st.pyplot(draw_live_map(st.session_state.grid, live_units, my_team))

with col_cmd:
    st.subheader(f"【{my_team}】コマンド入力")
    my_units = [u for u in live_units if u['team'] == my_team and u['is_active']]
    
    for u in my_units:
        with st.expander(f"{u['unit_name']} (HP: {int(u['hp'])})"):
            c_x = st.number_input("移動X", 0, 14, u['pos_x'], key=f"x_{u['unit_name']}")
            c_y = st.number_input("移動Y", 0, 14, u['pos_y'], key=f"y_{u['unit_name']}")
            action = st.selectbox("アクション", ["通常射撃", "エスクード"], key=f"a_{u['unit_name']}")
            if st.button("行動を保存", key=f"b_{u['unit_name']}"):
                supabase.table("unit_states").update({"submitted_move": {"x":c_x, "y":c_y, "action":action}, "pos_x":c_x, "pos_y":c_y}).eq("unit_name", u['unit_name']).execute()
                st.rerun()

    st.markdown("---")
    if st.button("🚨 ターン解決 (全員の行動を実行)"):
        logs = resolve_battle_logic()
        for l in logs: st.write(l)
        st.rerun()

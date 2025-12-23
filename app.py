import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import japanize_matplotlib
from matplotlib.colors import ListedColormap
from supabase import create_client, Client
import random, math, time

# --- 1. 初期設定 ---
st.set_page_config(layout="wide", page_title="WT Rank Battle: AP & Z-Axis")
supabase: Client = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

GRID_SIZE = 15
df_master = pd.read_csv("units.csv")

# --- 2. 描画エンジン (APとZの可視化) ---

def draw_tactical_map(grid, units, my_team):
    fig, ax = plt.subplots(figsize=(10, 10))
    # 0:地面, 1-5:ビル, 6:味方, 7:敵
    cmap = ListedColormap(['#8B4513', '#D3D3D3', '#BDBDBD', '#9E9E9E', '#757575', '#424242', '#00FF7F', '#FF4500'])
    
    display_map = grid.copy().astype(float)
    my_units = [u for u in units if u['team'] == my_team and u.get('is_active')]

    for u in units:
        if not u.get('is_active'): continue
        
        # 視界判定
        is_visible = u['team'] == my_team
        if not is_visible:
            for my_u in my_units:
                if math.sqrt((u['pos_x']-my_u['pos_x'])**2 + (u['pos_y']-my_u['pos_y'])**2) <= 5:
                    is_visible = True; break

        if is_visible:
            val = 6 if u['team'] == my_team else 7
            display_map[u['pos_x'], u['pos_y']] = val
            
            # ラベル：名前 + Z高度 + AP残量
            ap_now = u.get('ap', 0)
            z_now = int(u.get('pos_z', 0))
            label = f"{u['unit_name']}\nZ:{z_now} | AP:{ap_now}"
            
            label_bg = '#00FF7F' if u['team'] == my_team else '#FF4500'
            ax.text(u['pos_y'], u['pos_x'] - 0.7, label, color='white', fontsize=9, 
                    fontweight='bold', ha='center', va='bottom',
                    bbox=dict(facecolor=label_bg, alpha=0.9, boxstyle='round,pad=0.3'))

    ax.imshow(display_map, cmap=cmap, vmin=0, vmax=7, interpolation='nearest')
    for i in range(GRID_SIZE):
        for j in range(GRID_SIZE):
            if grid[i, j] > 0:
                ax.text(j, i, str(int(grid[i, j])), ha='center', va='center', color='white', alpha=0.3, fontweight='bold')
    return fig

# --- 3. 戦闘解決エンジン (AP消費ロジック) ---

def calculate_ap_cost(u, nx, ny, nz, main_w):
    """APコスト計算: 移動(1/マス) + 高度変更(2/階) + 攻撃(3～)"""
    move_dist = abs(u['pos_x'] - nx) + abs(u['pos_y'] - ny)
    climb_dist = abs(u['pos_z'] - nz)
    attack_cost = 5 if main_w != '-' else 0 # 攻撃基本コスト
    return move_dist + (climb_dist * 2) + attack_cost

def resolve_turn(my_team, enemy_team, mode, grid):
    st.info("APを計算してターンを処理中...")
    units = supabase.table("unit_states").select("*").execute().data
    session = supabase.table("game_session").select("*").eq("id", 1).single().execute().data
    
    logs = []
    my_pts = session.get('my_points', 0); en_pts = session.get('enemy_points', 0)

    for u in units:
        if not u.get('is_active'): continue
        
        # 1. APの回復 (毎ターン Mobility + 10 回復)
        master = df_master[df_master['name'] == u['unit_name']].iloc[0]
        u['ap'] = min(u.get('max_ap', 20), u.get('ap', 0) + int(master['mob']) + 10)

        # 2. 移動と高度の確定
        move = u.get('submitted_move')
        if move:
            nx, ny, nz = move.get('x'), move.get('y'), move.get('z')
            main_w = u.get('selected_main', '-')
            
            cost = calculate_ap_cost(u, nx, ny, nz, main_w)
            
            if u['ap'] >= cost:
                u['ap'] -= cost
                u['pos_x'], u['pos_y'], u['pos_z'] = nx, ny, nz
                logs.append(f"🏃 {u['unit_name']} が移動 (AP-{cost})")
                
                # 攻撃処理 (3D距離計算)
                enemies = [e for e in units if e['team'] != u['team'] and e.get('is_active')]
                for e in enemies:
                    dist = math.sqrt((u['pos_x']-e['pos_x'])**2 + (u['pos_y']-e['pos_y'])**2 + (u['pos_z']-e.get('pos_z',0))**2)
                    if dist <= master['rng'] and main_w != '-':
                        # (ここで以前のダメージ計算ロジックを実行)
                        dmg = int((master['atk'] * 2) * random.uniform(0.8, 1.2))
                        e['hp'] -= dmg
                        logs.append(f"💥 {u['unit_name']} -> {e['unit_name']} ({dmg}ダメ)")
                        if e['hp'] <= 0:
                            e['is_active'] = False; my_pts += (1 if u['team']==my_team else 0); en_pts += (0 if u['team']==my_team else 1)
            else:
                logs.append(f"⚠️ {u['unit_name']} のAPが不足し、行動に失敗！")

    # 3. DB更新
    for u in units:
        supabase.table("unit_states").update({
            "hp": u['hp'], "pos_x": u['pos_x'], "pos_y": u['pos_y'], "pos_z": u['pos_z'],
            "ap": u['ap'], "is_active": u['is_active'], "submitted_move": None
        }).eq("unit_name", u['unit_name']).execute()
    
    supabase.table("game_session").update({"current_turn": session['current_turn']+1, "my_points":my_pts, "enemy_points":en_pts}).eq("id", 1).execute()
    for l in logs: supabase.table("battle_logs").insert({"turn": session['current_turn'], "message": l}).execute()

# --- 4. メイン UI ---

st.title("🛰️ World Trigger: Z-Axis & Action Points")

session = supabase.table("game_session").select("*").eq("id", 1).single().execute().data
live_units = supabase.table("unit_states").select("*").execute().data

with st.sidebar:
    st.header(f"Turn {session['current_turn']} / 10")
    my_team = st.selectbox("自分の部隊", df_master['team'].unique(), index=1)
    enemy_team = st.selectbox("敵部隊", [t for t in df_master['team'].unique() if t != my_team])
    
    if st.button("リセット・試合開始"):
        supabase.table("unit_states").delete().neq("id", 0).execute()
        selected = df_master[df_master['team'].isin([my_team, enemy_team])]
        for _, row in selected.iterrows():
            supabase.table("unit_states").insert({
                "unit_name": row['name'], "team": row['team'], "hp": 100, "ap": 20, "max_ap": 20,
                "pos_x": random.randint(0, 14), "pos_y": random.randint(0, 14), "pos_z": 0, "is_active": True
            }).execute()
        supabase.table("game_session").update({"current_turn": 1, "my_points":0, "enemy_points":0}).eq("id", 1).execute()
        st.rerun()

col_map, col_cmd = st.columns([2, 1])

with col_map:
    if 'grid' not in st.session_state: st.session_state.grid = np.random.randint(0, 4, (15, 15))
    st.pyplot(draw_tactical_map(st.session_state.grid, live_units, my_team))

with col_cmd:
    st.subheader("🎮 指令プロット")
    my_active = [u for u in live_units if u['team'] == my_team and u.get('is_active')]
    for u in my_active:
        with st.expander(f"{u['unit_name']} (AP:{u.get('ap')})"):
            m = df_master[df_master['name'] == u['unit_name']].iloc[0]
            
            c1, c2, c3 = st.columns(3)
            nx = c1.number_input("X", 0, 14, u['pos_x'], key=f"x{u['unit_name']}")
            ny = c2.number_input("Y", 0, 14, u['pos_y'], key=f"y{u['unit_name']}")
            # Z軸の入力を追加（そのマスのビルの高さが上限）
            max_z = int(st.session_state.grid[nx, ny])
            nz = c3.number_input("Z", 0, 5, min(u['pos_z'], max_z), key=f"z{u['unit_name']}")
            
            m_t = st.selectbox("メイン", [m[f'main{i}'] for i in range(1, 5) if m[f'main{i}'] != '-'], key=f"m{u['unit_name']}")
            
            # 予想コスト表示
            cost = calculate_ap_cost(u, nx, ny, nz, m_t)
            st.caption(f"消費予定AP: {cost} {'⚠️不足' if cost > u.get('ap',0) else '✅OK'}")
            
            if st.button("確定", key=f"b{u['unit_name']}"):
                supabase.table("unit_states").update({
                    "submitted_move": {"x": nx, "y": ny, "z": nz}, "selected_main": m_t
                }).eq("unit_name", u['unit_name']).execute()
                st.rerun()

    if st.button("🚨 ターンを解決する"):
        resolve_turn(my_team, enemy_team, "友人", st.session_state.grid)
        st.rerun()

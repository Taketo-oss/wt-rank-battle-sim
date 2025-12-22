import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from supabase import create_client, Client
import random, math, time

# --- A. 初期設定 ---
st.set_page_config(layout="wide", page_title="WT Rank Battle Pro")
supabase: Client = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

GRID_SIZE = 15
df_master = pd.read_csv("units.csv")

# --- B. 描画エンジン（名前表示・高低差・レーダー） ---

def draw_tactical_map(grid, units, my_team):
    fig, ax = plt.subplots(figsize=(10, 10))
    # 0:地, 1-5:ビル, 6:味方(ミント), 7:敵(赤)
    cmap = ListedColormap(['#8B4513', '#D3D3D3', '#A9A9A9', '#808080', '#696969', '#2F4F4F', '#00FF7F', '#FF4500'])
    
    display_map = grid.copy().astype(float)
    for u in units:
        if u.get('is_active', False):
            val = 6 if u['team'] == my_team else 7
            display_map[u['pos_x'], u['pos_y']] = val
            # 【重要】駒の横に名前を常に表示
            label_bg = '#00FF7F' if u['team'] == my_team else '#FF4500'
            ax.text(u['pos_y'], u['pos_x'] - 0.6, u['unit_name'], color='white', fontsize=9, 
                    fontweight='bold', ha='center', bbox=dict(facecolor=label_bg, alpha=0.8, boxstyle='round'))

    ax.imshow(display_map, cmap=cmap, vmin=0, vmax=7, interpolation='nearest')
    # ビルの高さを数値で表示
    for i in range(GRID_SIZE):
        for j in range(GRID_SIZE):
            if grid[i, j] > 0:
                ax.text(j, i, str(int(grid[i, j])), ha='center', va='center', color='black', alpha=0.3, fontsize=8)
    return fig

def draw_radar(units, my_team):
    fig, ax = plt.subplots(figsize=(4, 4), facecolor='black')
    ax.set_facecolor('black')
    for u in units:
        if u.get('is_active', False):
            color = '#00FF7F' if u['team'] == my_team else '#FF0000'
            ax.scatter(u['pos_y'], u['pos_x'], c=color, s=80, edgecolors='white', alpha=0.8)
    ax.set_xlim(-0.5, 14.5); ax.set_ylim(14.5, -0.5); ax.axis('off')
    return fig

# --- C. 戦闘解決エンジン（提示されたロジックを統合） ---

def is_los_clear(u, e, grid):
    steps = max(abs(u['pos_x']-e['pos_x']), abs(u['pos_y']-e['pos_y']))
    if steps == 0: return True
    for i in range(1, steps):
        tx = int(u['pos_x'] + (e['pos_x'] - u['pos_x']) * i / steps)
        ty = int(u['pos_y'] + (e['pos_y'] - u['pos_y']) * i / steps)
        if grid[tx, ty] > max(u.get('pos_z', 0), e.get('pos_z', 0)):
            return False
    return True

def resolve_turn(my_team, enemy_team, mode, grid):
    st.info("戦闘解決中...")
    units = supabase.table("unit_states").select("*").execute().data
    session = supabase.table("game_session").select("*").eq("id", 1).single().execute().data
    
    logs = []
    my_pts = session.get('my_points', 0)
    en_pts = session.get('enemy_points', 0)

    # 1. エスクードの先行処理
    for u in units:
        if u.get('is_active') and u.get('selected_main') == "エスクード":
            tx, ty = u['pos_x'], u['pos_y']
            grid[tx, ty] = min(5, grid[tx, ty] + 2)
            logs.append(f"🛡️ {u['unit_name']} がエスクードを展開！壁が出現。")

    # 2. 移動の反映 & CPU行動
    for u in units:
        if not u.get('is_active'): continue
        # プレイヤーの移動予約を反映
        if u.get('team') == my_team or mode == "友人（オンライン）":
            move = u.get('submitted_move')
            if move:
                u['pos_x'], u['pos_y'] = move.get('x', u['pos_x']), move.get('y', u['pos_y'])
        
        # CPU行動
        elif mode == "コンピューター（CPU）" and u.get('team') == enemy_team:
            targets = [t for t in units if t['team'] == my_team and t['is_active']]
            if targets:
                target = random.choice(targets)
                u['pos_x'] += (1 if target['pos_x'] > u['pos_x'] else -1 if target['pos_x'] < u['pos_x'] else 0)
                u['pos_y'] += (1 if target['pos_y'] > u['pos_y'] else -1 if target['pos_y'] < u['pos_y'] else 0)

    # 3. 攻撃計算 (3D距離・LoS・千佳補正)
    for u in [u for u in units if u.get('is_active')]:
        master = df_master[df_master['name'] == u['unit_name']].iloc[0]
        enemies = [e for e in units if e['team'] != u['team'] and e.get('is_active')]
        main_wep = u.get('selected_main', '-')
        
        for e in enemies:
            dist = math.sqrt((u['pos_x']-e['pos_x'])**2 + (u['pos_y']-e['pos_y'])**2 + (u.get('pos_z',0)-e.get('pos_z',0))**2)
            if dist <= master['rng']:
                if main_wep == 'バイパー' or is_los_clear(u, e, grid):
                    atk = (master['atk']+10) * (1 + master['trn']/15)
                    if main_wep == 'アイビス' and u['unit_name'] == '雨取 千佳':
                        atk = 25 * (master['trn']/0.9)
                    
                    damage = max(5, int(atk - 10))
                    e['hp'] -= damage
                    logs.append(f"💥 {u['unit_name']} -> {e['unit_name']} ({damage}ダメ)")
                    if e['hp'] <= 0:
                        e['hp'] = 0; e['is_active'] = False
                        logs.append(f"💀 {e['unit_name']} ベイルアウト！")
                        if u['team'] == my_team: my_pts += 1
                        else: en_pts += 1

    # 4. DB一括更新
    for u in units:
        supabase.table("unit_states").update({
            "hp": u['hp'], "pos_x": u['pos_x'], "pos_y": u['pos_y'], "is_active": u['is_active'], "submitted_move": None
        }).eq("unit_name", u['unit_name']).execute()
    
    supabase.table("game_session").update({
        "current_turn": session['current_turn'] + 1, "my_points": my_pts, "enemy_points": en_pts
    }).eq("id", 1).execute()
    for l in logs:
        supabase.table("battle_logs").insert({"turn": session['current_turn'], "message": l}).execute()

# --- D. メイン UI ---

st.title("🛰️ World Trigger Online Pro")

# DBから最新情報取得
session = supabase.table("game_session").select("*").eq("id", 1).single().execute().data
live_units = supabase.table("unit_states").select("*").execute().data

with st.sidebar:
    st.header(f"Turn {session['current_turn']} / 10")
    st.metric("味方ポイント", session.get('my_points', 0))
    st.metric("敵ポイント", session.get('enemy_points', 0))
    
    my_team = st.selectbox("操作部隊", df_master['team'].unique(), index=1)
    enemy_team = st.selectbox("敵部隊", [t for t in df_master['team'].unique() if t != my_team])
    mode = st.radio("対戦形式", ["友人（オンライン）", "コンピューター（CPU）"])
    
    st.pyplot(draw_radar(live_units, my_team))
    
    if st.button("リセット・試合開始"):
        supabase.table("unit_states").delete().neq("id", 0).execute()
        supabase.table("battle_logs").delete().neq("id", 0).execute()
        selected = df_master[df_master['team'].isin([my_team, enemy_team])]
        for _, row in selected.iterrows():
            supabase.table("unit_states").insert({
                "unit_name": row['name'], "team": row['team'], "hp": 100,
                "pos_x": random.randint(0, 14), "pos_y": random.randint(0, 14), "is_active": True
            }).execute()
        supabase.table("game_session").update({"current_turn": 1, "my_points":0, "enemy_points":0}).eq("id", 1).execute()
        st.rerun()

col_map, col_cmd = st.columns([2, 1])

with col_map:
    if 'grid' not in st.session_state: st.session_state.grid = np.random.randint(0, 4, (GRID_SIZE, GRID_SIZE))
    st.pyplot(draw_tactical_map(st.session_state.grid, live_units, my_team))
    # ログ表示
    logs = supabase.table("battle_logs").select("*").order("id", desc=True).limit(5).execute().data
    for l in logs: st.caption(f"Turn {l['turn']}: {l['message']}")

with col_cmd:
    st.subheader("🎮 コマンド入力")
    my_active = [u for u in live_units if u['team'] == my_team and u.get('is_active')]
    for u in my_active:
        with st.expander(f"{u['unit_name']} (HP:{int(u['hp'])})"):
            m = df_master[df_master['name'] == u['unit_name']].iloc[0]
            nx = st.number_input("移動先X", 0, 14, u['pos_x'], key=f"x{u['unit_name']}")
            ny = st.number_input("移動先Y", 0, 14, u['pos_y'], key=f"y{u['unit_name']}")
            
            main_t = st.selectbox("メイン", [m[f'main{i}'] for i in range(1, 5) if m[f'main{i}'] != '-'], key=f"m{u['unit_name']}")
            sub_t = st.selectbox("サブ", [m[f'sub{i}'] for i in range(1, 5) if m[f'sub{i}'] != '-'], key=f"s{u['unit_name']}")
            
            if st.button("保存", key=f"b{u['unit_name']}"):
                supabase.table("unit_states").update({
                    "submitted_move": {"x": nx, "y": ny}, "selected_main": main_t, "selected_sub": sub_t
                }).eq("unit_name", u['unit_name']).execute()
                st.success("保存完了！")

    if st.button("🚨 全隊員の行動を解決（ターン進行）"):
        resolve_turn(my_team, enemy_team, mode, st.session_state.grid)
        st.rerun()

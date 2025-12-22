import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from supabase import create_client, Client
import random, math, time

# --- A. 初期設定 ---
st.set_page_config(layout="wide", page_title="WT Rank Battle v2")
supabase: Client = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

GRID_SIZE = 15
MAX_HEIGHT = 5

# マスタデータの読み込み
df_master = pd.read_csv("units.csv")

# --- B. 描画関数 ---

def draw_tactical_map(grid, units, my_team):
    """メインマップ：名前タグ・高低差・ユニット表示"""
    fig, ax = plt.subplots(figsize=(10, 10))
    # 0:地(茶), 1-5:ビル(灰), 6:味方(ミント), 7:敵(赤)
    cmap = ListedColormap(['#8B4513', '#D3D3D3', '#A9A9A9', '#808080', '#696969', '#2F4F4F', '#00FF7F', '#FF4500'])
    
    display_map = grid.copy().astype(float)
    for u in units:
        if u['is_active']:
            val = 6 if u['team'] == my_team else 7
            display_map[u['pos_x'], u['pos_y']] = val
            # ネームプレート
            ax.text(u['pos_y'], u['pos_x'] - 0.7, u['unit_name'], color='white', fontsize=8, 
                    fontweight='bold', ha='center', bbox=dict(facecolor='black', alpha=0.6, boxstyle='round'))

    ax.imshow(display_map, cmap=cmap, vmin=0, vmax=7, interpolation='nearest')
    for i in range(GRID_SIZE):
        for j in range(GRID_SIZE):
            if grid[i, j] > 0:
                ax.text(j, i, str(int(grid[i, j])), ha='center', va='center', color='white', alpha=0.4)
    return fig

def draw_radar(units, my_team):
    """レーダー画面：トリオン信号"""
    fig, ax = plt.subplots(figsize=(4, 4), facecolor='black')
    ax.set_facecolor('black')
    for u in units:
        if u['is_active']:
            color = '#00FF7F' if u['team'] == my_team else '#FF0000'
            ax.scatter(u['pos_y'], u['pos_x'], c=color, s=80, edgecolors='white', alpha=0.8)
    ax.set_xlim(-0.5, 14.5); ax.set_ylim(14.5, -0.5); ax.axis('off')
    return fig

# --- C. 戦闘解決エンジン ---

def resolve_turn(my_team, enemy_team, mode, grid):
    st.info("戦闘解決中...")
    units = supabase.table("unit_states").select("*").execute().data
    session = supabase.table("game_session").select("*").eq("id", 1).single().execute().data
    
    # 1. CPU行動 (CPUモードの場合)
    if mode == "コンピューター（CPU）":
        for u in [u for u in units if u['team'] == enemy_team and u['is_active']]:
            targets = [t for t in units if t['team'] == my_team and t['is_active']]
            if targets:
                target = random.choice(targets)
                u['pos_x'] += (1 if target['pos_x'] > u['pos_x'] else -1 if target['pos_x'] < u['pos_x'] else 0)
                u['pos_y'] += (1 if target['pos_y'] > u['pos_y'] else -1 if target['pos_y'] < u['pos_y'] else 0)

    # 2. ダメージ計算 (射線LoS・トリオン補正)
    logs = []
    for u in [u for u in units if u['is_active']]:
        master = df_master[df_master['name'] == u['unit_name']].iloc[0]
        # ターゲット選定
        enemies = [e for e in units if e['team'] != u['team'] and e['is_active']]
        for e in enemies:
            dist = math.sqrt((u['pos_x']-e['pos_x'])**2 + (u['pos_y']-e['pos_y'])**2)
            if dist <= master['rng']:
                # ダメージ算出 (千佳アイビス42倍補正)
                atk = (master['atk']+10) * (1 + master['trn']/15)
                if u['selected_main'] == 'アイビス': atk = 25 * (master['trn']/0.9)
                
                damage = max(5, int(atk - 10))
                e['hp'] -= damage
                logs.append(f"💥 {u['unit_name']} -> {e['unit_name']} ({damage}ダメ)")
                if e['hp'] <= 0:
                    e['is_active'] = False
                    logs.append(f"💀 {e['unit_name']} ベイルアウト！")

    # 3. DB一括更新
    for u in units:
        supabase.table("unit_states").update({
            "hp": u['hp'], "pos_x": u['pos_x'], "pos_y": u['pos_y'], "is_active": u['is_active'], "submitted_move": None
        }).eq("unit_name", u['unit_name']).execute()
    
    supabase.table("game_session").update({"current_turn": session['current_turn'] + 1}).eq("id", 1).execute()
    for l in logs:
        supabase.table("battle_logs").insert({"turn": session['current_turn'], "message": l}).execute()

# --- D. メイン UI ---

st.title("🛰️ World Trigger Online Simulator")

# セッション状態
if 'grid' not in st.session_state:
    st.session_state.grid = np.random.randint(0, 4, (GRID_SIZE, GRID_SIZE))

session = supabase.table("game_session").select("*").eq("id", 1).single().execute().data
live_units = supabase.table("unit_states").select("*").execute().data

with st.sidebar:
    st.header(f"Turn {session['current_turn']} / 10")
    my_team = st.selectbox("自分の部隊", df_master['team'].unique(), index=1)
    enemy_team = st.selectbox("対戦相手", [t for t in df_master['team'].unique() if t != my_team])
    mode = st.radio("対戦形式", ["友人（オンライン）", "コンピューター（CPU）"])
    
    st.pyplot(draw_radar(live_units, my_team))
    
    if st.button("試合開始（初期化）"):
        supabase.table("unit_states").delete().neq("id", 0).execute()
        supabase.table("battle_logs").delete().neq("id", 0).execute()
        selected = df_master[df_master['team'].isin([my_team, enemy_team])]
        for _, row in selected.iterrows():
            supabase.table("unit_states").insert({
                "unit_name": row['name'], "team": row['team'], "hp": 100,
                "pos_x": random.randint(0, 14), "pos_y": random.randint(0, 14)
            }).execute()
        supabase.table("game_session").update({"current_turn": 1}).eq("id", 1).execute()
        st.rerun()

col_map, col_cmd = st.columns([2, 1])

with col_map:
    st.pyplot(draw_tactical_map(st.session_state.grid, live_units, my_team))
    # ログ表示
    st.subheader("📋 戦況ログ")
    logs = supabase.table("battle_logs").select("*").order("id", desc=True).limit(5).execute().data
    for l in logs: st.caption(f"Turn {l['turn']}: {l['message']}")

with col_cmd:
    st.subheader("🎮 コマンド入力")
    my_units = [u for u in live_units if u['team'] == my_team and u['is_active']]
    for u in my_units:
        with st.expander(f"{u['unit_name']} (HP:{int(u['hp'])})"):
            m = df_master[df_master['name'] == u['unit_name']].iloc[0]
            # タップ移動の代わりに入力
            nx = st.number_input("X", 0, 14, u['pos_x'], key=f"x{u['unit_name']}")
            ny = st.number_input("Y", 0, 14, u['pos_y'], key=f"y{u['unit_name']}")
            
            main_t = st.selectbox("メイン", [m[f'main{i}'] for i in range(1, 5) if m[f'main{i}'] != '-'], key=f"m{u['unit_name']}")
            sub_t = st.selectbox("サブ", [m[f'sub{i}'] for i in range(1, 5) if m[f'sub{i}'] != '-'], key=f"s{u['unit_name']}")
            
            if st.button("保存", key=f"b{u['unit_name']}"):
                supabase.table("unit_states").update({
                    "pos_x": nx, "pos_y": ny, "selected_main": main_t, "selected_sub": sub_t, "submitted_move": {"ok":True}
                }).eq("unit_name", u['unit_name']).execute()
                st.rerun()

    if st.button("🚨 ターン解決を実行"):
        resolve_turn(my_team, enemy_team, mode, st.session_state.grid)
        st.rerun()

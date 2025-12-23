import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import japanize_matplotlib
from matplotlib.colors import ListedColormap
from supabase import create_client, Client
import random, math, time

# --- A. 初期設定 ---
st.set_page_config(layout="wide", page_title="WT Rank Battle Ultimate v4")
supabase: Client = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

GRID_SIZE = 15
df_master = pd.read_csv("units.csv")

# --- B. 描画エンジン（変更なし） ---
def draw_tactical_map(grid, units, my_team):
    fig, ax = plt.subplots(figsize=(10, 10))
    cmap = ListedColormap(['#8B4513', '#D3D3D3', '#A9A9A9', '#808080', '#696969', '#2F4F4F', '#00FF7F', '#FF4500'])
    display_map = grid.copy().astype(float)
    my_active_units = [u for u in units if u['team'] == my_team and u.get('is_active')]
    for u in units:
        if not u.get('is_active'): continue
        is_visible = False
        if u['team'] == my_team: is_visible = True
        else:
            for my_u in my_active_units:
                dist = math.sqrt((u['pos_x']-my_u['pos_x'])**2 + (u['pos_y']-my_u['pos_y'])**2)
                if dist <= 5: is_visible = True; break
        if is_visible:
            val = 6 if u['team'] == my_team else 7
            display_map[u['pos_x'], u['pos_y']] = val
            label_bg = '#00FF7F' if u['team'] == my_team else '#FF4500'
            ax.text(u['pos_y'], u['pos_x'] - 0.7, u['unit_name'], color='white', fontsize=10, 
                    fontweight='bold', ha='center', bbox=dict(facecolor=label_bg, alpha=0.9, boxstyle='round'))
    ax.imshow(display_map, cmap=cmap, vmin=0, vmax=7, interpolation='nearest')
    return fig

def draw_radar(units, my_team):
    fig, ax = plt.subplots(figsize=(4, 4), facecolor='black')
    ax.set_facecolor('black')
    for u in units:
        if u.get('is_active'):
            if u['team'] == my_team or u.get('selected_sub') != 'バッグワーム':
                color = '#00FF7F' if u['team'] == my_team else '#FF0000'
                ax.scatter(u['pos_y'], u['pos_x'], c=color, s=80, edgecolors='white', alpha=0.8)
    ax.set_xlim(-0.5, 14.5); ax.set_ylim(14.5, -0.5); ax.axis('off')
    return fig

# --- C. 戦闘解決エンジン (新機能：環境破壊・貫通・ハイレイン回復) ---

def is_los_clear(u, e, grid):
    steps = max(abs(u['pos_x']-e['pos_x']), abs(u['pos_y']-e['pos_y']))
    if steps == 0: return True
    for i in range(1, steps):
        tx = int(u['pos_x'] + (e['pos_x'] - u['pos_x']) * i / steps)
        ty = int(u['pos_y'] + (e['pos_y'] - u['pos_y']) * i / steps)
        if grid[tx, ty] > max(u.get('pos_z', 0), e.get('pos_z', 0)): return False
    return True

def resolve_turn(my_team, enemy_team, mode, grid):
    st.info("戦況を解決中（環境破壊・貫通判定）...")
    units = supabase.table("unit_states").select("*").execute().data
    session = supabase.table("game_session").select("*").eq("id", 1).single().execute().data
    
    logs = []
    my_pts = session.get('my_points', 0); en_pts = session.get('enemy_points', 0)

    # 1. 移動・先行アクション
    for u in units:
        if not u.get('is_active'): continue
        move = u.get('submitted_move')
        if move: u['pos_x'], u['pos_y'] = move.get('x', u['pos_x']), move.get('y', u['pos_y'])
        
        # ハイレインの建物キューブ化（回復）
        if u['unit_name'] == 'ハイレイン' and u.get('selected_main') == 'アレクトール':
            if grid[u['pos_x'], u['pos_y']] > 0:
                grid[u['pos_x'], u['pos_y']] -= 1 # 建物を削る
                u['trn'] = u.get('trn', 40) + 5 # トリオン回復
                logs.append(f"🦋 ハイレインが周囲の建物をキューブ化！トリオンが回復した。")

    # 2. 攻撃計算
    for u in [u for u in units if u.get('is_active')]:
        master = df_master[df_master['name'] == u['unit_name']].iloc[0]
        cur_trn = u.get('trn', master['trn']) # 現在のトリオン値を使用
        enemies = [e for e in units if e['team'] != u['team'] and e.get('is_active')]
        main_w = u.get('selected_main', '-')

        for e in enemies:
            dist = math.sqrt((u['pos_x']-e['pos_x'])**2 + (u['pos_y']-e['pos_y'])**2 + (u.get('pos_z',0)-e.get('pos_z',0))**2)
            if dist <= master['rng']:
                # --- シールド判定（貫通ロジック） ---
                is_shielded = (e.get('selected_sub') == 'シールド')
                dmg_mult = 1.0
                if is_shielded:
                    # トリオン差による貫通判定
                    e_master = df_master[df_master['name'] == e['unit_name']].iloc[0]
                    e_trn = e.get('trn', e_master['trn'])
                    if cur_trn > e_trn * 3: # トリオンが相手の3倍以上なら貫通
                        dmg_mult = 0.8 
                        logs.append(f"⚡ {u['unit_name']} のトリオンがシールドを貫通！")
                    else:
                        dmg_mult = 0.3 # 通常のシールド軽減
                
                # --- 特殊攻撃ロジック ---
                if main_w == 'オルガノン':
                    atk = master['atk'] * 1.5
                    grid[e['pos_x'], e['pos_y']] = max(0, grid[e['pos_x'], e['pos_y']] - 1) # 環境破壊
                    damage = int(atk * dmg_mult)
                    e['hp'] -= damage
                    logs.append(f"🌀 オルガノンが {e['unit_name']} とビルを切り裂く！({damage}ダメ)")

                elif main_w == 'アレクトール':
                    damage = int(master['atk'] * dmg_mult)
                    e['hp'] -= damage
                    e['trn'] = max(1, e.get('trn', 10) - 5) # トリオンデバフ
                    logs.append(f"🦋 アレクトールが {e['unit_name']} のトリオンを削り取った！")

                elif main_w == 'アイビス' and u['unit_name'] == '雨取 千佳':
                    atk = 25 * (cur_trn / 0.9)
                    grid[e['pos_x'], e['pos_y']] = max(0, grid[e['pos_x'], e['pos_y']] - 2) # 大規模破壊
                    damage = int(atk * dmg_mult)
                    e['hp'] -= damage
                    logs.append(f"💣 千佳の砲撃！命中地点のビルが粉砕された！({damage}ダメ)")

                elif is_los_clear(u, e, grid): # 通常攻撃
                    atk = (master['atk']+10) * (1 + cur_trn/15)
                    damage = max(5, int(atk*dmg_mult - 10))
                    e['hp'] -= damage
                    logs.append(f"💥 {u['unit_name']} -> {e['unit_name']} ({damage}ダメ)")

                if e['hp'] <= 0:
                    e['hp'] = 0; e['is_active'] = False
                    logs.append(f"💀 {e['unit_name']} ベイルアウト！")
                    if u['team'] == my_team: my_pts += 1
                    else: en_pts += 1

    # 3. 更新
    for u in units:
        supabase.table("unit_states").update({
            "hp": u['hp'], "pos_x": u['pos_x'], "pos_y": u['pos_y'], "is_active": u['is_active'], 
            "trn": u.get('trn'), "submitted_move": None
        }).eq("unit_name", u['unit_name']).execute()
    
    supabase.table("game_session").update({"current_turn": session['current_turn']+1, "my_points": my_pts, "enemy_points": en_pts}).eq("id", 1).execute()
    for l in logs: supabase.table("battle_logs").insert({"turn": session['current_turn'], "message": l}).execute()
    st.session_state.grid = grid # グリッド更新

# --- D. メイン UI (初期化時に trn をセットするように修正) ---

st.title("🛰️ World Trigger Online: Destruction Mode")

session = supabase.table("game_session").select("*").eq("id", 1).single().execute().data
live_units = supabase.table("unit_states").select("*").execute().data

with st.sidebar:
    st.header(f"Turn {session['current_turn']} / 10")
    c1, c2 = st.columns(2)
    c1.metric("味方点", session.get('my_points', 0))
    c2.metric("敵点", session.get('enemy_points', 0))
    
    entry_mode = st.radio("エントリー方式", ["部隊プリセット", "カスタム編成"])
    if entry_mode == "部隊プリセット":
        my_team = st.selectbox("自分の部隊", df_master['team'].unique(), index=1)
        enemy_team = st.selectbox("敵部隊", [t for t in df_master['team'].unique() if t != my_team])
    else:
        my_team = "カスタム"; enemy_team = "敵チーム"
        custom_members = st.multiselect("メンバー選択", df_master['name'].unique())

    if st.button("リセット・試合開始"):
        supabase.table("unit_states").delete().neq("id", 0).execute()
        supabase.table("battle_logs").delete().neq("id", 0).execute()
        selected = df_master[df_master['team'].isin([my_team, enemy_team])] if entry_mode=="部隊プリセット" else df_master[df_master['name'].isin(custom_members)]
        for _, row in selected.iterrows():
            supabase.table("unit_states").insert({
                "unit_name": row['name'], "team": row['team'] if entry_mode=="部隊プリセット" else "カスタム",
                "hp": 100, "trn": row['trn'], # 初期トリオンをセット
                "pos_x": random.randint(0, 14), "pos_y": random.randint(0, 14), "is_active": True
            }).execute()
        supabase.table("game_session").update({"current_turn": 1, "my_points":0, "enemy_points":0}).eq("id", 1).execute()
        st.rerun()
    
    st.pyplot(draw_radar(live_units, my_team))

col_map, col_cmd = st.columns([2, 1])
with col_map:
    if 'grid' not in st.session_state: st.session_state.grid = np.random.randint(0, 4, (GRID_SIZE, GRID_SIZE))
    st.pyplot(draw_tactical_map(st.session_state.grid, live_units, my_team))
    logs = supabase.table("battle_logs").select("*").order("id", desc=True).limit(8).execute().data
    for l in logs: st.caption(f"Turn {l['turn']}: {l['message']}")

with col_cmd:
    st.subheader("🎮 コマンド入力")
    my_active = [u for u in live_units if u['team'] == my_team and u.get('is_active')]
    for u in my_active:
        with st.expander(f"{u['unit_name']} (HP:{int(u['hp'])}, Trn:{int(u.get('trn',0))})"):
            m = df_master[df_master['name'] == u['unit_name']].iloc[0]
            nx = st.number_input("移動先X", 0, 14, u['pos_x'], key=f"x{u['unit_name']}")
            ny = st.number_input("移動先Y", 0, 14, u['pos_y'], key=f"y{u['unit_name']}")
            main_t = st.selectbox("メイン", [m[f'main{i}'] for i in range(1, 5) if m[f'main{i}'] != '-'], key=f"m{u['unit_name']}")
            sub_t = st.selectbox("サブ", [m[f'sub{i}'] for i in range(1, 5) if m[f'sub{i}'] != '-'], key=f"s{u['unit_name']}")
            if st.button("保存", key=f"b{u['unit_name']}"):
                supabase.table("unit_states").update({"submitted_move": {"x": nx, "y": ny}, "selected_main": main_t, "selected_sub": sub_t}).eq("unit_name", u['unit_name']).execute()
                st.success("保存完了")
    if st.button("🚨 解決（ターン進行）"):
        resolve_turn(my_team, enemy_team, "コンピューター（CPU）" if "CPU" in st.sidebar.radio("対戦", ["友人", "CPU"], label_visibility="collapsed") else "友人", st.session_state.grid)
        st.rerun()

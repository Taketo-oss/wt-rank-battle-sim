import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import japanize_matplotlib  # 日本語化
from matplotlib.colors import ListedColormap
from supabase import create_client, Client
import random, math, time

# --- A. 初期設定 ---
st.set_page_config(layout="wide", page_title="WT Rank Battle: Ultimate Edition")
supabase: Client = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

GRID_SIZE = 15
df_master = pd.read_csv("units.csv")

# --- B. 描画エンジン (高度・HP・AP・視界制限) ---

def draw_tactical_map(grid, units, my_team):
    """マップとユニット情報の描画"""
    fig, ax = plt.subplots(figsize=(12, 12))
    # 0:地面, 1-5:ビル高度
    cmap = ListedColormap(['#8B4513', '#D3D3D3', '#BDBDBD', '#9E9E9E', '#757575', '#424242', '#00FF7F', '#FF4500'])
    
    display_map = grid.copy().astype(float)
    my_units = [u for u in units if u['team'] == my_team and u.get('is_active')]

    for u in units:
        if not u.get('is_active'): continue
        
        # 視界判定 (味方から5マス以内)
        is_visible = (u['team'] == my_team)
        if not is_visible:
            for my_u in my_units:
                if math.sqrt((u['pos_x']-my_u['pos_x'])**2 + (u['pos_y']-my_u['pos_y'])**2) <= 5:
                    is_visible = True; break

        if is_visible:
            val = 6 if u['team'] == my_team else 7
            display_map[u['pos_x'], u['pos_y']] = val
            
            # ユニットラベル (名前 + HP + Z + AP)
            z_now = int(u.get('pos_z', 0))
            hp_now = int(u.get('hp', 0))
            ap_now = int(u.get('ap', 0))
            label = f"{u['unit_name']}\nHP:{hp_now} Z:{z_now} AP:{ap_now}"
            
            color_bg = '#00FF7F' if u['team'] == my_team else '#FF4500'
            ax.text(u['pos_y'], u['pos_x'] - 0.7, label, color='white', fontsize=9, 
                    fontweight='bold', ha='center', va='bottom',
                    bbox=dict(facecolor=color_bg, alpha=0.9, boxstyle='round,pad=0.3'))

    ax.imshow(display_map, cmap=cmap, vmin=0, vmax=7, interpolation='nearest')
    for i in range(GRID_SIZE):
        for j in range(GRID_SIZE):
            if grid[i, j] > 0:
                ax.text(j, i, str(int(grid[i, j])), ha='center', va='center', 
                        color='white', alpha=0.4, fontweight='bold', fontsize=12)
    return fig

# --- C. 戦闘解決エンジン (全機能マージ) ---

def is_los_clear(u, e, grid):
    """射線判定: 高いビルがあれば遮蔽される"""
    steps = max(abs(u['pos_x']-e['pos_x']), abs(u['pos_y']-e['pos_y']))
    if steps == 0: return True
    for i in range(1, steps):
        tx = int(u['pos_x'] + (e['pos_x'] - u['pos_x']) * i / steps)
        ty = int(u['pos_y'] + (e['pos_y'] - u['pos_y']) * i / steps)
        if grid[tx, ty] > max(u.get('pos_z', 0), e.get('pos_z', 0)): return False
    return True

def resolve_turn(my_team, enemy_team, mode, grid):
    st.info("APを計算し、戦況を解決しています...")
    units = supabase.table("unit_states").select("*").execute().data
    session = supabase.table("game_session").select("*").eq("id", 1).single().execute().data
    
    logs = []
    my_pts = session.get('my_points', 0); en_pts = session.get('enemy_points', 0)

    # 1. 行動解決
    for u in units:
        if not u.get('is_active'): continue
        master = df_master[df_master['name'] == u['unit_name']].iloc[0]
        u['ap'] = min(20, u.get('ap', 0) + int(master['mob']) + 5) # AP回復

        move = u.get('submitted_move')
        if move:
            nx, ny, nz = move.get('x'), move.get('y'), move.get('z')
            # 実際の移動
            u['pos_x'], u['pos_y'], u['pos_z'] = nx, ny, nz
            
        elif mode == "コンピューター（CPU）" and u['team'] == enemy_team:
            targets = [t for t in units if t['team'] == my_team and t['is_active']]
            if targets:
                target = random.choice(targets)
                u['pos_x'] += (1 if target['pos_x'] > u['pos_x'] else -1 if target['pos_x'] < u['pos_x'] else 0)
                u['pos_y'] += (1 if target['pos_y'] > u['pos_y'] else -1 if target['pos_y'] < u['pos_y'] else 0)
                u['pos_z'] = grid[u['pos_x'], u['pos_y']]

        # 特殊: ハイレイン建物捕食
        if u['unit_name'] == 'ハイレイン' and u.get('selected_main') == 'アレクトール' and grid[u['pos_x'], u['pos_y']] > 0:
            grid[u['pos_x'], u['pos_y']] -= 1
            u['trn'] = u.get('trn', 40) + 10
            logs.append(f"🦋 ハイレインが建物の一部を吸収した！")

    # 2. 攻撃・ダメージ計算
    for u in [u for u in units if u.get('is_active')]:
        master = df_master[df_master['name'] == u['unit_name']].iloc[0]
        cur_trn = u.get('trn', master['trn'])
        enemies = [e for e in units if e['team'] != u['team'] and e.get('is_active')]
        main_w = u.get('selected_main', '-')

        for e in enemies:
            # 3D距離: $$dist = \sqrt{(x_1-x_2)^2 + (y_1-y_2)^2 + (z_1-z_2)^2}$$
            dist = math.sqrt((u['pos_x']-e['pos_x'])**2 + (u['pos_y']-e['pos_y'])**2 + (u.get('pos_z',0)-e.get('pos_z',0))**2)
            
            if dist <= master['rng'] and main_w != '-':
                # 貫通判定
                is_shielded = (e.get('selected_sub') == 'シールド')
                dmg_mult = 1.0
                if is_shielded:
                    e_master = df_master[df_master['name'] == e['unit_name']].iloc[0]
                    if cur_trn > e.get('trn', e_master['trn']) * 2.5: 
                        dmg_mult = 0.9; logs.append(f"⚡ {u['unit_name']} の出力がシールドを貫通！")
                    else: dmg_mult = 0.5
                
                # 基本攻撃力と乱数・クリティカル
                base_atk = (master['atk'] * 1.5) * (1 + cur_trn / 8)
                variation = random.uniform(0.85, 1.15)
                is_crit = random.random() < 0.08
                crit_mult = 1.8 if is_crit else 1.0

                if main_w == 'オルガノン':
                    base_atk *= 2.0; grid[e['pos_x'], e['pos_y']] = max(0, grid[e['pos_x'], e['pos_y']] - 1)
                elif main_w == 'アイビス' and u['unit_name'] == '雨取 千佳':
                    base_atk = 50 * (cur_trn / 0.8); grid[e['pos_x'], e['pos_y']] = max(0, grid[e['pos_x'], e['pos_y']] - 2)

                if is_los_clear(u, e, grid) or main_w in ['オルガノン', 'バイパー']:
                    dmg = int(base_atk * dmg_mult * variation * crit_mult)
                    e['hp'] -= dmg
                    logs.append(f"{'🔴 [CRIT] ' if is_crit else ''}{u['unit_name']} -> {e['unit_name']} ({dmg}ダメ)")
                    
                    if e['hp'] <= 0:
                        e['hp'] = 0; e['is_active'] = False
                        if u['team'] == my_team: en_pts += 0; my_pts += 1
                        else: en_pts += 1

    # 3. DB更新
    for u in units:
        supabase.table("unit_states").update({
            "hp": u['hp'], "pos_x": u['pos_x'], "pos_y": u['pos_y'], "pos_z": u['pos_z'],
            "ap": u['ap'], "trn": u.get('trn'), "is_active": u['is_active'], "submitted_move": None
        }).eq("unit_name", u['unit_name']).execute()
    
    supabase.table("game_session").update({"current_turn": session['current_turn']+1, "my_points":my_pts, "enemy_points":en_pts}).eq("id", 1).execute()
    for l in logs: supabase.table("battle_logs").insert({"turn": session['current_turn'], "message": l}).execute()

# --- D. UI レイアウト ---

st.title("🛰️ World Trigger Online: Ultimate Simulator")

session = supabase.table("game_session").select("*").eq("id", 1).single().execute().data
live_units = supabase.table("unit_states").select("*").execute().data

with st.sidebar:
    st.header(f"Turn {session['current_turn']} / 10")
    c1, c2 = st.columns(2); c1.metric("味方点", session['my_points']); c2.metric("敵点", session['enemy_points'])
    
    st.markdown("---")
    entry_mode = st.radio("チーム編成", ["部隊プリセット", "カスタム編成"])
    if entry_mode == "部隊プリセット":
        my_team = st.selectbox("自分の部隊", df_master['team'].unique(), index=1)
        enemy_team = st.selectbox("敵部隊", [t for t in df_master['team'].unique() if t != my_team])
    else:
        my_team = "カスタム"; enemy_team = "敵チーム"
        custom_members = st.multiselect("メンバー選択(最大4名)", df_master['name'].unique())

    mode = st.radio("対戦形式", ["友人", "CPU"])
    
    if st.button("試合開始（初期化）"):
        supabase.table("unit_states").delete().neq("id", 0).execute()
        supabase.table("battle_logs").delete().neq("id", 0).execute()
        selected = df_master[df_master['team'].isin([my_team, enemy_team])] if entry_mode=="部隊プリセット" else df_master[df_master['name'].isin(custom_members)]
        for _, row in selected.iterrows():
            supabase.table("unit_states").insert({
                "unit_name": row['name'], "team": row['team'] if entry_mode=="部隊プリセット" else "カスタム",
                "hp": 100, "ap": 20, "trn": row['trn'], "pos_x": random.randint(0, 14), "pos_y": random.randint(0, 14), "pos_z": 0, "is_active": True
            }).execute()
        supabase.table("game_session").update({"current_turn": 1, "my_points":0, "enemy_points":0}).eq("id", 1).execute()
        st.rerun()

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
        with st.expander(f"{u['unit_name']} (HP:{int(u['hp'])} AP:{u.get('ap')})"):
            m = df_master[df_master['name'] == u['unit_name']].iloc[0]
            cx1, cx2, cx3 = st.columns(3)
            nx = cx1.number_input("X", 0, 14, u['pos_x'], key=f"x{u['unit_name']}")
            ny = cx2.number_input("Y", 0, 14, u['pos_y'], key=f"y{u['unit_name']}")
            # 高度制限
            nz = cx3.number_input("Z", 0, int(st.session_state.grid[nx, ny]), u['pos_z'], key=f"z{u['unit_name']}")
            
            main_t = st.selectbox("メイン", [m[f'main{i}'] for i in range(1, 5) if m[f'main{i}'] != '-'], key=f"m{u['unit_name']}")
            sub_t = st.selectbox("サブ", [m[f'sub{i}'] for i in range(1, 5) if m[f'sub{i}'] != '-'], key=f"s{u['unit_name']}")
            
            # APコスト計算
            cost = (abs(u['pos_x']-nx) + abs(u['pos_y']-ny)) + (abs(u['pos_z']-nz) * 2) + (5 if main_t != '-' else 0)
            st.caption(f"消費AP: {cost} {'⚠️不足' if cost > u.get('ap',0) else '✅OK'}")

            if st.button("行動確定", key=f"b{u['unit_name']}"):
                supabase.table("unit_states").update({"submitted_move": {"x": nx, "y": ny, "z": nz}, "selected_main": main_t, "selected_sub": sub_t}).eq("unit_name", u['unit_name']).execute()
                st.success("予約完了")

    if st.button("🚨 全行動を解決する"):
        resolve_turn(my_team, enemy_team, mode, st.session_state.grid)
        st.rerun()

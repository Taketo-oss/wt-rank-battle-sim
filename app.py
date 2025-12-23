import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import japanize_matplotlib
from matplotlib.colors import ListedColormap
from supabase import create_client, Client
import random, math, time

# --- A. 初期設定 ---
st.set_page_config(layout="wide", page_title="WT Rank Battle: Ultimate v7")
supabase: Client = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

GRID_SIZE = 15
df_master = pd.read_csv("units.csv")

# --- B. 描画エンジン (レーダー・高度・HP・AP統合) ---

def draw_tactical_map(grid, units, my_team):
    """メインマップ：視界制限と詳細ステータス表示"""
    fig, ax = plt.subplots(figsize=(10, 10), facecolor='#1e212b')
    ax.set_facecolor('#1e212b')
    
    # 0:地面, 1-5:ビル, 6:味方(ミントグリーン), 7:敵(赤)
    cmap = ListedColormap(['#3d2b1f', '#d3d3d3', '#bdbdbd', '#9e9e9e', '#757575', '#424242', '#2ecc71', '#e74c3c'])
    
    display_map = grid.copy().astype(float)
    my_active_units = [u for u in units if u['team'] == my_team and u.get('is_active')]

    for u in units:
        if not u.get('is_active'): continue
        
        # 視界判定 (味方から5マス以内)
        is_visible = (u['team'] == my_team)
        if not is_visible:
            for my_u in my_active_units:
                if math.sqrt((u['pos_x']-my_u['pos_x'])**2 + (u['pos_y']-my_u['pos_y'])**2) <= 5:
                    is_visible = True; break

        if is_visible:
            val = 6 if u['team'] == my_team else 7
            display_map[u['pos_x'], u['pos_y']] = val
            
            # ラベル：名前 + Z + HP + AP
            hp_now = int(u.get('hp', 0))
            ap_now = int(u.get('ap', 0))
            z_now = int(u.get('pos_z', 0))
            label = f"{u['unit_name']}\nHP:{hp_now} Z:{z_now} AP:{ap_now}"
            
            # ミントグリーン(味方) vs 赤(敵)
            label_bg = '#2ecc71' if u['team'] == my_team else '#e74c3c'
            ax.text(u['pos_y'], u['pos_x'] - 0.8, label, color='white', fontsize=8, 
                    fontweight='bold', ha='center', va='bottom',
                    bbox=dict(facecolor=label_bg, alpha=0.9, boxstyle='round,pad=0.3'))

    ax.imshow(display_map, cmap=cmap, vmin=0, vmax=7, interpolation='nearest')
    for i in range(GRID_SIZE):
        for j in range(GRID_SIZE):
            if grid[i, j] > 0:
                ax.text(j, i, str(int(grid[i, j])), ha='center', va='center', color='white', alpha=0.3, fontweight='bold')
    return fig

def draw_radar(units, my_team):
    """【復活】レーダー機能：バッグワーム使用者は非表示"""
    fig, ax = plt.subplots(figsize=(4, 4), facecolor='#0d1117')
    ax.set_facecolor('#0d1117')
    
    # レーダーの円形ガイド
    for r in [3, 7, 11]:
        circle = plt.Circle((7, 7), r, color='#1b5e20', fill=False, linestyle=':', alpha=0.5)
        ax.add_artist(circle)

    for u in units:
        if u.get('is_active'):
            # バッグワーム使用中の敵はレーダーに映らない
            if u['team'] == my_team or u.get('selected_sub') != 'バッグワーム':
                color = '#2ecc71' if u['team'] == my_team else '#e74c3c'
                ax.scatter(u['pos_y'], u['pos_x'], c=color, s=100, edgecolors='white', alpha=0.8, marker='H')
    
    ax.set_xlim(-0.5, 14.5); ax.set_ylim(14.5, -0.5)
    ax.axis('off')
    return fig

# --- C. 戦闘解決エンジン (全ロジック統合) ---

def is_los_clear(u, e, grid):
    steps = max(abs(u['pos_x']-e['pos_x']), abs(u['pos_y']-e['pos_y']))
    if steps == 0: return True
    for i in range(1, steps):
        tx = int(u['pos_x'] + (e['pos_x'] - u['pos_x']) * i / steps)
        ty = int(u['pos_y'] + (e['pos_y'] - u['pos_y']) * i / steps)
        if grid[tx, ty] > max(u.get('pos_z', 0), e.get('pos_z', 0)): return False
    return True

def resolve_turn(my_team, enemy_team, mode, grid):
    st.info("AP消費と戦闘結果を計算中...")
    units = supabase.table("unit_states").select("*").execute().data
    session = supabase.table("game_session").select("*").eq("id", 1).single().execute().data
    
    logs = []
    my_pts = session.get('my_points', 0); en_pts = session.get('enemy_points', 0)

    for u in units:
        if not u.get('is_active'): continue
        master = df_master[df_master['name'] == u['unit_name']].iloc[0]
        # AP回復
        u['ap'] = min(25, u.get('ap', 0) + int(master['mob']) + 5)

        move = u.get('submitted_move')
        if move:
            u['pos_x'], u['pos_y'], u['pos_z'] = move.get('x'), move.get('y'), move.get('z')
        
        elif mode == "コンピューター（CPU）" and u['team'] == enemy_team:
            targets = [t for t in units if t['team'] == my_team and t['is_active']]
            if targets:
                target = random.choice(targets)
                u['pos_x'] += (1 if target['pos_x'] > u['pos_x'] else -1 if target['pos_x'] < u['pos_x'] else 0)
                u['pos_y'] += (1 if target['pos_y'] > u['pos_y'] else -1 if target['pos_y'] < u['pos_y'] else 0)
                u['pos_z'] = grid[u['pos_x'], u['pos_y']]

    # 攻撃解決
    for u in [u for u in units if u.get('is_active')]:
        master = df_master[df_master['name'] == u['unit_name']].iloc[0]
        enemies = [e for e in units if e['team'] != u['team'] and e.get('is_active')]
        main_w = u.get('selected_main', '-')
        
        for e in enemies:
            # 3D距離計算: $dist = \sqrt{(x_1-x_2)^2 + (y_1-y_2)^2 + (z_1-z_2)^2}$
            dist = math.sqrt((u['pos_x']-e['pos_x'])**2 + (u['pos_y']-e['pos_y'])**2 + (u.get('pos_z',0)-e.get('pos_z',0))**2)
            if dist <= master['rng'] and main_w != '-':
                atk = (master['atk'] * 1.5) * (1 + master['trn']/10) * random.uniform(0.85, 1.15)
                # 特殊トリガーと環境破壊
                if main_w == 'オルガノン': atk *= 2.0; grid[e['pos_x'], e['pos_y']] = max(0, grid[e['pos_x'], e['pos_y']] - 1)
                elif main_w == 'アイビス' and u['unit_name'] == '雨取 千佳': atk *= 3.0; grid[e['pos_x'], e['pos_y']] = max(0, grid[e['pos_x'], e['pos_y']] - 2)

                if is_los_clear(u, e, grid) or main_w in ['オルガノン', 'バイパー']:
                    dmg = int(atk)
                    e['hp'] -= dmg
                    logs.append(f"💥 {u['unit_name']} -> {e['unit_name']} ({dmg}ダメ)")
                    if e['hp'] <= 0:
                        e['hp'] = 0; e['is_active'] = False
                        if u['team'] == my_team: my_pts += 1
                        else: en_pts += 1

    # DB一括更新
    for u in units:
        supabase.table("unit_states").update({
            "hp": u['hp'], "pos_x": u['pos_x'], "pos_y": u['pos_y'], "pos_z": u['pos_z'],
            "ap": u['ap'], "is_active": u['is_active'], "submitted_move": None
        }).eq("unit_name", u['unit_name']).execute()
    
    supabase.table("game_session").update({"current_turn": session['current_turn']+1, "my_points":my_pts, "enemy_points":en_pts}).eq("id", 1).execute()
    for l in logs: supabase.table("battle_logs").insert({"turn": session['current_turn'], "message": l}).execute()

# --- D. メイン UI ---

st.title("🛰️ World Trigger Online: Ultimate v7")

session = supabase.table("game_session").select("*").eq("id", 1).single().execute().data
live_units = supabase.table("unit_states").select("*").execute().data

with st.sidebar:
    st.header(f"Turn {session['current_turn']} / 10")
    c1, c2 = st.columns(2)
    c1.metric("味方点", session.get('my_points', 0))
    c2.metric("敵点", session.get('enemy_points', 0))
    
    st.markdown("---")
    # レーダー表示
    st.subheader("📡 トリオン探知レーダー")
    st.pyplot(draw_radar(live_units, "操作部隊"))
    
    st.markdown("---")
    entry_mode = st.radio("チーム編成", ["部隊プリセット", "カスタム編成"])
    if entry_mode == "部隊プリセット":
        my_team_sel = st.selectbox("自分の部隊", df_master['team'].unique(), index=1)
        enemy_team_sel = st.selectbox("敵部隊", [t for t in df_master['team'].unique() if t != my_team_sel])
    else:
        my_team_sel = "カスタム"; enemy_team_sel = "敵チーム"
        custom_members = st.multiselect("メンバー選択(最大4名)", df_master['name'].unique())

    mode = st.radio("対戦形式", ["友人（オンライン）", "コンピューター（CPU）"])
    
    if st.button("試合開始（初期化）"):
        supabase.table("unit_states").delete().neq("id", 0).execute()
        supabase.table("battle_logs").delete().neq("id", 0).execute()
        selected = df_master[df_master['team'].isin([my_team_sel, enemy_team_sel])] if entry_mode=="部隊プリセット" else df_master[df_master['name'].isin(custom_members)]
        for _, row in selected.iterrows():
            supabase.table("unit_states").insert({
                "unit_name": row['name'], "team": row['team'] if entry_mode=="部隊プリセット" else "カスタム",
                "hp": 100, "ap": 20, "pos_x": random.randint(0, 14), "pos_y": random.randint(0, 14), "pos_z": 0, "is_active": True
            }).execute()
        supabase.table("game_session").update({"current_turn": 1, "my_points":0, "enemy_points":0}).eq("id", 1).execute()
        st.rerun()

col_map, col_cmd = st.columns([2, 1])

with col_map:
    if 'grid' not in st.session_state: st.session_state.grid = np.random.randint(0, 4, (GRID_SIZE, GRID_SIZE))
    st.pyplot(draw_tactical_map(st.session_state.grid, live_units, "操作部隊"))
    logs = supabase.table("battle_logs").select("*").order("id", desc=True).limit(5).execute().data
    for l in logs: st.caption(f"Turn {l['turn']}: {l['message']}")

with col_cmd:
    st.subheader("🎮 コマンドプロット")
    my_active = [u for u in live_units if u['team'] == "操作部隊" or u['team'] == my_team_sel and u.get('is_active')]
    for u in my_active:
        with st.expander(f"{u['unit_name']} (HP:{int(u.get('hp'))} AP:{u.get('ap')})"):
            m = df_master[df_master['name'] == u['unit_name']].iloc[0]
            cx1, cx2, cx3 = st.columns(3)
            nx = cx1.number_input("移動X", 0, 14, u['pos_x'], key=f"x{u['unit_name']}")
            ny = cx2.number_input("移動Y", 0, 14, u['pos_y'], key=f"y{u['unit_name']}")
            nz = cx3.number_input("高度Z", 0, int(st.session_state.grid[nx, ny]), u['pos_z'], key=f"z{u['unit_name']}")
            
            m_t = st.selectbox("使用トリガー", [m[f'main{i}'] for i in range(1, 5) if m[f'main{i}'] != '-'], key=f"m{u['unit_name']}")
            s_t = st.selectbox("サブ", [m[f'sub{i}'] for i in range(1, 5) if m[f'sub{i}'] != '-'], key=f"s{u['unit_name']}")
            
            cost = (abs(u['pos_x']-nx) + abs(u['pos_y']-ny)) + (abs(u['pos_z']-nz) * 2) + (5 if m_t != '-' else 0)
            st.caption(f"消費予定AP: {cost}")

            if st.button("行動確定", key=f"b{u['unit_name']}"):
                supabase.table("unit_states").update({
                    "submitted_move": {"x": nx, "y": ny, "z": nz}, "selected_main": m_t, "selected_sub": s_t
                }).eq("unit_name", u['unit_name']).execute()
                st.success("予約完了")

    if st.button("🚨 全行動を解決する"):
        resolve_turn(my_team_sel, enemy_team_sel, mode, st.session_state.grid)
        st.rerun()

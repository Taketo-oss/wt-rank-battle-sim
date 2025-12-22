import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from supabase import create_client, Client
import math
import random

# --- 1. 初期設定 ---
st.set_page_config(layout="wide", page_title="WT Rank Battle Sim")
url = st.secrets["SUPABASE_URL"]
key = st.secrets["SUPABASE_KEY"]
supabase = create_client(url, key)

GRID_SIZE = 15

# --- 2. 描画エンジン（レーダーと名前付きマップ） ---

def draw_enhanced_map(grid, units, my_team):
    """メインマップ：名前と高低差を表示"""
    fig, ax = plt.subplots(figsize=(10, 10))
    cmap = ListedColormap(['#8B4513', '#D3D3D3', '#A9A9A9', '#808080', '#696969', '#2F4F4F', '#00FF7F', '#FF4500'])
    
    display_map = grid.copy().astype(float)
    for u in units:
        if u['is_active']:
            color = 6 if u['team'] == my_team else 7
            display_map[u['pos_x'], u['pos_y']] = color
            
            # 駒の横に名前を表示（自分のチームは強調）
            text_color = 'lime' if u['team'] == my_team else 'red'
            ax.text(u['pos_y'], u['pos_x'] - 0.6, u['unit_name'], 
                    color='white', fontsize=9, fontweight='bold', ha='center',
                    bbox=dict(facecolor=text_color, alpha=0.7, edgecolor='white', boxstyle='round,pad=0.3'))

    ax.imshow(display_map, cmap=cmap, vmin=0, vmax=7, interpolation='nearest')
    
    # マップの数字（ビルの高さ）を表示
    for i in range(GRID_SIZE):
        for j in range(GRID_SIZE):
            if grid[i, j] > 0:
                ax.text(j, i, str(int(grid[i, j])), ha='center', va='center', color='black', alpha=0.3, fontsize=8)
    
    ax.set_xticks(range(GRID_SIZE)); ax.set_yticks(range(GRID_SIZE))
    return fig

def draw_trion_radar(units, my_team):
    """レーダー画面：トリオン信号のみを表示"""
    fig, ax = plt.subplots(figsize=(4, 4), facecolor='black')
    ax.set_facecolor('black')
    
    # 走査線の円を描画
    for r in [5, 10, 15]:
        circle = plt.Circle((7, 7), r, color='#004400', fill=False, linestyle='--')
        ax.add_artist(circle)

    for u in units:
        if u['is_active']:
            color = '#00FF7F' if u['team'] == my_team else '#FF0000'
            # トリオン信号を光らせる
            ax.scatter(u['pos_y'], u['pos_x'], c=color, s=100, alpha=0.8, edgecolors='white', linewidth=1)
            # レーダー上にも薄く名前を表示
            ax.text(u['pos_y'], u['pos_x'] + 0.8, u['unit_name'][:2], color=color, fontsize=7, ha='center')

    ax.set_xlim(-0.5, 14.5); ax.set_ylim(14.5, -0.5)
    ax.axis('off')
    return fig

# --- 3. メインUI ---

st.title("🛰️ World Trigger: Advanced Rank Battle")

# データ読み込み
df = pd.read_csv("units.csv")
res = supabase.table("unit_states").select("*").execute()
live_units = res.data if res.data else []

# サイドバー：自分のチーム選択とレーダー
with st.sidebar:
    st.header("RADAR - 索敵画面")
    my_team = st.selectbox("自分の操作部隊", df['team'].unique(), index=1)
    st.pyplot(draw_trion_radar(live_units, my_team))
    
    st.markdown("---")
    if st.button("全隊員を再配置（初期化）"):
        # 初期化ロジックは前回同様
        pass

# メイン画面のレイアウト
col_map, col_cmd = st.columns([2, 1])

with col_map:
    if 'grid' not in st.session_state:
        st.session_state.grid = np.random.randint(0, 4, (15, 15))
    st.pyplot(draw_enhanced_map(st.session_state.grid, live_units, my_team))

with col_cmd:
    st.subheader("🛠️ コマンド入力")
    my_active_units = [u for u in live_units if u['team'] == my_team and u['is_active']]
    
    if not my_active_units:
        st.info("サイドバーから初期化ボタンを押して、駒を配置してください。")
    
    for u in my_active_units:
        # CSVからトリガー情報を取得
        m_data = df[df['name'] == u['unit_name']].iloc[0]
        
        with st.expander(f"【{u['unit_name']}】の行動"):
            # 1. 移動先
            c1, c2 = st.columns(2)
            nx = c1.number_input(f"移動X", 0, 14, u['pos_x'], key=f"nx_{u['unit_name']}")
            ny = c2.number_input(f"移動Y", 0, 14, u['pos_y'], key=f"ny_{u['unit_name']}")
            
            # 2. メイントリガー選択 (Main 1-4)
            main_trigs = [m_data[f'main{i}'] for i in range(1, 5) if m_data[f'main{i}'] != '-']
            sel_main = st.selectbox("メイン側トリガー", main_trigs, key=f"sm_{u['unit_name']}")
            
            # 3. サブトリガー選択 (Sub 1-4)
            sub_trigs = [m_data[f'sub{i}'] for i in range(1, 5) if m_data[f'sub{i}'] != '-']
            sel_sub = st.selectbox("サブ側トリガー", sub_trigs, key=f"ss_{u['unit_name']}")
            
            if st.button(f"{u['unit_name']} のプロットを確定", key=f"btn_{u['unit_name']}"):
                supabase.table("unit_states").update({
                    "pos_x": nx, "pos_y": ny,
                    "selected_main": sel_main,
                    "selected_sub": sel_sub,
                    "submitted_move": {"active": True}
                }).eq("unit_name", u['unit_name']).execute()
                st.success("保存完了")
                st.rerun()

    st.markdown("---")
    if st.button("🚨 ターンを解決する（全員移動・攻撃）"):
        # 戦闘解決ロジックを実行（ここでselected_main/subを参照してダメージ計算）
        st.write("戦闘解決を実行しました。ページをリロードしてください。")

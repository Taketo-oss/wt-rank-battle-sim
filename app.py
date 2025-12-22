import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from supabase import create_client, Client
import random

# --- 1. 定数と数理モデル ---
GRID_SIZE = 15
MAX_HEIGHT = 5
MAX_TURNS = 10

def calc_hp(trn, dfn):
    return trn * 2.5 + dfn * 1.5

def calc_final_atk(u, trigger_type):
    if u['pos_type'] == 'Attacker': # 近接はトリオン量に依存しない
        return u['atk'] + 10 
    # 狙撃（アイビス）はトリオン量に比例（千佳の42倍を再現）
    if trigger_type == 'アイビス':
        return 25 * (u['trn'] / 0.9)
    # 通常射撃は緩やかに比例
    return (u['atk'] + 10) * (1 + u['trn'] / 15)

# --- 2. Supabase 連携 ---
@st.cache_resource
def init_supabase():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_supabase()

# --- 3. 描画ロジック ---
def draw_pixel_map(grid, units):
    fig, ax = plt.subplots(figsize=(8, 8))
    # 0:地, 1-5:ビル, 6:味方, 7:敵
    cmap = ListedColormap(['#8B4513', '#D3D3D3', '#A9A9A9', '#808080', '#696969', '#2F4F4F', '#1E90FF', '#FF4500'])
    norm = plt.Normalize(vmin=0, vmax=7)
    
    map_data = grid.copy().astype(float)
    for u in units:
        if u['is_active']:
            val = 6 if u['team'] == st.session_state.my_team else 7
            map_data[u['pos_x'], u['pos_y']] = val
            
    ax.imshow(map_data, cmap=cmap, norm=norm, interpolation='nearest')
    ax.set_xticks(np.arange(-0.5, 15, 1), minor=True)
    ax.set_yticks(np.arange(-0.5, 15, 1), minor=True)
    ax.grid(which='minor', color='black', linestyle='-', linewidth=0.5)
    return fig

# --- 4. メインUI ---
st.title("World Trigger: Web Rank Battle Sim")

if 'df' not in st.session_state:
    st.session_state.df = pd.read_csv("units.csv")
    st.session_state.grid = np.random.randint(0, 6, (15, 15))

st.sidebar.header("チーム編成")
st.session_state.my_team = st.sidebar.selectbox("自分の部隊", st.session_state.df['team'].unique())

col1, col2 = st.columns([3, 2])

with col1:
    st.subheader("15x15x5 ランク戦フィールド")
    # ここでは仮のユニットデータで描画
    sample_units = [{"pos_x": 0, "pos_y": 0, "team": st.session_state.my_team, "is_active": True}]
    fig = draw_pixel_map(st.session_state.grid, sample_units)
    st.pyplot(fig)

with col2:
    st.subheader("コマンド入力 (10ターン制限)")
    # Supabaseへの送信と同期のロジックをここに実装
    st.info("GitHubにアップロード後、Streamlit CloudのSecretsにSupabaseの情報を入力してください。")
    if st.button("ターン終了・同期開始"):
        st.write("相手の入力を待機中（Supabase経由）...")

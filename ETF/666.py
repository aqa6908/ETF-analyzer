import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

# --- 頁面設定 ---
st.set_page_config(page_title="ETF vs 0050 績效分析", page_icon="📈", layout="wide")

st.title("📈 ETF 相對績效分析系統")
st.markdown("將您關注的台股 ETF 與台灣 50 (0050) 進行**還原報酬率**對決。")

# --- 側邊欄 (輸入區) ---
with st.sidebar:
    st.header("⚙️ 設定參數")
    ticker_input = st.text_input("輸入 ETF 代號 (免填.TW)", value="0056")
    
    # 增加更多彈性的區間選項
    period_options = {
        "3mo": "近 3 個月", 
        "6mo": "近 6 個月", 
        "ytd": "今年以來 (YTD)", 
        "1y": "近 1 年", 
        "3y": "近 3 年", 
        "5y": "近 5 年", 
        "10y": "近 10 年",
        "max": "上市以來 (Max)"
    }
    period = st.selectbox("分析區間", options=list(period_options.keys()), index=3, 
                          format_func=lambda x: period_options[x])
                          
    # 增加資料頻率切換，解決短區間配月報會太少資料的問題
    interval_choice = st.radio("資料頻率 (影響圖表平滑度)", 
                               options=["日報 (Daily)", "週報 (Weekly)", "月報 (Monthly)"], 
                               index=2) # 預設維持月報

# --- 資料抓取邏輯 (加上 Cache 避免重複抓取浪費時間) ---
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_data(symbol, period):
    """取得還原收盤價，自動判斷上市(.TW)或上櫃(.TWO)"""
    
    # --- 新增：工程師自建的資料修復演算法 ---
    def clean_tw_stock_data(s):
        """修復 Yahoo API 遺漏的分割(Split)或減資造成的異常跳空"""
        prices = s.values.astype(float)
        for i in range(len(prices)-1, 0, -1):
            if prices[i-1] > 0 and pd.notna(prices[i]) and pd.notna(prices[i-1]):
                ratio = prices[i] / prices[i-1]
                # 台股單日漲跌幅極限為 10%。若單日變動超過 25%，判定為未還原的分割或減資
                if ratio < 0.75 or ratio > 1.25: 
                    # 將異常點之前的歷史價格全部按比例縮放，手動完成「還原」
                    prices[:i] = prices[:i] * ratio
        return pd.Series(prices, index=s.index, name=s.name)

    # 預設先試 .TW
    full_symbol = symbol if "." in symbol else f"{symbol}.TW"
    t = yf.Ticker(full_symbol)
    
    # 強制關閉 auto_adjust，確保我們能明確抓取到原始與還原欄位
    df = t.history(period=period, auto_adjust=False)
    
    # 如果找不到，且原本沒指定後綴，試試看上櫃 .TWO
    if df.empty and "." not in symbol:
        full_symbol = f"{symbol}.TWO"
        t = yf.Ticker(full_symbol)
        df = t.history(period=period, auto_adjust=False)
        
    if df.empty:
        return None, full_symbol
        
    # 移除時區資訊方便後續對齊
    df.index = df.index.tz_localize(None)
    
    # 強制優先取出 'Adj Close' (包含配息與分割的還原價)，若無才退回 'Close'
    if 'Adj Close' in df.columns:
        series = df['Adj Close']
    else:
        series = df['Close']
        
    # 套用自建的還原價修復演算法
    series = clean_tw_stock_data(series)
        
    series.name = full_symbol
    return pd.DataFrame(series), full_symbol

# --- 主程式邏輯 ---
if ticker_input:
    ticker = ticker_input.strip().upper()
    
    if not ticker:
        st.warning("請輸入代號")
    else:
        with st.spinner(f"正在撈取 {ticker} 與 0050 的最新數據..."):
            # 抓取目標 ETF 與 0050
            df_target, target_symbol = fetch_data(ticker, period)
            df_0050, _ = fetch_data("0050", period)
            
            if df_target is None:
                st.error(f"❌ 找不到代號 {ticker} 的資料，請確認是否輸入正確。")
            elif df_0050 is None:
                st.error("❌ 系統異常：無法取得 0050 基準資料。")
            else:
                # 1. 找尋雙方共同都有交易的日子 (內連接)
                df_merged = df_target.join(df_0050, how='inner')
                
                if df_merged.empty:
                    st.error("❌ 兩檔標的在該區間內沒有重疊的交易日資料。")
                else:
                    # ===== 依據使用者選擇動態調整資料頻率 =====
                    if "月報" in interval_choice:
                        df_merged = df_merged.resample('ME').last()
                        hover_format = "%Y-%m" # 滑鼠停靠時的日期格式
                        show_markers = True
                        bar_gap = 0.2
                        range_breaks = [] # 月報不需要隱藏週末
                    elif "週報" in interval_choice:
                        df_merged = df_merged.resample('W-FRI').last()
                        hover_format = "%Y-%m-%d" # 保留細節給滑鼠提示
                        show_markers = True
                        bar_gap = 0.1
                        range_breaks = []
                    else: # 日報
                        # 日資料不需 resample
                        hover_format = "%Y-%m-%d" # 保留細節給滑鼠提示
                        show_markers = False # 日資料點太多，隱藏圓點比較乾淨
                        bar_gap = 0.1 # 加入小間隙，避免柱子全部黏在一起
                        range_breaks = [dict(bounds=["sat", "mon"])] # 日資料需隱藏週末以避免空白
                        
                    # 動態調整 X 軸刻度間距，避免同月出現多個重複標籤
                    if period in ["3mo", "6mo", "ytd", "1y"]:
                        x_dtick = "M1"
                    elif period in ["3y", "5y"]:
                        x_dtick = "M3"
                    elif period == "10y":
                        x_dtick = "M6"
                    else:
                        x_dtick = "M12"
                        
                    df_merged.dropna(inplace=True) # 確保沒有因放假產生的空值
                    
                    col_target = df_merged.columns[0]
                    col_0050 = df_merged.columns[1]
                    
                    # 2. 以第一天為基準計算累積報酬率 (%)
                    base_target = df_merged[col_target].iloc[0]
                    base_0050 = df_merged[col_0050].iloc[0]
                    
                    df_merged['Return_Target'] = ((df_merged[col_target] / base_target) - 1) * 100
                    df_merged['Return_0050'] = ((df_merged[col_0050] / base_0050) - 1) * 100
                    
                    # 3. 計算超額報酬 (Alpha)
                    df_merged['Alpha'] = df_merged['Return_Target'] - df_merged['Return_0050']
                    
                    # --- 繪圖區 (使用 Plotly) ---
                    freq_title = interval_choice.split(" ")[0] # 擷取 日報/週報/月報 作為標題
                    st.subheader(f"📊 {target_symbol} vs 0050 累積還原報酬率走勢 ({freq_title})")
                    st.caption("💡 **互動提示**：在圖表上**按住拖曳**可放大局部細節，**點擊兩下**即可恢復完整全圖。")
                    
                    # 主圖：折線圖
                    fig_main = go.Figure()
                    fig_main.add_trace(go.Scatter(
                        x=df_merged.index, y=df_merged['Return_Target'],
                        mode='lines+markers' if show_markers else 'lines', 
                        name=f'{target_symbol}',
                        line=dict(color='#F54346', width=2.5), 
                        marker=dict(size=6) if show_markers else None,
                        fill='tozeroy', fillcolor='rgba(245, 67, 70, 0.1)'
                    ))
                    fig_main.add_trace(go.Scatter(
                        x=df_merged.index, y=df_merged['Return_0050'],
                        mode='lines+markers' if show_markers else 'lines', 
                        name='0050 (大盤基準)',
                        line=dict(color='#8E8E93', width=2),
                        marker=dict(size=5) if show_markers else None
                    ))
                    fig_main.update_layout(
                        hovermode='x unified',
                        plot_bgcolor='rgba(0,0,0,0)', 
                        paper_bgcolor='rgba(0,0,0,0)',
                        legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="left", x=0), # 將圖例移到左上方，看起來更整齊
                        yaxis=dict(
                            ticksuffix="%", 
                            gridcolor='#E5E5EA', 
                            zeroline=True, zerolinecolor='#D1D1D6'
                        ),
                        xaxis=dict(
                            showgrid=False,
                            tickformat="%Y-%m", # 軸標籤統一只顯示年月
                            hoverformat=hover_format, # 游標停靠時顯示的精準日期
                            dtick=x_dtick, # 強制間距
                            rangebreaks=range_breaks
                        ),
                        margin=dict(l=0, r=0, t=30, b=0), # 增加一點頂部空間給圖例
                        height=400
                    )
                    # 加入 config={'displayModeBar': False} 完全隱藏右上方英文工具列
                    st.plotly_chart(fig_main, use_container_width=True, config={'displayModeBar': False})
                    
                    st.divider()
                    
                    # 副圖：柱狀圖 (超額報酬)
                    st.subheader(f"⚖️ 打敗大盤幅度 (相對 0050 超額報酬 - {freq_title})")
                    st.caption("💡 **說明**：柱狀圖在 0 軸以上(紅色)代表累計領先 0050；在 0 軸以下(綠色)代表落後 0050。同樣支援**拖曳放大**與**點擊兩下恢復**。")
                    
                    # 台灣股市習慣：正值為紅，負值為綠
                    colors = ['#F54346' if val >= 0 else '#34C759' for val in df_merged['Alpha']]
                    
                    fig_sub = go.Figure()
                    fig_sub.add_trace(go.Bar(
                        x=df_merged.index, y=df_merged['Alpha'],
                        marker_color=colors, name='超額報酬',
                        marker_line_width=0, 
                        hovertemplate=f'%{{x|{hover_format}}}<br>幅度: %{{y:.2f}}%<extra></extra>' 
                    ))
                    fig_sub.update_layout(
                        hovermode='x unified',
                        plot_bgcolor='rgba(0,0,0,0)',
                        paper_bgcolor='rgba(0,0,0,0)',
                        yaxis=dict(
                            ticksuffix="%", 
                            gridcolor='#E5E5EA',
                            zeroline=True, zerolinecolor='#8E8E93', zerolinewidth=2
                        ),
                        xaxis=dict(
                            showgrid=False,
                            type='date',
                            tickformat="%Y-%m", # 軸標籤統一只顯示年月
                            dtick=x_dtick, # 強制間距
                            rangebreaks=range_breaks
                        ),
                        bargap=bar_gap, # 動態調整柱子間隙
                        margin=dict(l=0, r=0, t=10, b=0),
                        height=300
                    )
                    
                    # 同樣隱藏副圖的英文工具列
                    st.plotly_chart(fig_sub, use_container_width=True, config={'displayModeBar': False})
import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import numpy as np

# --- 頁面設定 ---
st.set_page_config(page_title="標的 vs 0050 績效分析", page_icon="📈", layout="wide")

st.title("📈 相對績效分析系統")
st.markdown("將您關注的台股標的與台灣 50 (0050) 進行**還原報酬率**對決。")

# --- 初始化 Session State (用於自動千分位) ---
if 'dca_amt_val' not in st.session_state:
    st.session_state.dca_amt_val = "3,000"
if 'lump_amt_val' not in st.session_state:
    st.session_state.lump_amt_val = "100,000"

def format_dca_amt():
    raw = st.session_state.dca_input_key.replace(",", "")
    if raw.isdigit():
        st.session_state.dca_amt_val = f"{int(raw):,}"

def format_lump_amt():
    raw = st.session_state.lump_input_key.replace(",", "")
    if raw.isdigit():
        st.session_state.lump_amt_val = f"{int(raw):,}"

# --- 資料抓取邏輯 (處理異常代號與資料斷層) ---
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_data(symbol, period):
    """取得還原收盤價，處理異常代號與資料斷層"""
    
    def clean_tw_stock_data(s):
        """修復 Yahoo API 遺漏的分割/減資跳空 (例如 0052)"""
        if s.empty: return s
        prices = s.values.astype(float)
        for i in range(len(prices)-1, 0, -1):
            if prices[i-1] > 0 and pd.notna(prices[i]) and pd.notna(prices[i-1]):
                ratio = prices[i] / prices[i-1]
                if ratio < 0.75 or ratio > 1.25: 
                    prices[:i] = prices[:i] * ratio
        return pd.Series(prices, index=s.index, name=s.name)

    ticker_str = symbol.strip().upper()
    full_symbol = ticker_str if "." in ticker_str else f"{ticker_str}.TW"
    
    try:
        t = yf.Ticker(full_symbol)
        df = t.history(period=period, auto_adjust=False)
        
        if df.empty and "." not in ticker_str:
            full_symbol = f"{ticker_str}.TWO"
            t = yf.Ticker(full_symbol)
            df = t.history(period=period, auto_adjust=False)
            
        if df.empty:
            return None, full_symbol, "NotFound"
            
        df.index = df.index.tz_localize(None)
        series = df['Adj Close'] if 'Adj Close' in df.columns else df['Close']
        series = clean_tw_stock_data(series)
        series.name = full_symbol
        return pd.DataFrame(series), full_symbol, "Success"

    except Exception as e:
        if "RateLimitError" in str(e) or "429" in str(e):
            return None, full_symbol, "RateLimit"
        return None, full_symbol, "Error"

# --- 側邊欄 (設定區) ---
with st.sidebar:
    st.header("⚙️ 設定參數")
    # 更新標籤：拿掉範例文字
    ticker_input = st.text_input("輸入代號", value="0056")
    
    period_options = {
        "3mo": "近 3 個月", "6mo": "近 6 個月", "ytd": "今年以來 (YTD)", 
        "1y": "近 1 年", "3y": "近 3 年", "5y": "近 5 年", 
        "10y": "近 10 年", "max": "上市以來 (Max)"
    }
    period = st.selectbox("分析區間", options=list(period_options.keys()), index=3, format_func=lambda x: period_options[x])
    interval_choice = st.radio("圖表資料頻率", options=["日報 (Daily)", "週報 (Weekly)", "月報 (Monthly)"], index=2)
    
    st.divider()
    
    st.header("💰 投資模式")
    invest_mode = st.radio("選擇模式", ["單筆投入 (Lump Sum)", "定期定額 (DCA)"], index=0)
    
    if invest_mode == "定期定額 (DCA)":
        st.text_input(
            "每期投入金額 (元)", 
            value=st.session_state.dca_amt_val, 
            key="dca_input_key", 
            on_change=format_dca_amt
        )
        amount_input = int(st.session_state.dca_amt_val.replace(",", ""))
        dca_times_per_month = st.selectbox("每月扣款次數", options=[1, 2, 3, 4, 5, 6], index=0)
    else:
        st.text_input(
            "初始投入金額 (元)", 
            value=st.session_state.lump_amt_val, 
            key="lump_input_key", 
            on_change=format_lump_amt
        )
        amount_input = int(st.session_state.lump_amt_val.replace(",", ""))

# --- 主程式區塊 ---
if ticker_input:
    ticker = ticker_input.strip().upper()
    with st.spinner(f"正在分析 {ticker}..."):
        df_target, target_symbol, status_target = fetch_data(ticker, period)
        df_0050, _, status_0050 = fetch_data("0050", period)
        
        if status_target == "NotFound":
            st.error(f"❌ 無此代號：查無 '{ticker}'。請確認輸入是否正確。")
        elif status_target == "RateLimit" or status_0050 == "RateLimit":
            st.error("⚠️ 系統繁忙：Yahoo Finance 暫時限制了您的連線。請稍等後再試。")
        elif df_target is None or df_0050 is None:
            st.error("❌ 讀取失敗：無法取得數據。")
        else:
            df_merged = df_target.join(df_0050, how='inner')
            
            if df_merged.empty:
                st.warning("⚠️ 查無重疊交易日。")
            else:
                col_t, col_50 = df_merged.columns[0], df_merged.columns[1]
                
                if invest_mode == "單筆投入 (Lump Sum)":
                    df_merged['Return_Target'] = ((df_merged[col_t] / df_merged[col_t].iloc[0]) - 1) * 100
                    df_merged['Return_0050'] = ((df_merged[col_50] / df_merged[col_50].iloc[0]) - 1) * 100
                    final_val_t = amount_input * (1 + df_merged['Return_Target'].iloc[-1] / 100)
                    final_val_50 = amount_input * (1 + df_merged['Return_0050'].iloc[-1] / 100)
                    total_cost = amount_input
                    title_suffix = "單筆累積報酬率"
                else:
                    amt_per_time = amount_input
                    step = max(1, int(20 / dca_times_per_month))
                    invest_dates = df_merged.iloc[::step].index
                    
                    for col, name in [(col_t, 'T'), (col_50, '50')]:
                        is_invest = df_merged.index.isin(invest_dates)
                        shares = np.where(is_invest, amt_per_time / df_merged[col], 0)
                        cum_shares = shares.cumsum()
                        total_value = cum_shares * df_merged[col]
                        cum_cost_series = pd.Series(is_invest * amt_per_time, index=df_merged.index).cumsum()
                        cum_cost = cum_cost_series.replace(0, np.nan)
                        
                        df_merged[f'Ret_{name}'] = ((total_value / cum_cost) - 1) * 100
                        df_merged[f'Val_{name}'] = total_value
                        df_merged['Final_Cost'] = cum_cost
                    
                    df_merged['Return_Target'] = df_merged['Ret_T']
                    df_merged['Return_0050'] = df_merged['Ret_50']
                    final_val_t = df_merged['Val_T'].iloc[-1]
                    final_val_50 = df_merged['Val_50'].iloc[-1]
                    total_cost = df_merged['Final_Cost'].iloc[-1]
                    title_suffix = "定期定額資產報酬率"

                df_merged['Alpha'] = df_merged['Return_Target'] - df_merged['Return_0050']
                
                # --- 數據總結顯示區 ---
                st.subheader("💰 實質績效結算")
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("總投入本金", f"${total_cost:,.0f}")
                m2.metric(f"{target_symbol} 最終價值", f"${final_val_t:,.0f}", f"{df_merged['Return_Target'].iloc[-1]:.2f}%")
                m3.metric("0050 最終價值", f"${final_val_50:,.0f}", f"{df_merged['Return_0050'].iloc[-1]:.2f}%")
                
                profit_diff = final_val_t - final_val_50
                diff_color = "normal" if profit_diff >= 0 else "inverse"
                m4.metric("相對損益差額", f"${profit_diff:,.0f}", f"{df_merged['Alpha'].iloc[-1]:.2f}%", delta_color=diff_color)

                # --- 繪圖區 ---
                if "月報" in interval_choice:
                    df_plot = df_merged.resample('ME').last()
                    x_fmt, show_m = "%Y-%m", True
                elif "週報" in interval_choice:
                    df_plot = df_merged.resample('W-FRI').last()
                    x_fmt, show_m = "%Y-%m-%d", True
                else:
                    df_plot = df_merged.copy()
                    x_fmt, show_m = "%Y-%m-%d", False
                
                df_plot.dropna(inplace=True)
                
                st.divider()
                st.subheader(f"📊 {target_symbol} vs 0050 {title_suffix}")
                
                fig_main = go.Figure()
                fig_main.add_trace(go.Scatter(x=df_plot.index, y=df_plot['Return_Target'], name=target_symbol, mode='lines', line=dict(color='#F54346', width=2.5), fill='tozeroy', fillcolor='rgba(245, 67, 70, 0.1)'))
                fig_main.add_trace(go.Scatter(x=df_plot.index, y=df_plot['Return_0050'], name='0050', line=dict(color='#8E8E93', width=2)))
                fig_main.update_layout(hovermode='x unified', plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', margin=dict(l=0, r=0, t=30, b=0), height=400, legend=dict(orientation="h", y=1.1))
                st.plotly_chart(fig_main, use_container_width=True, config={'displayModeBar': False})
                
                st.subheader("⚖️ 打敗大盤幅度 (超額報酬)")
                fig_sub = go.Figure(go.Bar(x=df_plot.index, y=df_plot['Alpha'], marker_color=['#F54346' if v >= 0 else '#34C759' for v in df_plot['Alpha']]))
                fig_sub.update_layout(hovermode='x unified', plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', height=300, margin=dict(l=0,r=0,t=10,b=0))
                st.plotly_chart(fig_sub, use_container_width=True, config={'displayModeBar': False})

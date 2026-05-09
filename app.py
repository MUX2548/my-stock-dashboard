import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

# 1. ตั้งค่าหน้าเพจ
st.set_page_config(page_title="ระบบวิเคราะห์หุ้นอัตโนมัติ", layout="wide")

# 🌟 บังคับตั้งค่าเป็นเวลาประเทศไทย (UTC+7) เสมอ
tz_th = timezone(timedelta(hours=7))
current_date = datetime.now(tz_th).strftime("%d/%m/%Y")
current_time = datetime.now(tz_th).strftime("%H:%M")

with st.sidebar:
    st.title("เมนูการใช้งาน")
    ticker = st.text_input("🔎 ใส่ชื่อหุ้น หรือ ดัชนี", value="NVTS").upper()
    st.markdown("---")
    st.markdown("💰 **พอร์ตส่วนตัว (Portfolio)**")
    buy_price = st.number_input("ใส่ราคาต้นทุนของคุณ (USD)", min_value=0.0, value=0.0, step=0.1)

@st.cache_data(ttl=300)
def load_data(ticker_symbol):
    try:
        stock = yf.Ticker(ticker_symbol)
        df = stock.history(period="6mo", interval="1d")
        if df.empty: return pd.DataFrame(), {}
            
        # คำนวณเทคนิคอลพื้นฐาน
        df['EMA_20'] = df['Close'].ewm(span=20, adjust=False).mean()
        df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()
        
        # RSI
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        df['RSI'] = 100 - (100 / (1 + gain/loss))
        
        # 🌟 ตีเส้นแนวโน้มอัตโนมัติ (Linear Regression Trendline)
        y = df['Close'].values
        x = np.arange(len(y))
        slope, intercept = np.polyfit(x, y, 1)
        df['Trendline'] = slope * x + intercept
        
        # ข้อมูลพื้นฐาน
        fund = {"ps": "N/A", "pe": "N/A", "roe": "N/A"}
        try:
            info = stock.info
            ps = info.get('priceToSalesTrailing12Months')
            pe = info.get('trailingPE')
            roe = info.get('returnOnEquity')
            if ps: fund["ps"] = round(ps, 2)
            if pe: fund["pe"] = round(pe, 2)
            if roe: fund["roe"] = round(roe * 100, 2)
        except: pass
            
        return df, fund
    except: return pd.DataFrame(), {}

df, fund = load_data(ticker)

# 🔮 Harmonic Momentum Matrix
def get_matrix(df):
    if df.empty: return None
    last = df['Close'].iloc[-1]
    vol = df['Close'].pct_change().tail(14).std()
    return {"l": last * (1 + vol*0.5), "u": last * (1 + vol*1.0), "trend": "ขึ้น 📈" if last > df['EMA_50'].iloc[-1] else "ลง 📉"}

matrix = get_matrix(df)

# ==========================================
# 6. จัด Layout หน้าจอหลัก
# ==========================================
st.markdown(f"## 📈 วิเคราะห์หุ้น: {ticker}")
st.caption(f"📅 ข้อมูลล่าสุด: {current_date} | {current_time} น.")

if not df.empty:
    # 🔮 Matrix สั้นๆ ด้านบน
    if matrix:
        st.info(f"🔮 **ทิศทางคืนนี้:** {matrix['trend']} | **เป้าหมาย:** {matrix['l']:,.2f} - {matrix['u']:,.2f} (คำนวณตาม Harmonic Matrix)")

    # 📊 กราฟขนาดใหญ่
    col_chart, col_plan = st.columns([7, 3])
    
    with col_chart:
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
        # แท่งเทียน
        fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name="Price"), row=1, col=1)
        # 🌟 เส้นตีแนวโน้ม (Trendline)
        fig.add_trace(go.Scatter(x=df.index, y=df['Trendline'], line=dict(color='rgba(255, 255, 255, 0.3)', dash='dot'), name="Trendline"), row=1, col=1)
        # EMA
        fig.add_trace(go.Scatter(x=df.index, y=df['EMA_20'], line=dict(color='#00E676', width=1.5), name="EMA 20"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['EMA_50'], line=dict(color='#FF6D00', width=1.5), name="EMA 50"), row=1, col=1)
        
        if buy_price > 0:
            fig.add_hline(y=buy_price, line_dash="dash", line_color="cyan", annotation_text="ต้นทุน", row=1, col=1)
            
        # RSI
        fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], line=dict(color='#BA68C8'), name="RSI"), row=2, col=1)
        fig.add_hline(y=70, line_dash="dot", line_color="red", row=2, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color="green", row=2, col=1)
        
        fig.update_layout(template="plotly_dark", height=500, margin=dict(l=0,r=0,t=0,b=0), showlegend=False)
        fig.update_xaxes(rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True)

    with col_plan:
        last_p = df['Close'].iloc[-1]
        change = last_p - df['Close'].iloc[-2]
        st.metric("ราคาปัจจุบัน", f"${last_p:,.2f}", f"{change:.2f}")
        
        if buy_price > 0:
            pl = ((last_p - buy_price) / buy_price) * 100
            st.write(f"**กำไร/ขาดทุน:** {pl:.2f}%")
            if pl > 0: st.success("✅ ถือต่อเพื่อรันกำไร")
            else: st.error("⚠️ ระวัง! กราฟเริ่มเสียทรง")
        
        st.markdown("---")
        st.subheader("🚧 โซนราคาสำคัญ")
        st.write(f"**แนวต้าน:** {df['High'].tail(20).max():.2f}")
        st.write(f"**แนวรับ:** {df['EMA_50'].iloc[-1]:.2f}")

    # 🌟 ย้ายมาไว้ใต้กราฟ: ข้อมูลพื้นฐาน (Fundamental Analysis)
    st.markdown("---")
    st.subheader("📊 ข้อมูลพื้นฐาน (Fundamental Analysis)")
    f1, f2, f3 = st.columns(3)
    with f1:
        st.metric("P/S Ratio", fund['ps'])
        st.caption("ราคาเทียบรายได้ (<3 = ถูก)")
    with f2:
        st.metric("P/E Ratio", fund['pe'])
        st.caption("จุดคืนทุน (N/A = ยังไม่มีกำไร)")
    with f3:
        roe_display = f"{fund['roe']}%" if fund['roe'] != "N/A" else "N/A"
        st.metric("ROE", roe_display)
        st.caption("ความเก่งบริหาร (>15% = ดี)")
    
    st.info("💡 **หมายเหตุ:** ค่า N/A จะปรากฏในกรณีที่เป็นดัชนี (Index) หรือบริษัทที่ยังไม่มีกำไร ซึ่งถือเป็นเรื่องปกติของหุ้นเติบโตเร็วค่ะ")

else:
    st.warning("ไม่พบข้อมูล กรุณาตรวจสอบชื่อหุ้นอีกครั้ง หรือรอระบบรีเฟรชสักครู่ค่ะ")

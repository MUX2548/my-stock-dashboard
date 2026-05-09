import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

# 1. ตั้งค่าหน้าเพจ
st.set_page_config(page_title="ระบบวิเคราะห์หุ้นอัตโนมัติ", layout="wide")

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
        
        # เคลียร์ข้อมูลที่แหว่ง (NaN) ป้องกันกราฟพัง
        df = df.dropna(subset=['Close']) 
            
        df['EMA_10'] = df['Close'].ewm(span=10, adjust=False).mean()
        df['EMA_20'] = df['Close'].ewm(span=20, adjust=False).mean()
        df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()
        
        ema_12 = df['Close'].ewm(span=12, adjust=False).mean()
        ema_26 = df['Close'].ewm(span=26, adjust=False).mean()
        macd = ema_12 - ema_26
        signal = macd.ewm(span=9, adjust=False).mean()
        df['MACD'] = macd
        df['Signal'] = signal
        df['MACD_Hist'] = macd - signal
        
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        df['RSI'] = 100 - (100 / (1 + gain/loss))
        
        # Trendline
        if len(df) > 1:
            y = df['Close'].values
            x = np.arange(len(y))
            slope, intercept = np.polyfit(x, y, 1)
            df['Trendline'] = slope * x + intercept
        else:
            df['Trendline'] = np.nan
        
        fund = {"ps": "N/A", "pe": "N/A", "roe": "N/A"}
        try:
            info = stock.info
            ps = info.get('priceToSalesTrailing12Months')
            pe = info.get('trailingPE')
            roe = info.get('returnOnEquity')
            if ps: fund["ps"] = f"{ps:.2f}"
            if pe: fund["pe"] = f"{pe:.2f}"
            if roe: fund["roe"] = f"{roe * 100:.2f}%"
        except: pass
            
        return df, fund
    except: return pd.DataFrame(), {}

df, fund = load_data(ticker)

# ==========================================
# 🌟 ฟังก์ชัน: The Harmonic Momentum Matrix
# ==========================================
def get_matrix(df):
    if df.empty or len(df) < 14: return None
    last = df['Close'].iloc[-1]
    vol = df['Close'].pct_change().tail(14).std()
    return {"l": last * (1 - vol*1.0) if last < df['EMA_50'].iloc[-1] else last * (1 + vol*0.5), 
            "u": last * (1 - vol*0.5) if last < df['EMA_50'].iloc[-1] else last * (1 + vol*1.0), 
            "trend": "ขึ้น 📈" if last > df['EMA_50'].iloc[-1] else "ลง 📉"}

matrix = get_matrix(df)

# ==========================================
# 🌟 ฟังก์ชัน: คำแนะนำภาพรวม (ที่หายไป เอากลับมาแล้ว!)
# ==========================================
def auto_analyze(df):
    if df.empty: return ""
    last_close = df['Close'].iloc[-1]
    ema10 = df['EMA_10'].iloc[-1]
    ema20 = df['EMA_20'].iloc[-1] 
    ema50 = df['EMA_50'].iloc[-1]
    recent_high = df['High'].tail(20).max()

    if last_close > ema50: 
        trend = "ขาขึ้น 📈 🟢"
        buy_zone = f"โซน {ema10:.2f} ถึง {ema20:.2f} 🔴"
        hold_zone = f"ถ้าราคายืนเหนือ {ema20:.2f} (หนีที่ {ema50:.2f})"
    else: 
        trend = "ขาลง 📉 🔴"
        buy_zone = "ยังไม่แนะนำ (รอสัญญาณกลับตัว) ⚠️"
        hold_zone = f"ระวัง! หลุด Low ควรคัททิ้ง 🟡"
        
    sell_zone = f"โซน {recent_high:.2f} ขึ้นไป 🟡"
    return f"**📈 แนวโน้ม:** {trend}\n\n**🟢 ซื้อ:** {buy_zone}\n\n**🔴 ขาย:** {sell_zone}\n\n**🟡 ถือต่อ:** {hold_zone}"

if not df.empty:
    action_short = auto_analyze(df)
else:
    action_short = ""

# ==========================================
# 6. จัด Layout หน้าจอหลัก
# ==========================================
st.markdown(f"## 📈 วิเคราะห์หุ้น: {ticker}")
st.caption(f"📅 ข้อมูลล่าสุด: {current_date} | {current_time} น.")

if not df.empty:
    if matrix:
        st.info(f"🔮 **ทิศทางคืนนี้:** {matrix['trend']} | **เป้าหมาย:** {matrix['l']:,.2f} - {matrix['u']:,.2f} (Harmonic Matrix)")

    col_chart, col_plan = st.columns([7, 3])
    
    with col_chart:
        fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.5, 0.25, 0.25])
        
        fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name="Price"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['Trendline'], line=dict(color='rgba(255, 255, 255, 0.3)', dash='dot'), name="Trendline"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['EMA_20'], line=dict(color='#00E676', width=1.5), name="EMA 20"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['EMA_50'], line=dict(color='#FF6D00', width=1.5), name="EMA 50"), row=1, col=1)
        
        if buy_price > 0:
            fig.add_hline(y=buy_price, line_dash="dash", line_color="cyan", annotation_text="ต้นทุน", row=1, col=1)
            
        # แท่ง Volume
        colors = ['#00E676' if df['Close'].iloc[i] > df['Open'].iloc[i] else '#FF6D00' for i in range(len(df))]
        fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=colors, name="Volume"), row=2, col=1)
        
        # RSI
        fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], line=dict(color='#BA68C8'), name="RSI"), row=3, col=1)
        fig.add_hline(y=70, line_dash="dot", line_color="red", row=3, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color="green", row=3, col=1)
        
        fig.update_layout(template="plotly_dark", height=650, margin=dict(l=0,r=0,t=0,b=0), showlegend=False)
        fig.update_xaxes(rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True)

    with col_plan:
        last_p = df['Close'].iloc[-1]
        change = last_p - df['Close'].iloc[-2] if len(df) > 1 else 0
        st.metric("ราคาปัจจุบัน", f"${last_p:,.2f}", f"{change:.2f}")
        
        if buy_price > 0:
            pl = ((last_p - buy_price) / buy_price) * 100
            st.write(f"**กำไร/ขาดทุน:** {pl:.2f}%")
            if pl > 0: st.success("✅ ถือต่อเพื่อรันกำไร")
            else: st.error("⚠️ ระวัง! กราฟเริ่มเสียทรง")
        
        # 🌟 กล่องคำแนะนำภาพรวมที่นำกลับมา 🌟
        st.markdown("---")
        st.subheader("💡 คำแนะนำภาพรวม")
        st.success(action_short)
        
        st.markdown("---")
        st.subheader("🚧 โซนราคาสำคัญ")
        st.write(f"**แนวต้าน:** {df['High'].tail(20).max():.2f}")
        st.write(f"**แนวรับ:** {df['EMA_50'].iloc[-1]:.2f}")

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
        st.metric("ROE", fund['roe'])
        st.caption("ความเก่งบริหาร (>15% = ดี)")
    
    st.info("💡 **ทริค:** เซียนหุ้นจะดูแท่ง Volume ควบคู่ไปด้วย หากราคาทะลุแนวต้านพร้อม Volume สีเขียวสูงปรี๊ด แสดงว่าเป็นขาขึ้นของจริงค่ะ!")

else:
    st.warning("ไม่พบข้อมูล หรือกราฟอาจอยู่ระหว่างปรับฐานข้อมูล กรุณาลองหุ้นตัวอื่นค่ะ")

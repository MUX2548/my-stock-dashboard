import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

# 1. ตั้งค่าหน้าเพจ
st.set_page_config(page_title="ระบบวิเคราะห์หุ้นอัตโนมัติ", layout="wide")

# 🌟 บังคับตั้งค่าเป็นเวลาประเทศไทย (UTC+7)
tz_th = timezone(timedelta(hours=7))
current_date = datetime.now(tz_th).strftime("%d/%m/%Y")
current_time = datetime.now(tz_th).strftime("%H:%M")

with st.sidebar:
    st.title("เมนูการใช้งาน")
    ticker = st.text_input("🔎 ใส่ชื่อหุ้น หรือ ดัชนี", value="NVTS").upper()
    st.markdown("---")
    st.markdown("💰 **พอร์ตส่วนตัว**")
    buy_price = st.number_input("ราคาต้นทุน (USD)", min_value=0.0, value=0.0, step=0.1)

@st.cache_data(ttl=300)
def load_data(ticker_symbol):
    try:
        stock = yf.Ticker(ticker_symbol)
        df = stock.history(period="6mo", interval="1d")
        if df.empty: return pd.DataFrame(), {}
            
        # คำนวณ Indicators
        df['EMA_10'] = df['Close'].ewm(span=10, adjust=False).mean()
        df['EMA_20'] = df['Close'].ewm(span=20, adjust=False).mean()
        df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()
        ema_12 = df['Close'].ewm(span=12, adjust=False).mean()
        ema_26 = df['Close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = ema_12 - ema_26
        df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['MACD_Hist'] = df['MACD'] - df['Signal']
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        df['RSI'] = 100 - (100 / (1 + gain/loss))
        df['Daily_Return'] = df['Close'].pct_change()
        
        # 🌟 ดึงข้อมูลพื้นฐานแบบละเอียด
        info_data = {}
        try:
            raw_info = stock.info
            info_data = {
                "ps_ratio": raw_info.get('priceToSalesTrailing12Months', 'N/A'),
                "mkt_cap": raw_info.get('marketCap', 'N/A'),
                "pe_ratio": raw_info.get('trailingPE', 'N/A'),
                "div_yield": raw_info.get('dividendYield', 0),
                "52w_high": raw_info.get('fiftyTwoWeekHigh', 'N/A'),
                "name": raw_info.get('longName', ticker_symbol)
            }
        except: pass
            
        return df, info_data
    except: return pd.DataFrame(), {}

df, info = load_data(ticker)

# ==========================================
# 🔮 The Harmonic Momentum Matrix Model
# ==========================================
def quantum_model(df):
    if df.empty or len(df) < 20: return None
    last_price = df['Close'].iloc[-1]
    vol = df['Daily_Return'].tail(14).std()
    target_l = last_price * (1 + (vol * 0.5))
    target_u = last_price * (1 + (vol * 1.0))
    trend = "ขาขึ้น 📈" if last_price > df['EMA_50'].iloc[-1] else "ขาลง 📉"
    return {"trend": trend, "l": target_l, "u": target_u, "price": last_price}

matrix = quantum_model(df)

# ==========================================
# 6. จัด Layout หน้าจอหลัก
# ==========================================
st.markdown(f"## 📊 {info.get('name', ticker)}")
st.caption(f"📅 ข้อมูลอัปเดตล่าสุด: {current_date} | {current_time} น. (เวลาไทย)")

# 🌟 ส่วนที่ 1: ข้อมูลพื้นฐาน & การแจ้งเตือน (สวยงาม)
if not df.empty:
    st.markdown("---")
    f_col1, f_col2, f_col3, f_col4 = st.columns(4)
    
    # คำนวณ RSI ปัจจุบันเพื่อใช้แจ้งเตือน
    current_rsi = df['RSI'].iloc[-1]
    ps_val = info.get('ps_ratio', 'N/A')

    with f_col1:
        st.metric("P/S Ratio", f"{ps_val}")
    with f_col2:
        pe_val = info.get('pe_ratio', 'N/A')
        st.metric("P/E Ratio", f"{pe_val}")
    with f_col3:
        mkt_cap = info.get('mkt_cap', 0)
        st.metric("Market Cap", f"${mkt_cap/1e9:.2f}B" if isinstance(mkt_cap, (int, float)) else "N/A")
    with f_col4:
        div = info.get('div_yield', 0)
        st.metric("Dividend Yield", f"{div*100:.2f}%" if div else "0.00%")

    # ⚠️ ระบบแจ้งเตือนข้อควรระวัง (Alert System)
    st.markdown("#### 🚨 จุดที่ต้องระวังและข้อสังเกต")
    alert_cols = st.columns(3)
    
    with alert_cols[0]:
        if current_rsi >= 70:
            st.error(f"⚠️ RSI: {current_rsi:.2f} (Overbought) ระวังการย่อตัวรุนแรง!")
        elif current_rsi <= 30:
            st.success(f"💡 RSI: {current_rsi:.2f} (Oversold) โซนราคาถูก มีโอกาสรีบาวด์")
        else:
            st.info(f"✅ RSI: {current_rsi:.2f} (Neutral) อยู่ในระดับปกติ")

    with alert_cols[1]:
        if isinstance(ps_val, (int, float)) and ps_val > 20:
            st.warning(f"⚠️ P/S Ratio สูง ({ps_val}): ราคาหุ้นอาจแพงเกินรายได้ไปมาก")
        else:
            st.success("✅ Valuation: ระดับราคาเทียบรายได้ยังสมเหตุสมผล")

    with alert_cols[2]:
        last_price = df['Close'].iloc[-1]
        ema50 = df['EMA_50'].iloc[-1]
        if last_price < ema50:
            st.error("⚠️ Trend: ราคาหลุดเส้น EMA 50 เสี่ยงเป็นขาลงยาว")
        else:
            st.success("✅ Trend: ราคายืนเหนือ EMA 50 แนวโน้มหลักยังดี")

# 🔮 ส่วน Harmonic Matrix
if matrix:
    st.markdown("---")
    st.info(f"🔮 **ทิศทางคืนนี้ (Harmonic Matrix):** {matrix['trend']} | **เป้าหมาย:** {matrix['l']:,.2f} - {matrix['u']:,.2f}")

# กราฟ
if not df.empty:
    st.markdown("---")
    c1, c2 = st.columns([7, 3])
    
    with c1:
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
        fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name="ราคา"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['EMA_20'], line=dict(color='#00E676', width=1.5), name="EMA 20"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['EMA_50'], line=dict(color='#FF6D00', width=1.5), name="EMA 50"), row=1, col=1)
        if buy_price > 0:
            fig.add_hline(y=buy_price, line_dash="dash", line_color="white", annotation_text="ต้นทุนของคุณ", row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], line=dict(color='#BA68C8'), name="RSI"), row=2, col=1)
        fig.update_layout(template="plotly_dark", height=600, margin=dict(l=0,r=0,t=0,b=0), showlegend=False)
        fig.update_xaxes(rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True)

    with c2:
        last_p = df['Close'].iloc[-1]
        change = last_p - df['Close'].iloc[-2]
        st.metric("ราคาปัจจุบัน", f"${last_p:,.2f}", f"{change:.2f}")
        
        if buy_price > 0:
            pl = ((last_p - buy_price) / buy_price) * 100
            st.write(f"**กำไร/ขาดทุน:** {pl:.2f}%")
            if pl > 0: st.success("ถือรันเทรนด์ต่อได้")
            else: st.error("พิจารณาจุดตัดขาดทุน")
else:
    st.warning("กรุณากรอกชื่อหุ้นที่ถูกต้อง หรือรอระบบรีเฟรชข้อมูลสักครู่ครับ")

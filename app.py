import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

# 1. ตั้งค่าหน้าเพจแบบ Wide Screen
st.set_page_config(page_title="Strategic Portfolio Ecosystem 2.0", layout="wide")

# ==========================================
# 🔐 ระบบสถานะการเข้าสู่ระบบ (Login State)
# ==========================================
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

# ตั้งค่าเวลาไทย
tz_th = timezone(timedelta(hours=7))
current_date = datetime.now(tz_th).strftime("%d/%m/%Y")
current_time = datetime.now(tz_th).strftime("%H:%M")

# --- แถบเมนูด้านซ้าย (Sidebar) ---
with st.sidebar:
    st.title("🛡️ Strategic Hub")
    ticker = st.text_input("🔎 ชื่อหุ้น / ดัชนี", value="NVTS").upper()
    
    st.markdown("---")
    st.subheader("⏱️ ช่วงเวลาวิเคราะห์")
    tf_option = st.radio("เลือกความละเอียด:", ["1D (รายวัน)", "1W (รายสัปดาห์)", "1M (รายเดือน)"], index=0)
    st.markdown("---")
    
    # 🌟 โหมดคนทั่วไป (Guest) vs โหมดเจ้าของพอร์ต (Owner)
    if not st.session_state["logged_in"]:
        st.subheader("🔒 สำหรับเจ้าของพอร์ต")
        st.caption("เข้าสู่ระบบเพื่อปลดล็อคเครื่องมือจัดการเงินทุนและพอร์ตส่วนตัว")
        pwd = st.text_input("🔑 รหัสผ่าน", type="password")
        if st.button("เข้าสู่ระบบ (Login)", use_container_width=True):
            # ดึงรหัสผ่านจากตู้เซฟ ถ้ายังไม่ได้ตั้งในเว็บ จะใช้ 123456 เป็นค่าเริ่มต้น
            correct_pwd = st.secrets.get("app_password", "123456")
            if pwd == correct_pwd:
                st.session_state["logged_in"] = True
                st.rerun()
            else:
                st.error("❌ รหัสผ่านไม่ถูกต้อง")
        
        # กำหนดค่าเริ่มต้นเป็น 0 สำหรับคนทั่วไปเพื่อไม่ให้ระบบ Error
        total_capital = 0.0
        risk_pct = 2.0
        buy_price = 0.0

    else:
        # 🌟 เมนูที่จะเห็นเฉพาะคุณเท่านั้น
        st.subheader("🧮 จัดการความเสี่ยง (Risk Mgmt)")
        total_capital = st.number_input("เงินทุนรวม (USD)", min_value=0.0, value=10000.0, step=100.0)
        risk_pct = st.slider("ความเสี่ยงต่อไม้ (%)", 1.0, 5.0, 2.0)
        
        st.markdown("---")
        st.subheader("💰 สถานะพอร์ตปัจจุบัน")
        buy_price = st.number_input("ราคาต้นทุน (USD)", min_value=0.0, value=0.0, step=0.1)
        
        st.markdown("---")
        if st.button("🚪 ออกจากระบบ (Logout)", use_container_width=True):
            st.session_state["logged_in"] = False
            st.rerun()

# --- ฟังก์ชันดึงข้อมูลแบบ Pro ---
@st.cache_data(ttl=300)
def load_pro_data(ticker_symbol, tf):
    settings = {
        "1D (รายวัน)": {"period": "6mo", "interval": "1d"},
        "1W (รายสัปดาห์)": {"period": "2y", "interval": "1wk"},
        "1M (รายเดือน)": {"period": "5y", "interval": "1mo"}
    }
    p, i = settings[tf]["period"], settings[tf]["interval"]
    
    try:
        stock = yf.Ticker(ticker_symbol)
        df = stock.history(period=p, interval=i)
        if df.empty: return pd.DataFrame(), {}
        df = df.dropna(subset=['Close'])
        
        spy = yf.Ticker("^GSPC").history(period=p, interval=i)['Close']
        df['RS_vs_Market'] = (df['Close'].pct_change(10) - spy.pct_change(10)) * 100
        
        df['EMA_10'] = df['Close'].ewm(span=10, adjust=False).mean()
        df['EMA_20'] = df['Close'].ewm(span=20, adjust=False).mean()
        df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()
        
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        df['RSI'] = 100 - (100 / (1 + gain/loss))
        
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
            
            if ps is not None: fund["ps"] = f"{ps:.2f}"
            if pe is not None: fund["pe"] = f"{pe:.2f}"
            if roe is not None: fund["roe"] = f"{roe * 100:.2f}%"
        except: pass
        
        return df, fund
    except: return pd.DataFrame(), {}

df, fund = load_pro_data(ticker, tf_option)

# ==========================================
# 🌟 ระบบซ่อนแท็บ (แสดง 1 แท็บสำหรับคนทั่วไป / 3 แท็บสำหรับคุณ)
# ==========================================
if st.session_state["logged_in"]:
    tab_dash, tab_port, tab_strat = st.tabs(["📊 วิเคราะห์กราฟ (Analysis)", "💼 ตัวติดตามพอร์ต (Portfolio)", "📚 กลยุทธ์ & คู่มือ (Strategy)"])
else:
    tab_dash, = st.tabs(["📊 วิเคราะห์กราฟ (Analysis)"])

# ==========================================
# หน้าวิเคราะห์หลัก (Dashboard) - ทุกคนเห็นได้
# ==========================================
with tab_dash:
    if not df.empty:
        last_p = df['Close'].iloc[-1]
        
        rs_val = df['RS_vs_Market'].iloc[-1]
        if not np.isnan(rs_val):
            rs_color = "🟢 ชนะตลาด" if rs_val > 0 else "🔴 อ่อนแอว่าตลาด"
            st.info(f"🔮 **Harmonic Matrix:** {tf_option} | **Relative Strength:** {rs_color} ({rs_val:.2f}%)")

        col_left, col_right = st.columns([7, 3])
        
        with col_left:
            fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.5, 0.25, 0.25])
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name="Price"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['Trendline'], line=dict(color='rgba(255, 255, 255, 0.4)', dash='dot', width=2), name="Trend"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['EMA_20'], line=dict(color='#00E676', width=2.5), name="EMA 20"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['EMA_50'], line=dict(color='#FF6D00', width=2.5), name="EMA 50"), row=1, col=1)
            
            if buy_price > 0 and st.session_state["logged_in"]: 
                fig.add_hline(y=buy_price, line_dash="dash", line_color="cyan", line_width=2, annotation_text="ต้นทุน", row=1, col=1)
            
            v_colors = ['#00E676' if df['Close'].iloc[i] > df['Open'].iloc[i] else '#FF6D00' for i in range(len(df))]
            fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=v_colors, name="Vol"), row=2, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], line=dict(color='#BA68C8', width=2), name="RSI"), row=3, col=1)
            fig.add_hline(y=70, line_dash="dot", line_color="red", row=3, col=1)
            fig.add_hline(y=30, line_dash="dot", line_color="green", row=3, col=1)
            
            fig.update_layout(template="plotly_dark", height=600, margin=dict(l=0,r=0,t=0,b=0), showlegend=False)
            fig.update_xaxes(rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)
            
            st.markdown("---")
            f1, f2, f3 = st.columns(3)
            with f1: st.metric("P/S Ratio", fund.get('ps', 'N/A'))
            with f2: st.metric("P/E Ratio", fund.get('pe', 'N/A'))
            with f3: st.metric("ROE", fund.get('roe', 'N/A'))

        with col_right:
            prev_p = df['Close'].iloc[-2] if len(df) > 1 else last_p
            st.metric("ราคาปัจจุบัน", f"${last_p:,.2f}", f"{last_p - prev_p:.2f}")
            st.caption(f"🕒 อัปเดต: {df.index[-1].strftime('%d/%m/%Y')} | {current_time} น.")
            
            # 🌟 แสดงกล่องคำนวณเงินเฉพาะตอนล็อคอินเท่านั้น
            if st.session_state["logged_in"]:
                sl_price = df['EMA_50'].iloc[-1] * 0.99 if buy_price == 0 else buy_price * 0.92
                st.error(f"🛡️ **จุดหนี (Stop Loss): ${sl_price:.2f}**")
                
                risk_amt = total_capital * (risk_pct / 100)
                risk_per_share = last_p - sl_price
                if risk_per_share > 0:
                    shares = risk_amt / risk_per_share
                    st.success(f"🧮 **ซื้อได้:** {shares:.2f} หุ้น\n\n(ใช้เงิน: ${(shares * last_p):,.2f})")
            
            st.markdown("---")
            st.subheader("💡 คำแนะนำภาพรวม")
            if last_p > df['EMA_50'].iloc[-1]:
                st.success(f"**แนวโน้ม:** ขาขึ้น 📈\n\n**ซื้อ:** {df['EMA_10'].iloc[-1]:.2f} - {df['EMA_20'].iloc[-1]:.2f}\n\n**ขาย:** {df['High'].tail(20).max():.2f}")
            else:
                st.error("**แนวโน้ม:** ขาลง 📉\n\nระวัง! ไม่แนะนำให้รับของ (รอสร้างฐาน)")
            
            st.markdown("---")
            st.subheader("🚧 แนวรับ-ต้าน")
            st.write(f"**ต้าน:** {df['High'].tail(20).max():.2f}")
            st.write(f"**รับ:** {df['EMA_50'].iloc[-1]:.2f}")

# ==========================================
# แท็บที่ซ่อนไว้ (แสดงเฉพาะตอนล็อคอินเท่านั้น)
# ==========================================
if st.session_state["logged_in"]:
    with tab_port:
        st.subheader("💼 สรุปสถานะพอร์ตโฟลิโอ")
        if buy_price > 0:
            p_col1, p_col2, p_col3 = st.columns(3)
            pl_pct = ((last_p - buy_price) / buy_price) * 100
            p_col1.metric("มูลค่าปัจจุบัน", f"${last_p:,.2f}")
            p_col2.metric("ต้นทุนที่ซื้อ", f"${buy_price:,.2f}")
            p_col3.metric("กำไร/ขาดทุน (%)", f"{pl_pct:.2f}%", delta=f"{pl_pct:.2f}%")
            
            if pl_pct > 0: st.balloons()
        else:
            st.info("กรุณากรอกราคาต้นทุนที่แถบเมนูด้านซ้าย เพื่อเริ่มติดตามผลกำไรค่ะ")

    with tab_strat:
        st.subheader("📚 คู่มือกลยุทธ์การลงทุน (Pro Strategy)")
        st.markdown("""
        ### 1. กฎการเทรดแบบ Top-Down Analysis
        - **เช็กรายเดือน (1M):** เพื่อดูว่าหุ้นอยู่ในวัฏจักรขาขึ้นรอบใหญ่หรือไม่
        - **เช็กรายสัปดาห์ (1W):** เพื่อหาแนวรับ-แนวต้านที่แข็งแกร่ง
        - **เช็กรายวัน (1D):** เพื่อหาจุดเข้าซื้อที่ได้เปรียบ (Entry Point)
        
        ### 2. การจัดการความเสี่ยง (Risk Management)
        - **กฎ 2%:** อย่าให้การขาดทุนในแต่ละไม้ เกิน 2% ของเงินต้นทั้งหมด
        - **Relative Strength:** เน้นลงทุนในหุ้นที่ **ชนะตลาด (สีเขียว)** เพราะเวลาตลาดขึ้น หุ้นพวกนี้จะพุ่งแรงกว่า
        """)

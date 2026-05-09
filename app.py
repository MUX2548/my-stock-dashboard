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
    ticker = st.text_input("🔎 ชื่อหุ้น / ดัชนี (วิเคราะห์กราฟ)", value="NVTS").upper()
    
    st.markdown("---")
    st.subheader("⏱️ ช่วงเวลาวิเคราะห์")
    tf_option = st.radio("เลือกความละเอียด:", ["1D (รายวัน)", "1W (รายสัปดาห์)", "1M (รายเดือน)"], index=0)
    st.markdown("---")
    
    if not st.session_state["logged_in"]:
        st.subheader("🔒 สำหรับเจ้าของพอร์ต")
        st.caption("เข้าสู่ระบบเพื่อปลดล็อคเครื่องมือจัดการพอร์ตส่วนตัว")
        pwd = st.text_input("🔑 รหัสผ่าน", type="password")
        if st.button("เข้าสู่ระบบ (Login)", use_container_width=True):
            correct_pwd = st.secrets.get("app_password", "123456")
            if pwd == correct_pwd:
                st.session_state["logged_in"] = True
                st.rerun()
            else:
                st.error("❌ รหัสผ่านไม่ถูกต้อง")
        
        total_capital = 0.0
        risk_pct = 2.0
        buy_price = 0.0

    else:
        st.subheader("🧮 จัดการความเสี่ยง (Risk Mgmt)")
        total_capital = st.number_input("เงินทุนรวม (USD)", min_value=0.0, value=10000.0, step=100.0)
        risk_pct = st.slider("ความเสี่ยงต่อไม้ (%)", 1.0, 5.0, 2.0)
        
        st.markdown("---")
        st.subheader("💰 ต้นทุนหุ้นตัวนี้")
        st.caption("ใช้คำนวณจุดหนีในหน้าวิเคราะห์กราฟ")
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
# 🌟 ระบบแท็บ
# ==========================================
if st.session_state["logged_in"]:
    tab_dash, tab_port, tab_strat = st.tabs(["📊 วิเคราะห์กราฟ (Analysis)", "💼 ตัวติดตามพอร์ต (Portfolio)", "📚 กลยุทธ์ & คู่มือ (Strategy)"])
else:
    tab_dash, = st.tabs(["📊 วิเคราะห์กราฟ (Analysis)"])

# --- หน้าวิเคราะห์หลัก ---
with tab_dash:
    if not df.empty:
        last_p = df['Close'].iloc[-1]
        rs_val = df['RS_vs_Market'].iloc[-1]
        if not np.isnan(rs_val):
            rs_color = "🟢 ชนะตลาด" if rs_val > 0 else "🔴 อ่อนแอกว่าตลาด"
            st.info(f"🔮 **Harmonic Matrix:** {tf_option} | **Relative Strength:** {rs_color} ({rs_val:.2f}%)")

        col_left, col_right = st.columns([7, 3])
        with col_left:
            fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.5, 0.25, 0.25])
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name="Price"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['EMA_20'], line=dict(color='#00E676', width=2.5), name="EMA 20"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['EMA_50'], line=dict(color='#FF6D00', width=2.5), name="EMA 50"), row=1, col=1)
            if buy_price > 0: fig.add_hline(y=buy_price, line_dash="dash", line_color="cyan", annotation_text="ต้นทุน")
            
            fig.add_trace(go.Bar(x=df.index, y=df['Volume'], name="Vol"), row=2, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], line=dict(color='#BA68C8'), name="RSI"), row=3, col=1)
            fig.update_layout(template="plotly_dark", height=600, margin=dict(l=0,r=0,t=0,b=0), showlegend=False)
            fig.update_xaxes(rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)

# ==========================================
# 🌟 แท็บพอร์ตโฟลิโอ: ตรวจสอบราคาปัจจุบันรายตัว
# ==========================================
if st.session_state["logged_in"]:
    with tab_port:
        st.subheader("💼 ตัวติดตามพอร์ต (Real-time Multi-Stock Tracker)")
        
        # ตารางข้อมูลพอร์ต
        if "port_data" not in st.session_state:
            st.session_state.port_data = pd.DataFrame({"Ticker": ["NVTS"], "Cost_Price": [16.48], "Shares": [100.0]})

        edited_df = st.data_editor(st.session_state.port_data, num_rows="dynamic", use_container_width=True)
        st.session_state.port_data = edited_df

        if st.button("🔄 อัปเดตราคาปัจจุบันทุกตัวในพอร์ต", type="primary", use_container_width=True):
            tickers = edited_df["Ticker"].dropna().unique().tolist()
            if tickers:
                with st.spinner("กำลังดึงข้อมูลราคาล่าสุดจากตลาด..."):
                    current_prices = {}
                    for t in tickers:
                        try:
                            # ดึงราคาปัจจุบันรายตัว
                            price = yf.Ticker(t).history(period="1d")['Close'].iloc[-1]
                            current_prices[t] = price
                        except: pass

                    results = []
                    total_v = 0
                    total_c = 0
                    for _, row in edited_df.iterrows():
                        t, cost, sh = row["Ticker"], row["Cost_Price"], row["Shares"]
                        if t in current_prices:
                            curr_p = current_prices[t]
                            val = curr_p * sh
                            cst = cost * sh
                            results.append({"หุ้น": t, "ราคาปัจจุบัน": f"${curr_p:,.2f}", "ต้นทุน": f"${cost:,.2f}", "กำไร/ขาดทุน": f"${(val-cst):,.2f}", "%": f"{((val-cst)/cst*100):.2f}%", "มูลค่ารวม": f"${val:,.2f}"})
                            total_v += val
                            total_c += cst

                    st.markdown("---")
                    p1, p2, p3 = st.columns(3)
                    p1.metric("มูลค่ารวมปัจจุบัน", f"${total_v:,.2f}")
                    p2.metric("เงินต้นทั้งหมด", f"${total_c:,.2f}")
                    p3.metric("กำไร/ขาดทุนรวม", f"${(total_v-total_c):,.2f}", f"{((total_v-total_c)/total_c*100 if total_c>0 else 0):.2f}%")
                    st.dataframe(pd.DataFrame(results), use_container_width=True)
            else: st.warning("กรุณากรอกชื่อหุ้นในตารางก่อนค่ะ")

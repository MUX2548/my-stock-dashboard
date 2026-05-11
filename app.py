import json
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

# 1. ตั้งค่าหน้าเพจ
st.set_page_config(page_title="Strategic Portfolio Ecosystem 4.2", page_icon="📈", layout="wide")

# 🎨 2. ตกแต่ง UI/UX
st.markdown("""
    <style>
    .stButton>button {
        border-radius: 12px;
        font-weight: bold;
        transition: all 0.3s ease;
        border: 1px solid #4CAF50;
    }
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 15px rgba(76, 175, 80, 0.4);
        border-color: #4CAF50;
    }
    .stButton>button[data-baseweb="button"] {
        border-radius: 12px;
    }
    .summary-box {
        padding: 20px;
        border-radius: 10px;
        margin-bottom: 20px;
        border-left: 5px solid;
    }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 🔐 การเชื่อมต่อฐานข้อมูล
# ==========================================
@st.cache_resource
def init_connection():
    creds_dict = json.loads(st.secrets["google_creds_json"])
    sheet_url = st.secrets["spreadsheet_url"]
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc = gspread.authorize(credentials)
    return gc.open_by_url(sheet_url)

try:
    sh = init_connection()
except Exception as e:
    st.error(f"⚠️ ไม่สามารถเชื่อมต่อฐานข้อมูลได้: {e}")
    st.stop()

def clean_df_types(df):
    df_clean = df.copy()
    num_cols = ["Price", "Shares", "Amount_USD", "Running_Balance", "FX_Rate", "WHT_USD"]
    str_cols = ["Date", "Action", "Ticker", "Ref_Doc"]
    for col in num_cols:
        if col in df_clean.columns:
            df_clean[col] = pd.to_numeric(df_clean[col], errors='coerce').fillna(0.0)
    for col in str_cols:
        if col in df_clean.columns:
            df_clean[col] = df_clean[col].fillna("").astype(str).replace(["None", "nan", "<NA>", "NaN"], "")
    return df_clean

def load_ledger_data():
    try:
        ws = sh.worksheet("Ledger")
        records = ws.get_all_records()
        if not records:
            df = pd.DataFrame(columns=["Date", "Action", "Ticker", "Price", "Shares", "Amount_USD", "Running_Balance", "FX_Rate", "WHT_USD", "Ref_Doc"])
            return clean_df_types(df)
        df = pd.DataFrame(records)
        df.replace(["", "None", "nan", None], np.nan, inplace=True)
        df.dropna(how="all", inplace=True)
    except:
        df = pd.DataFrame()

    req_cols = ["Date", "Action", "Ticker", "Price", "Shares", "Amount_USD", "Running_Balance", "FX_Rate", "WHT_USD", "Ref_Doc"]
    for col in req_cols:
        if col not in df.columns: df[col] = ""

    df = clean_df_types(df)
    if not df.empty and "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], format="%d/%m/%Y", errors="coerce").dt.strftime("%d/%m/%Y").replace("NaT", "")
    return df[req_cols]

def save_df_to_sheet(worksheet_name, df):
    ws = sh.worksheet(worksheet_name)
    ws.clear()
    clean_df = clean_df_types(df)
    data_list = [clean_df.columns.values.tolist()] + clean_df.values.tolist()
    ws.update(values=data_list, range_name='A1')

if "trade_ledger" not in st.session_state:
    st.session_state.trade_ledger = load_ledger_data()

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

tz_th = timezone(timedelta(hours=7))
current_date = datetime.now(tz_th).strftime("%d/%m/%Y")
current_time = datetime.now(tz_th).strftime("%H:%M")

def calculate_stats(df_input):
    df = clean_df_types(df_input)
    cb = 0.0
    stat = {"outward": 0.0, "inward": 0.0, "bought": 0.0, "sold": 0.0, "dividend": 0.0, "realized_profit": 0.0}
    r_bals, hld = [], {}
    
    for idx, row in df.iterrows():
        action = str(row.get("Action", "")).strip()
        ticker = str(row.get("Ticker", "")).strip().upper()
        p, s, a = row.get("Price", 0.0), row.get("Shares", 0.0), row.get("Amount_USD", 0.0)
        val = p * s
        
        if action == "นำเงินออกนอกประเทศ (Outward)": cb += a; stat["outward"] += a
        elif action == "นำเงินเข้าประเทศไทย (Inward)": cb -= a; stat["inward"] += a
        elif action == "รับเงินปันผล (Dividend)": cb += a; stat["dividend"] += a
        elif action == "ซื้อหุ้น (Buy)" and ticker:
            cb -= val; stat["bought"] += val
            if ticker not in hld: hld[ticker] = {"shares": 0.0, "total_cost": 0.0}
            hld[ticker]["shares"] += s; hld[ticker]["total_cost"] += val
        elif action == "ขายหุ้น (Sell)" and ticker:
            cb += val; stat["sold"] += val
            if ticker in hld and hld[ticker]["shares"] > 0:
                avg = hld[ticker]["total_cost"] / hld[ticker]["shares"]
                stat["realized_profit"] += val - (avg * s)
                hld[ticker]["shares"] -= s; hld[ticker]["total_cost"] -= (avg * s)
        r_bals.append(cb)
    return cb, stat, r_bals, hld

@st.cache_data
def convert_df_to_csv(df):
    return df.to_csv(index=False).encode('utf-8-sig')

# ==========================================
# 🌟 Sidebar
# ==========================================
with st.sidebar:
    st.title("🛡️ Strategic Hub")
    ticker = st.text_input("🔎 ชื่อหุ้น / ดัชนี", value="NVTS").upper()
    tf_option = st.radio("เลือกความละเอียด:", ["1D (รายวัน)", "1W (รายสัปดาห์)", "1M (รายเดือน)"], index=0)
    
    st.markdown("---")
    st.subheader("🧮 เครื่องมือคำนวณ (Public)")
    t_cap = st.number_input("เงินทุนรวม (USD)", value=10000.0)
    r_pct = st.slider("ความเสี่ยงต่อไม้ (%)", 1.0, 5.0, 2.0)
    b_p = st.number_input("ราคาต้นทุนที่ซื้อ (USD)", min_value=0.0, step=0.1)
    
    st.markdown("---")
    if not st.session_state["logged_in"]:
        pwd = st.text_input("🔑 รหัสผ่าน (สำหรับเจ้าของ)", type="password")
        if st.button("🔓 เข้าสู่ระบบ", use_container_width=True, type="primary"):
            if pwd == st.secrets.get("app_password", "123456"):
                st.session_state["logged_in"] = True
                st.rerun()
            else: st.error("❌ รหัสผ่านไม่ถูกต้อง")
    else:
        st.success("✅ โหมดเจ้าของพอร์ต")
        if st.button("🚪 ออกจากระบบ", use_container_width=True):
            st.session_state["logged_in"] = False
            st.rerun()

# --- ดึงข้อมูลวิเคราะห์ ---
@st.cache_data(ttl=300)
def load_pro_data(ticker_symbol, tf):
    stgs = {"1D (รายวัน)": {"p": "6mo", "i": "1d"}, "1W (รายสัปดาห์)": {"p": "2y", "i": "1wk"}, "1M (รายเดือน)": {"p": "5y", "i": "1mo"}}
    p, i = stgs[tf]["p"], stgs[tf]["i"]
    try:
        s = yf.Ticker(ticker_symbol)
        df = s.history(period=p, interval=i)
        if df is None or df.empty: return pd.DataFrame(), {}, None, None
        df = df.dropna(subset=['Close'])
        if df.empty: return pd.DataFrame(), {}, None, None
        
        spy = yf.Ticker("^GSPC").history(period=p, interval=i)
        spy_trend = "N/A"
        spy_price = 0.0
        if not spy.empty:
            df['RS'] = (df['Close'].pct_change(10) - spy['Close'].pct_change(10)) * 100
            spy_price = spy['Close'].iloc[-1]
            spy_ema50 = spy['Close'].ewm(span=50).mean().iloc[-1]
            spy_trend = "ขึ้น 📈" if spy_price > spy_ema50 else "ลง 📉"
        else: df['RS'] = 0

        try:
            vix = yf.Ticker("^VIX").history(period=p, interval=i)
            vix_val = vix['Close'].iloc[-1] if not vix.empty else 20.0
        except: vix_val = 20.0

        market_signal = {"spy_trend": spy_trend, "spy_price": spy_price, "vix": vix_val}

        df['E20'] = df['Close'].ewm(span=20).mean()
        df['E50'] = df['Close'].ewm(span=50).mean()
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14).mean()
        df['RSI'] = 100 - (100 / (1 + gain/loss))
        df['MACD'] = df['Close'].ewm(span=12).mean() - df['Close'].ewm(span=26).mean()
        df['Sig'] = df['MACD'].ewm(span=9).mean()
        df['Hist'] = df['MACD'] - df['Sig']
        df['Vol_SMA'] = df['Volume'].rolling(window=20).mean()
        
        if len(df) > 1:
            y = df['Close'].values
            x = np.arange(len(y))
            slope, intercept = np.polyfit(x, y, 1)
            df['Trendline'] = slope * x + intercept
        else: df['Trendline'] = np.nan
        
        info = s.info
        fund = {"ps": f"{info.get('priceToSalesTrailing12Months', 0):.2f}", "pe": f"{info.get('trailingPE', 0):.2f}", "roe": f"{info.get('returnOnEquity', 0)*100:.2f}%"}
        
        last = df['Close'].iloc[-1]
        v = df['Close'].pct_change().tail(14).std()
        tr = "ขึ้น 📈" if last > df['E50'].iloc[-1] else "ลง 📉"
        mat = {"l": last * (1 - v*1.0) if tr == "ลง 📉" else last * (1 - v*0.5), "u": last * (1 - v*0.5) if tr == "ลง 📉" else last * (1 + v*1.0), "tr": tr}
        
        return df, fund, mat, market_signal
    except: return pd.DataFrame(), {}, None, None

df, fund, matrix, market_signal = load_pro_data(ticker, tf_option)

tabs = ["📊 วิเคราะห์กราฟ (Analysis)", "💼 บัญชี (Cloud Sync)", "🧾 ภาษีสรรพากร"] if st.session_state["logged_in"] else ["📊 วิเคราะห์กราฟ (Analysis)"]
tab_list = st.tabs(tabs)

# ==========================================
# หน้า 1: วิเคราะห์กราฟ
# ==========================================
with tab_list[0]:
    st.markdown(f"## 📈 วิเคราะห์หุ้น: {ticker}")
    st.caption(f"📅 ข้อมูลวิเคราะห์ ณ วันที่: {current_date} | 🕒 อัปเดตล่าสุด: {current_time} น.")
    
    if not df.empty:
        last_p = df['Close'].iloc[-1]
        prev_p = df['Close'].iloc[-2] if len(df) > 1 else last_p
        
        # 🌟 1. เรดาร์สแกนตลาด
        if market_signal:
            st.markdown("---")
            st.markdown("### 🌐 Market Signal (เรดาร์สแกนภาพรวมตลาด)")
            m1, m2, m3 = st.columns(3)
            spy_t = market_signal["spy_trend"]
            spy_p = market_signal["spy_price"]
            m1.metric("ตลาดโลก (S&P 500)", f"{spy_p:,.2f} จุด", f"{spy_t} (กระแสน้ำ{'ผลักดัน' if 'ขึ้น' in spy_t else 'กดดัน'})", delta_color="normal" if "ขึ้น" in spy_t else "inverse")
            
            v_val = market_signal["vix"]
            if v_val < 20: v_stat, v_col = "🟢 คนกล้าซื้อ (Risk ON)", "normal"
            elif v_val < 30: v_stat, v_col = "🟡 เฝ้าระวัง (Neutral)", "off"
            else: v_stat, v_col = "🔴 ตื่นตระหนก (Risk OFF)", "inverse"
            m2.metric("ดัชนีความกลัว (VIX Index)", f"{v_val:.2f}", v_stat, delta_color=v_col)
            m2.caption("💡 **VIX ยิ่งต่ำ = ตลาดปลอดภัย / VIX ยิ่งสูง = ตลาดผันผวนเทขาย**")
            
            with m3:
                if "ขึ้น" in spy_t and v_val < 25: st.success("✅ **ตลาดเป็นใจ:** สภาพแวดล้อมปลอดภัย เอื้อต่อการเข้าทำกำไร")
                elif "ลง" in spy_t and v_val > 25: st.error("🚨 **ความเสี่ยงสูง:** ตลาดกำลังผันผวนรุนแรง คุมความเสี่ยงด่วน")
                else: st.warning("⚠️ **ตลาดไร้ทิศทาง:** ตลาดยังเลือกทางไม่ได้ แนะนำเก็งกำไรในกรอบ")

        # 🌟 2. กล่อง AI สรุปกลยุทธ์การลงทุน (Executive Summary)
        rs_val = df['RS'].iloc[-1]
        stock_is_uptrend = last_p > df['E50'].iloc[-1]
        market_is_good = "ขึ้น" in market_signal["spy_trend"] and market_signal["vix"] < 25
        market_is_bad = "ลง" in market_signal["spy_trend"] and market_signal["vix"] > 25

        st.markdown("### 🤖 AI Executive Summary (สรุปแผนการลงทุน)")
        if market_is_good and stock_is_uptrend:
            st.success(f"**🌟 กลยุทธ์ (Action Plan): ทยอยสะสม / รันเทรนด์**\n\n**'น้ำขึ้น และเรือวิ่งฉลุย'** - สภาพตลาดโลกเป็นใจ และกราฟของหุ้น {ticker} เป็นขาขึ้นชัดเจน ถือเป็นจังหวะที่ดีในการถือครอง (Hold) หรือหาจังหวะย่อซื้อสะสมเพิ่มค่ะ")
        elif market_is_bad and not stock_is_uptrend:
            st.error(f"**🚨 กลยุทธ์ (Action Plan): หลีกเลี่ยง / รอดูสถานการณ์**\n\n**'พายุเข้า และเรือกำลังรั่ว'** - ตลาดรวมผันผวนหนัก และหุ้น {ticker} ก็เป็นขาลงอ่อนแอกว่าตลาด แนะนำให้หลีกเลี่ยงการลงทุนในตอนนี้ หรือถ้ามีของอยู่ควรพิจารณาตัดขาดทุน (Stop Loss) ค่ะ")
        elif market_is_good and not stock_is_uptrend:
            st.warning(f"**⚠️ กลยุทธ์ (Action Plan): Wait & See (รอดูอาการ)**\n\n**'น้ำขึ้น แต่เรือเครื่องดับ'** - ถึงแม้ตลาดรวมจะดี แต่หุ้น {ticker} กำลังเป็นขาลง แนะนำให้รอดูจนกว่ากราฟจะกลับตัวทะลุเส้นแนวต้านได้ หรือเปลี่ยนไปเล่นตัวอื่นที่กราฟสวยกว่าค่ะ")
        elif market_is_bad and stock_is_uptrend:
            st.info(f"**🛡️ กลยุทธ์ (Action Plan): ถืออย่างระมัดระวัง (Cautious Hold)**\n\n**'คลื่นลมแรง แต่เรือแกร่ง'** - หุ้น {ticker} แข็งแกร่งสวนทางตลาดที่กำลังแย่ สามารถถือได้แต่ต้องตั้งจุดหนี (Stop Loss) ไว้ให้ชัดเจน เพื่อป้องกันแรงเทขายตกใจจากตลาดรวมค่ะ")
        else:
            st.info(f"**🔍 กลยุทธ์ (Action Plan): เก็งกำไรระยะสั้น / ไซด์เวย์**\n\nตลาดและหุ้น {ticker} อยู่ในสภาวะก้ำกึ่ง (Sideway) แนะนำให้ซื้อที่แนวรับ-ขายที่แนวต้าน หรือรอดูทิศทางที่ชัดเจนก่อนเข้าซื้อไม้ใหญ่ค่ะ")

        st.markdown("---")
        rs_t = f" | **Relative Strength:** {'🟢 ชนะตลาด' if rs_val > 0 else '🔴 อ่อนแอกว่าตลาด'} ({rs_val:.2f}%)" if not np.isnan(rs_val) else ""
        if matrix: st.info(f"🔮 **ทิศทาง {tf_option}:** {matrix['tr']} | **เป้าหมาย:** {matrix['l']:,.2f} - {matrix['u']:,.2f} (Harmonic Matrix){rs_t}")
        
        c_l, c_r = st.columns([7, 3])
        with c_l:
            fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.45, 0.15, 0.2, 0.2])
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name="Price"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['Trendline'], line=dict(color='rgba(255, 255, 255, 0.4)', dash='dot', width=2), name="Trend"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['E20'], line=dict(color='#00E676', width=2.5), name="EMA 20"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['E50'], line=dict(color='#FF6D00', width=2.5), name="EMA 50"), row=1, col=1)
            if b_p > 0: fig.add_hline(y=b_p, line_dash="dash", line_color="cyan", annotation_text="ต้นทุน", row=1, col=1)
            
            v_c = ['#00E676' if df['Close'].iloc[i] > df['Open'].iloc[i] else '#FF5252' for i in range(len(df))]
            fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=v_c, name="Vol"), row=2, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['Vol_SMA'], line=dict(color='rgba(255, 255, 255, 0.5)', width=1.5), name="Vol Avg"), row=2, col=1)
            
            fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], line=dict(color='#BA68C8', width=2), name="RSI"), row=3, col=1)
            fig.add_hline(y=70, line_dash="dot", line_color="red", row=3, col=1)
            fig.add_hline(y=30, line_dash="dot", line_color="green", row=3, col=1)
            
            fig.add_trace(go.Bar(x=df.index, y=df['Hist'], marker_color=['#00E676' if v >= 0 else '#FF5252' for v in df['Hist']], name="MACD Hist"), row=4, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['MACD'], line=dict(color='#2962FF', width=2), name="MACD"), row=4, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['Sig'], line=dict(color='#FF6D00', width=2), name="Signal"), row=4, col=1)

            fig.update_layout(template="plotly_dark", height=800, margin=dict(l=0,r=0,t=0,b=0), showlegend=False)
            fig.update_xaxes(rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)
            
            st.subheader("📊 ข้อมูลพื้นฐาน (Fundamental)")
            f1, f2, f3 = st.columns(3); f1.metric("P/S Ratio", fund.get('ps','N/A')); f2.metric("P/E Ratio", fund.get('pe','N/A')); f3.metric("ROE", fund.get('roe','N/A'))
        
        with c_r:
            st.metric("ราคาปัจจุบัน", f"${last_p:,.2f}", f"{last_p - prev_p:.2f}")
            
            if b_p > 0:
                pl = ((last_p - b_p) / b_p) * 100
                st.write(f"**กำไร/ขาดทุนของคุณ:** {pl:.2f}%")
                sl = df['E50'].iloc[-1] * 0.99 if b_p == 0 else b_p * 0.92
                st.error(f"🛡️ **จุดหนี (Stop Loss): ${sl:.2f}**")
                ra = t_cap * (r_pct / 100); rps = last_p - sl
                if rps > 0: st.success(f"🧮 **ซื้อได้สูงสุด:** {ra/rps:.2f} หุ้น")
            
            st.markdown("---")
            st.subheader("🤖 สรุปสัญญาณเทคนิค")
            tr_s = "🟢 ขาขึ้น" if last_p > df['E50'].iloc[-1] else "🔴 ขาลง"
            mc_s = "🟢 แรงซื้อได้เปรียบ" if df['MACD'].iloc[-1] > df['Sig'].iloc[-1] else "🔴 แรงขายกดดัน"
            rs_val = df['RSI'].iloc[-1]
            rsi_s = "🔴 ซื้อมากไป" if rs_val > 70 else "🟢 ขายมากไป" if rs_val < 30 else "🟡 กลางๆ"
            
            st.write(f"**เทรนด์ (EMA 50):** {tr_s}")
            st.write(f"**รอบสวิง (MACD):** {mc_s}")
            st.write(f"**แรงซื้อขาย (RSI):** {rsi_s}")
            
            st.markdown("---")
            st.subheader("🚧 แนวรับ-ต้าน")
            st.write(f"**ต้าน:** {df['High'].tail(20).max():.2f}")
            st.write(f"**รับ:** {df['E50'].iloc[-1]:.2f}")
    else:
        st.warning(f"⚠️ ไม่สามารถดึงข้อมูลกราฟของหุ้น **'{ticker}'** ได้ในขณะนี้ค่ะ")

    st.markdown("---")
    with st.expander("⭐ ประเมินความแม่นยำของระบบวิเคราะห์"):
        with st.form("feedback_form", clear_on_submit=True):
            st.write(f"คุณมีความคิดเห็นอย่างไรกับการวิเคราะห์กราฟของหุ้น **{ticker}** ในครั้งนี้?")
            rating = st.slider("ระดับความแม่นยำและประโยชน์ที่ได้รับ (1 = แย่, 5 = แม่นยำ/มีประโยชน์มาก)", 1, 5, 5)
            comment = st.text_area("ข้อเสนอแนะเพิ่มเติม (Optional):")
            
            if st.form_submit_button("ส่งฟีดแบ็ก (Submit)"):
                try:
                    fb_ws = sh.worksheet("Feedback")
                    timestamp = datetime.now(tz_th).strftime("%d/%m/%Y %H:%M:%S")
                    fb_ws.append_row([timestamp, ticker, rating, comment])
                    st.success("🙏 ขอบคุณสำหรับฟีดแบ็กค่ะ!")
                except Exception as e:
                    st.error("⚠️ ไม่สามารถส่งข้อมูลได้ กรุณาตรวจสอบว่าสร้างชีต 'Feedback' แล้วหรือยังคะ")

if st.session_state["logged_in"]:
    cb, l_stat, r_bals, holdings = calculate_stats(st.session_state.trade_ledger)
    st.session_state.trade_ledger["Running_Balance"] = r_bals

    # ==========================================
    # หน้า 2: บัญชีและพอร์ตโฟลิโอ
    # ==========================================
    with tab_list[1]:
        st.subheader("💼 แดชบอร์ดกระแสเงินสด (Cashflow Overview)")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("📤 นำเงินออกสะสม (ลงทุน)", f"${l_stat['outward']:,.2f}")
        col2.metric("📥 นำเงินกลับไทย (ถอน)", f"${l_stat['inward']:,.2f}")
        col3.metric("📈 ต้นทุนหุ้นในพอร์ตรวม", f"${l_stat['bought'] - l_stat['sold']:,.2f}")
        col4.metric("💰 เงินสดคงเหลือ (พร้อมเทรด)", f"${cb:,.2f}", "💵 Cash Balance")
        
        st.markdown("---")
        h1, h2 = st.columns([8, 2])
        h1.subheader("📝 สมุดบันทึกบัญชีการเทรด (Cloud Ledger)")
        csv_ledger = convert_df_to_csv(st.session_state.trade_ledger)
        h2.download_button(label="📥 โหลดข้อมูล (Excel/CSV)", data=csv_ledger, file_name=f"Trade_Ledger_{current_date.replace('/','-')}.csv", mime='text/csv', use_container_width=True)
        
        st.info("💡 **วิธีลบข้อมูลตาราง:** กดเลือก ⬜ หน้าแถวที่ต้องการลบ (มุมซ้ายสุด) แล้วกดไอคอน 🗑️ มุมขวาบนของตาราง หรือกดปุ่ม Delete บนคีย์บอร์ดได้เลยค่ะ")
        
        ed_l = st.data_editor(st.session_state.trade_ledger, num_rows="dynamic", use_container_width=True,
            column_config={
                "Date": "วันที่ (DD/MM/YYYY)",
                "Action": st.column_config.SelectboxColumn("ประเภท", options=["นำเงินออกนอกประเทศ (Outward)", "นำเงินเข้าประเทศไทย (Inward)", "ซื้อหุ้น (Buy)", "ขายหุ้น (Sell)", "รับเงินปันผล (Dividend)"]),
                "Ticker": "ชื่อหุ้น",
                "Price": st.column_config.NumberColumn("ราคา ($)", format="%.4f"),
                "Shares": st.column_config.NumberColumn("จำนวนหุ้น", format="%.4f"),
                "Amount_USD": st.column_config.NumberColumn("จำนวนเงิน ($)", format="%.2f"),
                "Running_Balance": st.column_config.NumberColumn("ยอดยกมา ($)", disabled=True, format="%.2f"), 
                "FX_Rate": None, "WHT_USD": None, "Ref_Doc": None
            })
            
        if not ed_l.equals(st.session_state.trade_ledger):
            ed_l = clean_df_types(ed_l)
            _, _, n_rb, _ = calculate_stats(ed_l)
            ed_l["Running_Balance"] = n_rb
            st.session_state.trade_ledger = ed_l
            st.rerun()
            
        if st.button("💾 บันทึกข้อมูลบัญชีขึ้น Cloud", type="primary", use_container_width=True):
            save_df_to_sheet("Ledger", st.session_state.trade_ledger)
            st.success("บันทึกสำเร็จ! ข้อมูลปลอดภัย 100%")

        st.markdown("---")
        st.subheader("📊 พอร์ตโฟลิโอปัจจุบัน (Visual Holdings)")
        
        port_summary, total_invested = [], 0.0
        for t, data in holdings.items():
            if data["shares"] > 0.001:
                avg_c = data["total_cost"] / data["shares"]
                port_summary.append({"Ticker": t, "Cost_Price": avg_c, "Shares": data["shares"], "Total_Cost": data["total_cost"]})
                total_invested += data["total_cost"]
        
        if len(port_summary) > 0:
            current_port_df = pd.DataFrame(port_summary)
            
            if st.button("🔄 ดึงราคาล่าสุด & คำนวณกำไร/ขาดทุน (Mark to Market)", type="primary", use_container_width=True):
                with st.spinner("กำลังดึงราคาแบบเรียลไทม์..."):
                    results, total_v = [], 0.0
                    for _, row in current_port_df.iterrows():
                        t, avg_cost, sh, t_cost = row["Ticker"], row["Cost_Price"], row["Shares"], row["Total_Cost"]
                        try: curr_p = yf.Ticker(t).history(period="1d")['Close'].iloc[-1]
                        except: curr_p = avg_cost
                        
                        val = curr_p * sh
                        profit = val - t_cost
                        profit_pct = (profit / t_cost * 100) if t_cost > 0 else 0
                        results.append({
                            "หุ้น": t, "จำนวนหุ้น": sh, "ต้นทุนเฉลี่ย": avg_cost, 
                            "ราคาปัจจุบัน": curr_p, "กำไร/ขาดทุน": profit, 
                            "% เปลี่ยนแปลง": profit_pct, "มูลค่ารวม": val
                        })
                        total_v += val
                    
                    p1, p2, p3 = st.columns(3)
                    p1.metric("มูลค่าหุ้นรวม (Market Value)", f"${total_v:,.2f}")
                    p2.metric("ต้นทุนหุ้นทั้งหมด (Total Cost)", f"${total_invested:,.2f}")
                    p3.metric("กำไร/ขาดทุนรวม (Unrealized P/L)", f"${(total_v-total_invested):,.2f}", f"{((total_v-total_invested)/total_invested*100 if total_invested>0 else 0):.2f}%")
                    
                    res_df = pd.DataFrame(results)
                    chart_col1, chart_col2 = st.columns(2)
                    with chart_col1:
                        fig_pie = go.Figure(data=[go.Pie(labels=res_df['หุ้น'], values=res_df['มูลค่ารวม'], hole=.4)])
                        fig_pie.update_layout(title="สัดส่วนพอร์ต (Allocation)", template="plotly_dark", height=350, margin=dict(t=50, b=0, l=0, r=0))
                        st.plotly_chart(fig_pie, use_container_width=True)
                    with chart_col2:
                        bar_colors = ['#00E676' if val >= 0 else '#FF5252' for val in res_df['กำไร/ขาดทุน']]
                        fig_bar = go.Figure(data=[go.Bar(x=res_df['หุ้น'], y=res_df['กำไร/ขาดทุน'], marker_color=bar_colors)])
                        fig_bar.update_layout(title="กำไร/ขาดทุนรายตัว (P/L)", template="plotly_dark", height=350, margin=dict(t=50, b=0, l=0, r=0))
                        st.plotly_chart(fig_bar, use_container_width=True)

                    def color_profit(val):
                        return f'color: {"#FF5252" if val < 0 else "#00E676"}; font-weight: bold;'
                    
                    styled_res = res_df.style.map(color_profit, subset=["กำไร/ขาดทุน", "% เปลี่ยนแปลง"]).format({
                        "จำนวนหุ้น": "{:,.4f}", "ต้นทุนเฉลี่ย": "${:,.4f}", "ราคาปัจจุบัน": "${:,.4f}",
                        "กำไร/ขาดทุน": "${:,.2f}", "% เปลี่ยนแปลง": "{:,.2f}%", "มูลค่ารวม": "${:,.2f}"
                    })
                    st.dataframe(styled_res, use_container_width=True)
                    
                    csv_port = convert_df_to_csv(res_df)
                    st.download_button(label="📥 ดาวน์โหลดพอร์ตโฟลิโอ (Excel/CSV)", data=csv_port, file_name=f"Portfolio_{current_date.replace('/','-')}.csv", mime='text/csv')
        else:
            st.info("ว่างเปล่า (ยังไม่มีหุ้นในพอร์ตค่ะ)")

    # ==========================================
    # หน้า 3: ภาษีสรรพากร
    # ==========================================
    with tab_list[2]:
        t1, t2 = st.columns([8, 2])
        t1.subheader("🧾 ระบบประเมินภาษีสรรพากร ภ.ง.ด. 90")
        
        tax_idx = st.session_state.trade_ledger['Action'].isin(["นำเงินออกนอกประเทศ (Outward)", "นำเงินเข้าประเทศไทย (Inward)", "รับเงินปันผล (Dividend)"])
        tax_v = st.session_state.trade_ledger[tax_idx].copy()
        
        tax_v["Out_USD"] = np.where(tax_v["Action"] == "นำเงินออกนอกประเทศ (Outward)", tax_v["Amount_USD"], 0.0)
        tax_v["In_USD"] = np.where(tax_v["Action"].isin(["นำเงินเข้าประเทศไทย (Inward)", "รับเงินปันผล (Dividend)"]), tax_v["Amount_USD"], 0.0)
        
        tax_v["FX_Rate"] = pd.to_numeric(tax_v["FX_Rate"], errors='coerce').fillna(0.0)
        tax_v["WHT_USD"] = pd.to_numeric(tax_v["WHT_USD"], errors='coerce').fillna(0.0)
        
        tax_v["Out_THB"] = tax_v["Out_USD"] * tax_v["FX_Rate"]
        tax_v["In_THB"] = tax_v["In_USD"] * tax_v["FX_Rate"]
        
        t_bals, c_t_bal = [], 0.0
        for i, r in tax_v.iterrows():
            c_t_bal += (r["Out_THB"] - r["In_THB"])
            t_bals.append(c_t_bal)
        tax_v["Balance_THB"] = t_bals

        csv_tax = convert_df_to_csv(tax_v)
        t2.download_button(label="📥 โหลดตารางภาษี (Excel/CSV)", data=csv_tax, file_name=f"Tax_Report_{current_date.replace('/','-')}.csv", mime='text/csv', use_container_width=True)

        ed_t = st.data_editor(tax_v, use_container_width=True, num_rows="fixed",
            column_order=["Date", "Out_USD", "In_USD", "FX_Rate", "Out_THB", "In_THB", "Balance_THB", "WHT_USD", "Ref_Doc"],
            column_config={"Date": st.column_config.Column("วันที่", disabled=True), "Out_USD": st.column_config.NumberColumn("โอนออก ($)", disabled=True), "In_USD": st.column_config.NumberColumn("นำเข้า ($)", disabled=True),
                           "FX_Rate": st.column_config.NumberColumn("เรทเงิน (บาท/$)", format="%.4f"), "Out_THB": st.column_config.NumberColumn("โอนออก (฿)", disabled=True), "In_THB": st.column_config.NumberColumn("นำเข้า (฿)", disabled=True),
                           "WHT_USD": st.column_config.NumberColumn("ภาษีหัก ตปท. ($)", format="%.2f"), "Balance_THB": st.column_config.NumberColumn("เงินต้นคงเหลือ (฿)", disabled=True), "Ref_Doc": "หมายเหตุ"})
        
        if not ed_t[["FX_Rate", "WHT_USD", "Ref_Doc"]].equals(tax_v[["FX_Rate", "WHT_USD", "Ref_Doc"]]):
            ed_t = clean_df_types(ed_t)
            st.session_state.trade_ledger.loc[tax_idx, "FX_Rate"] = ed_t["FX_Rate"].values
            st.session_state.trade_ledger.loc[tax_idx, "WHT_USD"] = ed_t["WHT_USD"].values
            st.session_state.trade_ledger.loc[tax_idx, "Ref_Doc"] = ed_t["Ref_Doc"].values
            st.rerun()

        if st.button("💾 บันทึกอัตราแลกเปลี่ยนลง Cloud", type="primary", use_container_width=True):
            save_df_to_sheet("Ledger", st.session_state.trade_ledger); st.success("บันทึกสำเร็จ!")

        sum_out_thb = tax_v["Out_THB"].sum()
        sum_in_thb = tax_v["In_THB"].sum()
        sum_wht_thb = (tax_v["WHT_USD"] * tax_v["FX_Rate"]).sum()
        net_tax_gain = max(0, sum_in_thb - sum_out_thb)

        st.markdown("---")
        cf1, cf2, cf3 = st.columns(3)
        cf1.metric("📤 ยอดเงินโอนออกนอกประเทศรวม (เงินต้นตั้งรับ)", f"฿{sum_out_thb:,.2f}")
        cf2.metric("📥 ยอดเงินนำกลับเข้าไทยรวม", f"฿{sum_in_thb:,.2f}")
        cf3.metric("🚨 ส่วนเกินทุนสุทธิ (ประเมินภาษี)", f"฿{net_tax_gain:,.2f}", "หักล้างเงินต้นเรียบร้อยแล้ว", delta_color="inverse")

        st.markdown("---")
        c1, c2, c3 = st.columns(3)
        with c1: tax_year = st.selectbox("📅 เลือกปีภาษี", ["2567 (2024)", "2568 (2025)", "2569 (2026)", "2570 (2027)", "2571 (2028)", "2572 (2029)", "2573 (2030)"])
        with c2: is_resident = st.radio("อาศัยอยู่ในไทยเกิน 180 วัน หรือไม่?", ["เกิน 180 วัน", "ไม่ถึง 180 วัน"])
        with c3: other_income = st.number_input("รายได้ประจำอื่นๆ ต่อปี (บาท)", min_value=0.0, value=500000.0, step=50000.0)

        standard_expense = min(other_income * 0.5, 100000.0)
        personal_deduction = 60000.0 
        
        with st.expander("📝 บันทึกค่าลดหย่อนส่วนบุคคล", expanded=True):
            col_d1, col_d2 = st.columns(2)
            spouse_deduction = col_d1.checkbox("มีคู่สมรส (ไม่มีรายได้) - ลดหย่อน 60,000 บาท")
            children_count = col_d2.number_input("จำนวนบุตร (คนละ 30,000 บาท)", min_value=0, step=1)
            c_inv1, c_inv2, c_inv3 = st.columns(3)
            life_ins = c_inv1.number_input("เบี้ยประกันชีวิต", min_value=0.0, step=5000.0)
            health_ins = c_inv2.number_input("เบี้ยประกันสุขภาพ", min_value=0.0, step=5000.0)
            pvd = c_inv3.number_input("กองทุน PVD / กบข.", min_value=0.0, step=5000.0)
            ssf = c_inv1.number_input("ซื้อกองทุน SSF", min_value=0.0, step=5000.0)
            rmf = c_inv2.number_input("ซื้อกองทุน RMF", min_value=0.0, step=5000.0)
            donate = c_inv3.number_input("เงินบริจาค", min_value=0.0, step=1000.0)

        actual_health = min(health_ins, 25000.0)
        actual_life_health = min(life_ins + actual_health, 100000.0)
        total_income_for_cap = other_income + net_tax_gain
        ssf_limit = min(ssf, total_income_for_cap * 0.3, 200000.0)
        rmf_limit = min(rmf, total_income_for_cap * 0.3, 500000.0)
        pvd_limit = min(pvd, total_income_for_cap * 0.15, 500000.0)
        retirement_total = min(ssf_limit + rmf_limit + pvd_limit, 500000.0)
        family_deduction = (60000.0 if spouse_deduction else 0.0) + (children_count * 30000.0)
        
        total_deductions = standard_expense + personal_deduction + family_deduction + actual_life_health + retirement_total + donate

        if st.button(f"📊 คำนวณภาษีสุทธิ ปี {tax_year}", type="primary", use_container_width=True):
            if "ไม่ถึง" in is_resident: st.success("🎉 ได้รับยกเว้นภาษี")
            elif net_tax_gain <= 0: st.success("🎉 ยังไม่มีกำไรส่วนเกินจากยอดเงินต้น ไม่ต้องเสียภาษีค่ะ")
            else:
                net_inc = max(0, (other_income + net_tax_gain) - total_deductions)
                net_inc_without = max(0, other_income - total_deductions)
                def calc_tax(n):
                    t = 0
                    if n > 5000000: t += (n - 5000000) * 0.35 + 1265000
                    elif n > 2000000: t += (n - 2000000) * 0.30 + 365000
                    elif n > 1000000: t += (n - 1000000) * 0.25 + 115000
                    elif n > 750000: t += (n - 750000) * 0.20 + 65000
                    elif n > 500000: t += (n - 500000) * 0.15 + 27500
                    elif n > 300000: t += (n - 300000) * 0.10 + 7500
                    elif n > 150000: t += (n - 150000) * 0.05
                    return t
                
                tax_raw = calc_tax(net_inc) - calc_tax(net_inc_without)
                final_tax = max(0, tax_raw - sum_wht_thb)
                
                st.subheader(f"ผลการคำนวณ ภ.ง.ด. 90 (ประจำปี {tax_year})")
                r1, r2 = st.columns(2)
                r1.metric("ภาษีที่เกิดจากพอร์ต ตปท.", f"฿{tax_raw:,.2f}")
                r2.metric("🚨 ภาษีที่ต้องจ่ายเพิ่มจริง (หักเครดิตแล้ว)", f"฿{final_tax:,.2f}")

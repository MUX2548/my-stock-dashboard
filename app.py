import json
import time
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

# ==========================================
# 1. ตั้งค่าหน้าเพจ & ตกแต่ง UI/UX
# ==========================================
st.set_page_config(page_title="Strategic Portfolio Ecosystem 4.10", page_icon="📈", layout="wide")

st.markdown("""
    <style>
    .stButton>button { border-radius: 12px; font-weight: bold; transition: all 0.3s ease; border: 1px solid #4CAF50; }
    .stButton>button:hover { transform: translateY(-2px); box-shadow: 0 6px 15px rgba(76, 175, 80, 0.4); border-color: #4CAF50; }
    div[data-testid="stMetricValue"] { padding-bottom: 0px; }
    .stSpinner > div > div { border-top-color: #deff9a !important; }
    </style>
""", unsafe_allow_html=True)

tz_th = timezone(timedelta(hours=7))
current_date = datetime.now(tz_th).strftime("%d/%m/%Y")
current_time = datetime.now(tz_th).strftime("%H:%M:%S")

# ==========================================
# 2. 🔐 การเชื่อมต่อฐานข้อมูล (Database Services)
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
    try:
        ws = sh.worksheet(worksheet_name)
        ws.clear()
        clean_df = clean_df_types(df)
        data_list = [clean_df.columns.values.tolist()] + clean_df.values.tolist()
        ws.update(values=data_list, range_name='A1')
        return True
    except Exception as e:
        st.error(f"❌ เกิดข้อผิดพลาดในการบันทึกข้อมูล: {e}")
        return False

# ==========================================
# 3. 🧮 ลอจิกการคำนวณ (Business Logic)
# ==========================================
def calculate_stats(df_input):
    df = clean_df_types(df_input)
    
    # 🐞 Bug Fix: ป้องกันยอดยกมาเพี้ยนด้วยการเรียงลำดับวันที่ก่อนคำนวณ
    if not df.empty and "Date" in df.columns:
        df["Date_Temp"] = pd.to_datetime(df["Date"], format="%d/%m/%Y", errors="coerce")
        df = df.sort_values(by="Date_Temp").drop(columns=["Date_Temp"]).reset_index(drop=True)

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
        elif action == "กำไรจากการขายหุ้น (Profit)": cb += a
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
    
    df["Running_Balance"] = r_bals
    return df, cb, stat, hld

# ==========================================
# 4. 🌐 บริการดึงข้อมูลหุ้น (Financial APIs)
# ==========================================
@st.cache_data(ttl=60)
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
        spy_trend, spy_price = "N/A", 0.0
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

        # Indicators
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
    except Exception: 
        return pd.DataFrame(), {}, None, None

# 🚀 Performance Upgrade: ดึงข้อมูลราคาหุ้นทั้งพอร์ตพร้อมกัน (Batch Download)
@st.cache_data(ttl=60)
def get_batch_live_prices(tickers):
    if not tickers: return {}
    try:
        df = yf.download(tickers, period="1d", group_by='ticker', progress=False)
        prices = {}
        # จัดการโครงสร้างข้อมูลที่ต่างกันระหว่างการดึง 1 ตัว vs หลายตัว
        if len(tickers) == 1:
            if not df.empty and 'Close' in df.columns:
                prices[tickers[0]] = float(df['Close'].iloc[-1])
        else:
            for t in tickers:
                if t in df.columns.levels[0]:
                    if not df[t].empty and 'Close' in df[t].columns:
                        val = df[t]['Close'].iloc[-1]
                        if pd.notna(val): prices[t] = float(val)
        return prices
    except Exception:
        return {}

@st.cache_data(ttl=60)
def get_live_fx():
    try: 
        df = yf.Ticker("USDTHB=X").history(period="1d")
        if not df.empty: return df['Close'].iloc[-1]
    except: pass
    return 35.00

@st.cache_data
def convert_df_to_csv(df):
    return df.to_csv(index=False).encode('utf-8-sig')

# ==========================================
# 5. กำหนด Session State เบื้องต้น
# ==========================================
if "trade_ledger" not in st.session_state: st.session_state.trade_ledger = load_ledger_data()
if "logged_in" not in st.session_state: st.session_state["logged_in"] = False

def log_visitor():
    try:
        ws = sh.worksheet("Visitor_Log")
        if "has_logged_visit" not in st.session_state:
            timestamp = datetime.now(tz_th).strftime("%d/%m/%Y %H:%M:%S")
            ws.append_row([timestamp])
            st.session_state.has_logged_visit = True
        return len(ws.col_values(1))
    except: return "N/A"

visitor_count = log_visitor()

# ==========================================
# 🌟 Sidebar
# ==========================================
with st.sidebar:
    st.title("🛡️ Strategic Hub")
    if st.button("🔄 ดึงข้อมูลเรียลไทม์เดี๋ยวนี้", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
        
    st.info(f"👁️ **ยอดผู้เข้าชมทั้งหมด: {visitor_count} ครั้ง**")
    st.markdown("---")
    
    ticker = st.text_input("🔎 ชื่อหุ้น / ดัชนี", value="VKTX").upper()
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

# --- ดึงข้อมูลวิเคราะห์กราฟหลัก ---
with st.spinner(f"⏳ กำลังดึงข้อมูลกราฟ {ticker} และเรดาร์ตลาดโลก..."):
    df, fund, matrix, market_signal = load_pro_data(ticker, tf_option)

tabs = ["📊 วิเคราะห์กราฟ (Analysis)", "💼 บัญชี (Cloud Sync)", "🧾 ภาษีสรรพากร"] if st.session_state["logged_in"] else ["📊 วิเคราะห์กราฟ (Analysis)"]
tab_list = st.tabs(tabs)

# ==========================================
# หน้า 1: วิเคราะห์กราฟ
# ==========================================
with tab_list[0]:
    st.markdown(f"## 📈 วิเคราะห์หุ้น: {ticker}")
    st.markdown(f"#### 📅 ข้อมูล ณ วันที่: <span style='color:#4CAF50'>{current_date}</span> &nbsp;|&nbsp; 🕒 อัปเดตล่าสุด: <span style='color:#4CAF50'>{current_time} น.</span>", unsafe_allow_html=True)
    
    if not df.empty:
        last_p = df['Close'].iloc[-1]
        prev_p = df['Close'].iloc[-2] if len(df) > 1 else last_p
        
        if market_signal:
            st.markdown("---")
            st.markdown("### 🌐 Market Signal (เรดาร์สแกนภาพรวมตลาด)")
            m1, m2, m3 = st.columns(3)
            spy_t, spy_p = market_signal["spy_trend"], market_signal["spy_price"]
            m1.metric("ตลาดโลก (S&P 500)", f"{spy_p:,.2f} จุด", f"{spy_t} (กระแสน้ำ{'ผลักดัน' if 'ขึ้น' in spy_t else 'กดดัน'})", delta_color="normal" if "ขึ้น" in spy_t else "inverse")
            
            v_val = market_signal["vix"]
            if v_val < 20: v_stat, v_col = "🟢 คนกล้าซื้อ (Risk ON)", "normal"
            elif v_val < 30: v_stat, v_col = "🟡 เฝ้าระวัง (Neutral)", "off"
            else: v_stat, v_col = "🔴 ตื่นตระหนก (Risk OFF)", "inverse"
            m2.metric("ดัชนีความกลัว (VIX Index)", f"{v_val:.2f}", v_stat, delta_color=v_col)
            
            with m3:
                if "ขึ้น" in spy_t and v_val < 25: st.success("✅ **ตลาดเป็นใจ:** สภาพแวดล้อมปลอดภัย เอื้อต่อการเข้าทำกำไร")
                elif "ลง" in spy_t and v_val > 25: st.error("🚨 **ความเสี่ยงสูง:** ตลาดกำลังผันผวนรุนแรง คุมความเสี่ยงด่วน")
                else: st.warning("⚠️ **ตลาดไร้ทิศทาง:** ตลาดยังเลือกทางไม่ได้ แนะนำเก็งกำไรในกรอบ")

        c_l, c_r = st.columns([7, 3])
        with c_l:
            fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.45, 0.15, 0.2, 0.2])
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name="Price"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['Trendline'], line=dict(color='rgba(255, 255, 255, 0.4)', dash='dot', width=2), name="Trend"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['E20'], line=dict(color='#00E676', width=2.5), name="EMA 20"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['E50'], line=dict(color='#FF6D00', width=2.5), name="EMA 50"), row=1, col=1)
            
            v_c = ['#00E676' if df['Close'].iloc[i] > df['Open'].iloc[i] else '#FF5252' for i in range(len(df))]
            fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=v_c, name="Vol"), row=2, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], line=dict(color='#BA68C8', width=2), name="RSI"), row=3, col=1)
            fig.add_trace(go.Bar(x=df.index, y=df['Hist'], marker_color=['#00E676' if v >= 0 else '#FF5252' for v in df['Hist']], name="MACD Hist"), row=4, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['MACD'], line=dict(color='#2962FF', width=2), name="MACD"), row=4, col=1)

            fig.update_layout(template="plotly_dark", height=700, margin=dict(l=0,r=0,t=0,b=0), showlegend=False, xaxis_rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)
            
            st.subheader("📊 ข้อมูลพื้นฐาน (Fundamental)")
            f1, f2, f3 = st.columns(3)
            f1.metric("P/S Ratio", fund.get('ps','N/A')); f2.metric("P/E Ratio", fund.get('pe','N/A')); f3.metric("ROE", fund.get('roe','N/A'))
        
        with c_r:
            price_diff = last_p - prev_p
            pct_diff = (price_diff / prev_p) * 100 if prev_p > 0 else 0
            st.metric("ราคาปัจจุบัน", f"${last_p:,.2f}", f"{price_diff:,.2f} ({pct_diff:,.2f}%)")
            
            if b_p > 0:
                pl = ((last_p - b_p) / b_p) * 100
                st.write(f"**กำไร/ขาดทุนของคุณ:** {pl:.2f}%")
                sl = df['E50'].iloc[-1] * 0.99 if b_p == 0 else b_p * 0.92
                st.error(f"🛡️ **จุดหนี (Stop Loss): ${sl:.2f}**")
    else:
        st.warning(f"⚠️ ไม่สามารถดึงข้อมูลกราฟของหุ้น **'{ticker}'** ได้ในขณะนี้ค่ะ")

if st.session_state["logged_in"]:
    # ประมวลผลบัญชีก่อนแสดงผล
    sorted_ledger, cb, l_stat, holdings = calculate_stats(st.session_state.trade_ledger)
    st.session_state.trade_ledger = sorted_ledger

    # ==========================================
    # หน้า 2: บัญชีและพอร์ตโฟลิโอ (Auto Real-time)
    # ==========================================
    with tab_list[1]:
        st.subheader("💼 แดชบอร์ดกระแสเงินสด (Cashflow Overview)")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("📤 นำเงินออกสะสม (ลงทุน)", f"${l_stat['outward']:,.2f}")
        col2.metric("📥 นำเงินกลับไทย (ถอน)", f"${l_stat['inward']:,.2f}")
        col3.metric("📈 ต้นทุนหุ้นในพอร์ตรวม", f"${l_stat['bought'] - l_stat['sold']:,.2f}")
        col4.metric("💰 เงินสดคงเหลือ (พร้อมเทรด)", f"${cb:,.2f}", "💵 Cash Balance")
        
        st.markdown("---")
        st.subheader("📝 สมุดบันทึกบัญชีการเทรด (Cloud Ledger)")
        
        with st.form("ledger_form"):
            ed_l = st.data_editor(st.session_state.trade_ledger, num_rows="dynamic", use_container_width=True,
                column_config={
                    "Date": "วันที่ (DD/MM/YYYY)",
                    "Action": st.column_config.SelectboxColumn("ประเภท", options=["นำเงินออกนอกประเทศ (Outward)", "นำเงินเข้าประเทศไทย (Inward)", "ซื้อหุ้น (Buy)", "ขายหุ้น (Sell)", "รับเงินปันผล (Dividend)", "กำไรจากการขายหุ้น (Profit)"]),
                    "Ticker": "ชื่อหุ้น",
                    "Price": st.column_config.NumberColumn("ราคา ($)", format="%.4f", step=0.0001),
                    "Shares": st.column_config.NumberColumn("จำนวนหุ้น", format="%.4f", step=0.0001),
                    "Amount_USD": st.column_config.NumberColumn("จำนวนเงิน ($)", format="%.2f", step=0.01),
                    "Running_Balance": st.column_config.NumberColumn("ยอดยกมา ($)", disabled=True, format="%.2f"), 
                    "FX_Rate": st.column_config.NumberColumn("เรทเงิน", format="%.4f", step=0.0001), 
                    "WHT_USD": st.column_config.NumberColumn("ภาษีหักฯ ($)", format="%.2f", step=0.01), 
                    "Ref_Doc": "หมายเหตุ"
                })
            
            submit_btn = st.form_submit_button("💾 บันทึกข้อมูลบัญชีขึ้น Cloud", type="primary", use_container_width=True)
            
            if submit_btn:
                # คำนวณ Running Balance ใหม่ทันทีหลังกด Save
                updated_df, _, _, _ = calculate_stats(ed_l)
                st.session_state.trade_ledger = updated_df
                if save_df_to_sheet("Ledger", updated_df):
                    st.success("✅ บันทึกสำเร็จ! ข้อมูลปลอดภัย 100%")
                    time.sleep(1)
                    st.rerun()

        st.markdown("---")
        st.subheader("📊 พอร์ตโฟลิโอปัจจุบัน (Auto Real-Time Mark to Market)")
        
        live_fx = get_live_fx()
        st.info(f"💱 **อัตราแลกเปลี่ยนตลาดโลก ณ วินาทีนี้ (USD/THB):** ฿{live_fx:.4f} ต่อ 1 ดอลลาร์")
        
        # ดึงรายชื่อหุ้นในพอร์ตเพื่อ Batch Download
        active_tickers = [t for t, data in holdings.items() if data["shares"] > 0.001]
        
        if active_tickers:
            with st.spinner("⏳ กำลังดึงราคาล่าสุดของหุ้นทั้งพอร์ตพร้อมกัน..."):
                batch_prices = get_batch_live_prices(active_tickers)
                
            results, total_v, total_invested = [], 0.0, 0.0
            
            for t in active_tickers:
                data = holdings[t]
                sh, t_cost = data["shares"], data["total_cost"]
                avg_cost = t_cost / sh
                curr_p = batch_prices.get(t, avg_cost) # Fallback ถ้าราคาดึงไม่สำเร็จ
                
                val = curr_p * sh
                profit_usd = val - t_cost
                profit_thb = profit_usd * live_fx
                
                # 🐞 Bug Fix: กันต้นทุนเป็น 0 จากหุ้นปันผล/แตกพาร์
                profit_pct = (profit_usd / t_cost * 100) if t_cost > 0 else 100.0
                
                total_v += val
                total_invested += t_cost
                
                results.append({
                    "หุ้น": t, "จำนวนหุ้น": sh, "ต้นทุนเฉลี่ย": avg_cost, 
                    "ราคาปัจจุบัน": curr_p, "กำไร/ขาดทุน ($)": profit_usd, 
                    "กำไร/ขาดทุน (฿)": profit_thb, "% เปลี่ยนแปลง": profit_pct, "มูลค่ารวม": val
                })
            
            p1, p2, p3, p4 = st.columns(4)
            p1.metric("มูลค่าหุ้นรวม ($)", f"${total_v:,.2f}")
            p2.metric("ต้นทุนหุ้นทั้งหมด ($)", f"${total_invested:,.2f}")
            total_pl_usd = total_v - total_invested
            pl_pct = (total_pl_usd / total_invested * 100) if total_invested > 0 else 0
            p3.metric("กำไร/ขาดทุนรวม ($)", f"${total_pl_usd:,.2f}", f"{pl_pct:.2f}%")
            p4.metric("กำไร/ขาดทุนรวม (฿)", f"฿{(total_pl_usd * live_fx):,.2f}")
            
            res_df = pd.DataFrame(results)
            st.dataframe(res_df.style.map(lambda x: f'color: {"#FF5252" if x < 0 else "#00E676"};', subset=["กำไร/ขาดทุน ($)", "% เปลี่ยนแปลง"])
                         .format({"จำนวนหุ้น": "{:,.4f}", "ต้นทุนเฉลี่ย": "${:,.4f}", "ราคาปัจจุบัน": "${:,.4f}",
                                  "กำไร/ขาดทุน ($)": "${:,.2f}", "กำไร/ขาดทุน (฿)": "฿{:,.2f}", "% เปลี่ยนแปลง": "{:,.2f}%", "มูลค่ารวม": "${:,.2f}"}), 
                         use_container_width=True)

            # 🌟 New Feature: Portfolio Rebalancing
            with st.expander("⚖️ เครื่องมือปรับสมดุลพอร์ต (Portfolio Rebalancing)"):
                st.markdown("กำหนดเป้าหมายน้ำหนักของหุ้นแต่ละตัว (%) เพื่อคำนวณส่วนต่างที่ต้องปรับปรุง")
                rebal_df = res_df[["หุ้น", "มูลค่ารวม", "ราคาปัจจุบัน"]].copy()
                rebal_df["% ปัจจุบัน"] = (rebal_df["มูลค่ารวม"] / total_v) * 100
                rebal_df["% เป้าหมาย"] = 0.0  # ค่าเริ่มต้น
                
                edited_rebal = st.data_editor(rebal_df, column_config={"% เป้าหมาย": st.column_config.NumberColumn("เป้าหมาย (%)", min_value=0, max_value=100)}, use_container_width=True)
                
                target_sum = edited_rebal["% เป้าหมาย"].sum()
                if target_sum > 0:
                    if abs(target_sum - 100.0) > 0.01:
                        st.warning(f"⚠️ น้ำหนักเป้าหมายรวมคือ {target_sum}% (ควรจะเท่ากับ 100%)")
                    else:
                        st.success("✅ น้ำหนักรวมสมดุล 100%")
                        
                    edited_rebal["มูลค่าเป้าหมาย ($)"] = total_v * (edited_rebal["% เป้าหมาย"] / 100)
                    edited_rebal["ส่วนต่าง ($)"] = edited_rebal["มูลค่าเป้าหมาย ($)"] - edited_rebal["มูลค่ารวม"]
                    edited_rebal["Action หุ้น"] = edited_rebal["ส่วนต่าง ($)"] / edited_rebal["ราคาปัจจุบัน"]
                    
                    st.write("📌 **แผนการปรับพอร์ต (Action Plan):**")
                    action_df = edited_rebal[["หุ้น", "ส่วนต่าง ($)", "Action หุ้น"]].copy()
                    st.dataframe(action_df.style.format({"ส่วนต่าง ($)": "${:,.2f}", "Action หุ้น": "{:,.2f} หุ้น"}).map(lambda x: f'color: {"#FF5252" if x < 0 else "#00E676"};', subset=["ส่วนต่าง ($)", "Action หุ้น"]), use_container_width=True)

        else:
            st.info("ว่างเปล่า (ยังไม่มีหุ้นในพอร์ตค่ะ)")

    # ==========================================
    # หน้า 3: ภาษีสรรพากร
    # ==========================================
    with tab_list[2]:
        st.subheader("🧾 ระบบประเมินภาษีสรรพากร ภ.ง.ด. 90")
        
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

        with st.form("tax_form"):
            ed_t = st.data_editor(tax_v, use_container_width=True, num_rows="fixed",
                column_order=["Date", "Out_USD", "In_USD", "FX_Rate", "Out_THB", "In_THB", "Balance_THB", "WHT_USD", "Ref_Doc"],
                column_config={"Date": st.column_config.Column("วันที่", disabled=True), "Out_USD": st.column_config.NumberColumn("โอนออก ($)", disabled=True), "In_USD": st.column_config.NumberColumn("นำเข้า ($)", disabled=True),
                               "FX_Rate": st.column_config.NumberColumn("เรทเงิน (บาท/$)", format="%.4f", step=0.0001), 
                               "Out_THB": st.column_config.NumberColumn("โอนออก (฿)", disabled=True), "In_THB": st.column_config.NumberColumn("นำเข้า (฿)", disabled=True),
                               "WHT_USD": st.column_config.NumberColumn("ภาษีหัก ตปท. ($)", format="%.2f", step=0.01), 
                               "Balance_THB": st.column_config.NumberColumn("เงินต้นคงเหลือ (฿)", disabled=True), "Ref_Doc": "หมายเหตุ"})
            
            if st.form_submit_button("💾 บันทึกอัตราแลกเปลี่ยนลง Cloud", type="primary", use_container_width=True):
                ed_t_clean = clean_df_types(ed_t)
                st.session_state.trade_ledger.loc[tax_idx, "FX_Rate"] = ed_t_clean["FX_Rate"].values
                st.session_state.trade_ledger.loc[tax_idx, "WHT_USD"] = ed_t_clean["WHT_USD"].values
                st.session_state.trade_ledger.loc[tax_idx, "Ref_Doc"] = ed_t_clean["Ref_Doc"].values
                if save_df_to_sheet("Ledger", st.session_state.trade_ledger):
                    st.success("บันทึกสำเร็จ!")
                    time.sleep(1)
                    st.rerun()

        sum_out_thb = tax_v["Out_THB"].sum()
        sum_in_thb = tax_v["In_THB"].sum()
        sum_wht_thb = (tax_v["WHT_USD"] * tax_v["FX_Rate"]).sum()
        net_tax_gain = max(0, sum_in_thb - sum_out_thb)

        st.markdown("---")
        cf1, cf2, cf3 = st.columns(3)
        cf1.metric("📤 ยอดเงินโอนออกนอกประเทศรวม", f"฿{sum_out_thb:,.2f}")
        cf2.metric("📥 ยอดเงินนำกลับเข้าไทยรวม", f"฿{sum_in_thb:,.2f}")
        cf3.metric("🚨 ส่วนเกินทุนสุทธิ (ประเมินภาษี)", f"฿{net_tax_gain:,.2f}", "หักล้างเงินต้นเรียบร้อยแล้ว", delta_color="inverse")

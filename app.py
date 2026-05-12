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
# 1. ตั้งค่าหน้าเพจ
# ==========================================
st.set_page_config(page_title="Strategic Portfolio Ecosystem 4.10", page_icon="📈", layout="wide")

st.markdown("""
    <style>
    .stButton>button { border-radius: 12px; font-weight: bold; transition: all 0.3s ease; border: 1px solid #4CAF50; }
    .stButton>button:hover { transform: translateY(-2px); box-shadow: 0 6px 15px rgba(76, 175, 80, 0.4); border-color: #4CAF50; }
    .stButton>button[data-baseweb="button"] { border-radius: 12px; }
    .summary-box { padding: 20px; border-radius: 10px; margin-bottom: 20px; border-left: 5px solid; }
    div[data-testid="stMetricValue"] { padding-bottom: 0px; }
    .stSpinner > div > div { border-top-color: #deff9a !important; }
    </style>
""", unsafe_allow_html=True)

tz_th = timezone(timedelta(hours=7))
current_date = datetime.now(tz_th).strftime("%d/%m/%Y")
current_time = datetime.now(tz_th).strftime("%H:%M:%S")

# ==========================================
# 2. 🔐 การเชื่อมต่อฐานข้อมูล
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
    for col in num_cols:
        if col in df_clean.columns:
            df_clean[col] = pd.to_numeric(df_clean[col], errors='coerce').fillna(0.0)
    str_cols = ["Date", "Action", "Ticker", "Ref_Doc"]
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

def log_visitor():
    try:
        ws = sh.worksheet("Visitor_Log")
        if "has_logged_visit" not in st.session_state:
            timestamp = datetime.now(tz_th).strftime("%d/%m/%Y %H:%M:%S")
            ws.append_row([timestamp])
            st.session_state.has_logged_visit = True
        total_visits = len(ws.col_values(1))
        return total_visits
    except Exception as e:
        return "N/A"

visitor_count = log_visitor()

# ==========================================
# 3. ลอจิกการคำนวณบัญชี
# ==========================================
def calculate_stats(df_input):
    df = clean_df_types(df_input)
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
    
    return df, cb, stat, r_bals, hld

@st.cache_data
def convert_df_to_csv(df):
    return df.to_csv(index=False).encode('utf-8-sig')

# ==========================================
# 4. ดึงข้อมูลทางการเงิน (Independent Fetching System)
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
        
        market_signal = {"spy_trend": "N/A", "spy_price": 0.0, "vix": 0.0, "vix_ts": 0.0, "smart_money": "N/A"}
        try:
            spy = yf.Ticker("^GSPC").history(period=p, interval=i)
            if not spy.empty:
                df['RS'] = (df['Close'].pct_change(10) - spy['Close'].pct_change(10)) * 100
                spy_p = spy['Close'].iloc[-1]
                spy_ema50 = spy['Close'].ewm(span=50).mean().iloc[-1]
                market_signal["spy_price"] = float(spy_p)
                market_signal["spy_trend"] = "ขึ้น 📈" if spy_p > spy_ema50 else "ลง 📉"
            else: df['RS'] = 0
        except: df['RS'] = 0

        try:
            vix = yf.Ticker("^VIX").history(period="1mo")
            if not vix.empty: market_signal["vix"] = float(vix['Close'].iloc[-1])
        except: pass

        try:
            vix3m = yf.Ticker("^VIX3M").history(period="1mo")
            if not vix3m.empty and market_signal["vix"] > 0:
                market_signal["vix_ts"] = float(market_signal["vix"] / vix3m['Close'].iloc[-1])
        except: pass

        try:
            hyg = yf.Ticker("HYG").history(period="6mo")['Close']
            ief = yf.Ticker("IEF").history(period="6mo")['Close']
            if not hyg.empty and not ief.empty:
                df_sm = pd.concat([hyg, ief], axis=1).dropna()
                df_sm.columns = ['HYG', 'IEF']
                hyg_ief_ratio = df_sm['HYG'] / df_sm['IEF']
                ratio_ema20 = hyg_ief_ratio.ewm(span=20).mean().iloc[-1]
                market_signal["smart_money"] = "Risk ON 🟢" if hyg_ief_ratio.iloc[-1] > ratio_ema20 else "Risk OFF 🔴"
        except: pass

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
            y, x = df['Close'].values, np.arange(len(df['Close'].values))
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

@st.cache_data(ttl=60)
def get_batch_live_prices(tickers):
    if not tickers: return {}
    try:
        df = yf.download(tickers, period="1d", progress=False)
        prices = {}
        if len(tickers) == 1:
            if not df.empty and 'Close' in df.columns: prices[tickers[0]] = float(df['Close'].iloc[-1])
        else:
            if 'Close' in df.columns:
                for t in tickers:
                    if t in df['Close'].columns:
                        val = df['Close'][t].iloc[-1]
                        if pd.notna(val): prices[t] = float(val)
        return prices
    except: return {}

@st.cache_data(ttl=60)
def get_live_fx():
    try: return yf.Ticker("USDTHB=X").history(period="1d")['Close'].iloc[-1]
    except: return 35.00

# ==========================================
# 5. UI: Sidebar
# ==========================================
with st.sidebar:
    st.title("🛡️ Strategic Hub")
    if st.button("🔄 ดึงข้อมูลเรียลไทม์เดี๋ยวนี้", use_container_width=True):
        st.cache_data.clear(); st.rerun()
    st.info(f"👁️ **ยอดผู้เข้าชมทั้งหมด: {visitor_count} ครั้ง**")
    st.markdown("---")
    ticker = st.text_input("🔎 ชื่อหุ้น / ดัชนี", value="NVTS").upper()
    tf_option = st.radio("เลือกความละเอียด:", ["1D (รายวัน)", "1W (รายสัปดาห์)", "1M (รายเดือน)"], index=0)
    st.markdown("---")
    st.subheader("🧮 เครื่องมือคำนวณ (Public)")
    t_cap = st.number_input("เงินทุนรวม (USD)", value=10000.0)
    r_pct = st.slider("ความเสี่ยงต่อไม้ (%)", 1.0, 5.0, 2.0)
    b_p = st.number_input("ราคาต้นทุนสมมติ (USD)", min_value=0.0, step=0.1)
    st.markdown("---")
    if not st.session_state["logged_in"]:
        pwd = st.text_input("🔑 รหัสผ่าน (สำหรับเจ้าของ)", type="password")
        if st.button("🔓 เข้าสู่ระบบ", use_container_width=True, type="primary"):
            if pwd == st.secrets.get("app_password", "123456"): st.session_state["logged_in"] = True; st.rerun()
            else: st.error("❌ รหัสผ่านไม่ถูกต้อง")
    else:
        st.success("✅ โหมดเจ้าของพอร์ต")
        if st.button("🚪 ออกจากระบบ", use_container_width=True): st.session_state["logged_in"] = False; st.rerun()

# ประมวลผลบัญชีก่อนเพื่อดึงข้อมูลพอร์ตมาใช้วางแผนในหน้า 1
holdings = {}
if st.session_state["logged_in"]:
    sorted_df, cb, l_stat, r_bals, holdings = calculate_stats(st.session_state.trade_ledger)
    st.session_state.trade_ledger = sorted_df

with st.spinner(f"⏳ กำลังประมวลผลข้อมูล AI Advanced Radar..."):
    df, fund, matrix, market_signal = load_pro_data(ticker, tf_option)

tabs = ["📊 วิเคราะห์กราฟ (Analysis)", "💼 บัญชี (Cloud Sync)", "🧾 ภาษีสรรพากร"] if st.session_state["logged_in"] else ["📊 วิเคราะห์กราฟ (Analysis)"]
tab_list = st.tabs(tabs)

# ==========================================
# หน้า 1: วิเคราะห์กราฟ (Trader Insights Edition)
# ==========================================
with tab_list[0]:
    # ส่วนหัวและปุ่ม Pop-up (แสดงเฉพาะตอน Login)
    h_col1, h_col2 = st.columns([7, 3])
    with h_col1:
        st.markdown(f"## 📈 วิเคราะห์หุ้น: {ticker}")
        st.markdown(f"#### 📅 ข้อมูล ณ วันที่: <span style='color:#4CAF50'>{current_date}</span> &nbsp;|&nbsp; 🕒 อัปเดตล่าสุด: <span style='color:#4CAF50'>{current_time} น.</span>", unsafe_allow_html=True)
    
    with h_col2:
        if st.session_state["logged_in"]:
            st.markdown("<br>", unsafe_allow_html=True)
            with st.popover("➕ บันทึกเทรดด่วน (Quick Entry)", use_container_width=True):
                st.markdown(f"**เพิ่มรายการบัญชีสำหรับ `{ticker}` หรือรายการอื่นๆ**")
                with st.form("quick_entry_form"):
                    q_c1, q_c2 = st.columns(2)
                    qe_date = q_c1.text_input("วันที่ (DD/MM/YYYY)", value=current_date)
                    qe_action = q_c2.selectbox("ประเภท", ["ซื้อหุ้น (Buy)", "ขายหุ้น (Sell)", "นำเงินเข้าประเทศไทย (Inward)", "นำเงินออกนอกประเทศ (Outward)", "รับเงินปันผล (Dividend)", "กำไรจากการขายหุ้น (Profit)"])
                    
                    q_c3, q_c4, q_c5 = st.columns(3)
                    qe_ticker = q_c3.text_input("ชื่อหุ้น", value=ticker)
                    qe_price = q_c4.number_input("ราคา ($)", min_value=0.0, format="%.4f")
                    qe_shares = q_c5.number_input("จำนวนหุ้น", min_value=0.0, format="%.4f")
                    
                    q_c6, q_c7, q_c8 = st.columns(3)
                    qe_amount = q_c6.number_input("จำนวนเงิน ($)", min_value=0.0, format="%.2f")
                    qe_fx = q_c7.number_input("เรทเงิน", min_value=0.0, format="%.4f", value=35.0)
                    qe_wht = q_c8.number_input("ภาษีหักฯ ($)", min_value=0.0, format="%.2f")
                    
                    qe_ref = st.text_input("หมายเหตุ")
                    
                    if st.form_submit_button("💾 บันทึกข้อมูลลง Cloud", type="primary", use_container_width=True):
                        new_row = {
                            "Date": qe_date, "Action": qe_action, "Ticker": qe_ticker.upper() if qe_ticker else "",
                            "Price": float(qe_price), "Shares": float(qe_shares), "Amount_USD": float(qe_amount),
                            "Running_Balance": 0.0, "FX_Rate": float(qe_fx), "WHT_USD": float(qe_wht), "Ref_Doc": qe_ref
                        }
                        st.session_state.trade_ledger = pd.concat([st.session_state.trade_ledger, pd.DataFrame([new_row])], ignore_index=True)
                        sorted_df_new, _, _, _, _ = calculate_stats(st.session_state.trade_ledger)
                        st.session_state.trade_ledger = sorted_df_new
                        save_df_to_sheet("Ledger", st.session_state.trade_ledger)
                        st.success("บันทึกสำเร็จ!")
                        time.sleep(1)
                        st.rerun()

    if not df.empty:
        last_p = df['Close'].iloc[-1]
        prev_p = df['Close'].iloc[-2] if len(df) > 1 else last_p
        rsi_val = df['RSI'].iloc[-1]
        is_uptrend = last_p > df['E50'].iloc[-1]
        is_bullish_macd = df['MACD'].iloc[-1] > df['Sig'].iloc[-1]
        
        spy_t = market_signal["spy_trend"] if market_signal else "N/A"
        spy_p = market_signal["spy_price"] if market_signal else 0.0
        v_val = market_signal["vix"] if market_signal else 0.0
        vix_ts = market_signal["vix_ts"] if market_signal else 0.0
        sm_flow = market_signal["smart_money"] if market_signal else "N/A"
        is_market_good = "ขึ้น" in spy_t and (0 < v_val < 25) and (0 < vix_ts < 1)

        # ==========================================
        # 🌐 การวางแผนพอร์ต & ทัศนะจากเทรดเดอร์มือหนึ่ง
        # ==========================================
        actual_cost = b_p # ค่าเริ่มต้นจาก Sidebar
        
        # ตรวจสอบว่าผู้ใช้ถือหุ้นตัวนี้อยู่หรือไม่
        if st.session_state["logged_in"] and holdings.get(ticker, {}).get("shares", 0) > 0.001:
            my_hold = holdings[ticker]
            my_sh = my_hold["shares"]
            actual_cost = my_hold["total_cost"] / my_sh # ใช้ต้นทุนจริงแทน Sidebar
            my_val = last_p * my_sh
            my_pl = my_val - my_hold["total_cost"]
            my_pl_pct = (my_pl / my_hold["total_cost"]) * 100
            
            st.markdown(f"""
            <div style="background-color: rgba(41, 98, 255, 0.1); border-left: 5px solid #2962FF; padding: 20px; border-radius: 8px; margin-top: 20px; margin-bottom: 20px;">
                <h4 style="margin-top: 0; color: #82B1FF;">💼 สถานะพอร์ตปัจจุบันของคุณ ({ticker})</h4>
                <div style="display: flex; justify-content: space-between; flex-wrap: wrap; font-size: 1.1em;">
                    <div><b>จำนวนหุ้นในมือ:</b> {my_sh:,.4f}</div>
                    <div><b>ต้นทุนเฉลี่ยจริง:</b> ${actual_cost:,.4f}</div>
                    <div><b>มูลค่าปัจจุบัน:</b> ${my_val:,.2f}</div>
                    <div><b>กำไร/ขาดทุน:</b> <span style="color: {'#00E676' if my_pl>=0 else '#FF5252'}; font-weight:bold;">${my_pl:,.2f} ({my_pl_pct:,.2f}%)</span></div>
                </div>
                <p style="margin-top: 15px; margin-bottom: 0; font-size: 0.9em; color: #B0BEC5;">
                    💡 <i>ระบบนำข้อมูลต้นทุนจริงของคุณไปพล็อตลงในกราฟด้านล่าง เพื่อใช้วางแผนการตัดขาดทุนหรือจุดทำกำไรร่วมกับเครื่องมือ AI ครับ</i>
                </p>
            </div>
            """, unsafe_allow_html=True)

        if is_market_good and is_uptrend and is_bullish_macd and rsi_val < 70:
            rec, color = "STRONG BUY / HOLD", "#00E676"
            msg = f"**'จังหวะน้ำขึ้นต้องรีบตัก'** - ตลาดโลกเอื้ออำนวย และ {ticker} กำลังอยู่ในรอบขาขึ้นเต็มตัว กราฟมีโมเมนตัมเชิงบวกชัดเจน แนะนำให้ทยอยสะสม (Buy on Dip) หรือถือรันเทรนด์ต่อเพื่อทำกำไรคำโตครับ"
        elif is_uptrend and rsi_val >= 70:
            rec, color = "HOLD / TAKE PROFIT", "#FFD600"
            msg = f"**'ระวังความร้อนแรง'** - หุ้นยังเป็นขาขึ้นแข็งแกร่ง แต่เข้าเขต Overbought (ซื้อมากเกินไป) มืออาชีพจะไม่ไล่ราคาตรงนี้ แนะนำให้ถือรันเทรนด์โดยยกจุดตัดขาดทุน (Trailing Stop) ตามขึ้นมา หรือพิจารณาแบ่งขายทำกำไรบางส่วนครับ"
        elif not is_uptrend and is_bullish_macd and rsi_val < 35:
            rec, color = "SPECULATIVE BUY", "#2962FF"
            msg = f"**'ลุ้นรีบาวด์ในโซนล่าง'** - หุ้นยังอยู่ในเทรนด์ขาลง แต่เริ่มมีสัญญาณแรงซื้อกลับและลงลึกจนเข้าเขต Oversold เหมาะสำหรับสายซิ่งที่ต้องการเก็งกำไรระยะสั้น (เล่นรอบเด้ง) แต่ต้องตั้งจุด Stop loss ให้รัดกุมครับ"
        elif not is_uptrend:
            rec, color = "AVOID / WAIT", "#FF5252"
            msg = f"**'รักษาเงินต้นคือหัวใจ'** - ภาพรวมของ {ticker} เสียทรงขาขึ้นและหลุดเส้นค่าเฉลี่ยสำคัญ โมเมนตัมยังดูอ่อนแอ แนะนำให้ทับมือรอดูสถานการณ์ (Wait & See) หรือหาโอกาสจากหุ้นตัวอื่นที่กราฟแข็งแรงกว่านี้ครับ"
        else:
            rec, color = "NEUTRAL / SIDEWAY", "#B0BEC5"
            msg = f"**'ตลาดรอเลือกทาง'** - กราฟกำลังแกว่งตัวออกข้าง (Sideway) สัญญาณยังขัดแย้งกัน แนะนำให้เทรดสั้นๆ ในกรอบ (ซื้อใกล้แนวรับ - ขายใกล้แนวต้าน) หรือรอดูจนกว่าราคาจะเบรกเอาท์เลือกทิศทางที่ชัดเจนครับ"

        st.markdown(f"""
        <div style="background-color: #1E1E1E; border: 1px solid #333; border-left: 8px solid {color}; padding: 25px; border-radius: 12px; margin-bottom: 30px; box-shadow: 0 4px 15px rgba(0,0,0,0.2);">
            <h3 style="color: {color}; margin-top: 0; margin-bottom: 15px; font-size: 1.6rem; display: flex; align-items: center;">
                <span style="font-size: 2rem; margin-right: 12px;">🤵</span> ทัศนะจากเทรดเดอร์มือหนึ่ง: {rec}
            </h3>
            <p style="font-size: 1.15rem; line-height: 1.6; color: #E0E0E0; margin-bottom: 20px;">{msg}</p>
            <div style="display: flex; flex-wrap: wrap; gap: 20px; font-size: 1rem; color: #B0BEC5; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 15px;">
                <span><b>📊 เทรนด์:</b> <span style="color: {'#00E676' if is_uptrend else '#FF5252'};">{'ขาขึ้น (Uptrend)' if is_uptrend else 'ขาลง (Downtrend)'}</span></span>
                <span><b>⚡ โมเมนตัม:</b> <span style="color: {'#00E676' if is_bullish_macd else '#FF5252'};">{'เชิงบวก (Bullish)' if is_bullish_macd else 'เชิงลบ (Bearish)'}</span></span>
                <span><b>🌡️ ความร้อนแรง (RSI):</b> <span style="color: {'#FFD600' if rsi_val >= 70 else '#2962FF' if rsi_val <= 30 else '#E0E0E0'};">{rsi_val:.2f}</span></span>
            </div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("### 🌐 Market Signal (เรดาร์สแกนภาพรวมตลาด)")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("ตลาดโลก (S&P 500)", f"{spy_p:,.2f}" if spy_p > 0 else "N/A", spy_t if spy_p > 0 else None, delta_color="normal" if "ขึ้น" in spy_t else "inverse" if "ลง" in spy_t else "off")
        m1.caption("💡 **นิยาม:** ทิศทางเม็ดเงินระดับโลก หากยืนเหนือเส้นค่าเฉลี่ย 50 วัน (EMA50) สะท้อนว่าภาพรวมตลาดยังอยู่ในแนวโน้มขาขึ้น")
        vix_stat = "Risk ON" if 0 < v_val < 20 else "Neutral" if 0 < v_val < 30 else "Panic"
        m2.metric("ความกลัว (VIX)", f"{v_val:.2f}" if v_val > 0 else "N/A", vix_stat if v_val > 0 else None, delta_color="normal" if 0 < v_val < 25 else "inverse" if v_val >= 25 else "off")
        m2.caption("💡 **นิยาม:** ยิ่งต่ำ (<20) ตลาดยิ่งปลอดภัย / ถ้ายิ่งสูง (>30) แปลว่านักลงทุนตื่นตระหนก ซื้อประกันความเสี่ยงและพร้อมเทขาย")
        ts_label = "🟢 สงบ" if 0 < vix_ts < 1 else "🔴 ตระหนก"
        m3.metric("โครงสร้าง (VIX/VIX3M)", f"{vix_ts:.2f}" if vix_ts > 0 else "N/A", ts_label if vix_ts > 0 else None, delta_color="normal" if 0 < vix_ts < 1 else "inverse" if vix_ts >= 1 else "off")
        m3.caption("💡 **นิยาม:** ความผันผวนระยะสั้นเทียบระยะยาว หากน้อยกว่า 1 แปลว่าตลาดอยู่ในภาวะปกติ (Contango)")
        m4.metric("เงินใหญ่ (HYG/IEF)", "Credit Flow", sm_flow if sm_flow != "N/A" else None, delta_color="normal" if "ON" in sm_flow else "inverse" if "OFF" in sm_flow else "off")
        m4.caption("💡 **นิยาม:** หากสถาบันกล้าซื้อหุ้นกู้ขยะ (HYG) แปลว่ากล้าเสี่ยง (Risk ON) แต่ถ้าหนีไปถือพันธบัตร (IEF) แปลว่ากลัว (Risk OFF)")

        rs_val = df['RS'].iloc[-1]
        rs_t = f" | **Relative Strength:** {'🟢 ชนะตลาด' if rs_val > 0 else '🔴 อ่อนแอกว่าตลาด'} ({rs_val:.2f}%)" if not np.isnan(rs_val) else ""
        if matrix: st.info(f"🔮 **ทิศทาง {tf_option}:** {matrix['tr']} | **เป้าหมาย (Harmonic Matrix):** {matrix['l']:,.2f} - {matrix['u']:,.2f} {rs_t}")
        
        c_l, c_r = st.columns([7, 3])
        with c_l:
            fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.45, 0.15, 0.2, 0.2])
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name="Price"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['Trendline'], line=dict(color='rgba(255, 255, 255, 0.4)', dash='dot', width=2), name="Trend"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['E20'], line=dict(color='#00E676', width=2.5), name="EMA 20"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['E50'], line=dict(color='#FF6D00', width=2.5), name="EMA 50"), row=1, col=1)
            
            # วาดเส้นต้นทุนจริงลงในกราฟ
            if actual_cost > 0: fig.add_hline(y=actual_cost, line_dash="dash", line_color="cyan", annotation_text="ต้นทุนเฉลี่ย", row=1, col=1)
            
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
            price_diff = last_p - prev_p
            pct_diff = (price_diff / prev_p) * 100 if prev_p > 0 else 0
            st.metric("ราคาปัจจุบัน", f"${last_p:,.2f}", f"{price_diff:,.2f} ({pct_diff:,.2f}%)")
            st.markdown(f"<div style='margin-top: -15px; margin-bottom: 20px; font-size: 0.9em; color: #a0aab2;'>📅 {current_date} &nbsp; 🕒 {current_time} น.</div>", unsafe_allow_html=True)
            
            # ใช้ต้นทุนจริงจากพอร์ตมาคำนวณจุดตัดขาดทุน
            if actual_cost > 0:
                pl = ((last_p - actual_cost) / actual_cost) * 100
                st.write(f"**กำไร/ขาดทุน (อ้างอิงต้นทุน):** {pl:.2f}%")
                sl = df['E50'].iloc[-1] * 0.99 if actual_cost == 0 else actual_cost * 0.92
                st.error(f"🛡️ **จุดหนี (Stop Loss): ${sl:.2f}**")
                ra = t_cap * (r_pct / 100); rps = last_p - sl
                if rps > 0: st.success(f"🧮 **ซื้อเพิ่มได้สูงสุด:** {ra/rps:.2f} หุ้น")
            
            st.markdown("---")
            st.subheader("🤖 สรุปสัญญาณเทคนิค")
            tr_s = "🟢 ขาขึ้น" if is_uptrend else "🔴 ขาลง"
            mc_s = "🟢 แรงซื้อได้เปรียบ" if is_bullish_macd else "🔴 แรงขายกดดัน"
            rsi_s = "🔴 ซื้อมากไป" if rsi_val >= 70 else "🟢 ขายมากไป" if rsi_val <= 30 else "🟡 กลางๆ"
            st.write(f"**เทรนด์ (EMA 50):** {tr_s}")
            st.write(f"**รอบสวิง (MACD):** {mc_s}")
            st.write(f"**แรงซื้อขาย (RSI):** {rsi_s}")
            st.markdown("---")
            st.subheader("🚧 แนวรับ-ต้าน")
            st.write(f"**ต้าน:** {df['High'].tail(20).max():.2f}")
            st.write(f"**รับ:** {df['E50'].iloc[-1]:.2f}")
    else:
        st.warning(f"⚠️ ไม่สามารถดึงข้อมูลกราฟของหุ้น **'{ticker}'** ได้ในขณะนี้ค่ะ")
        st.info('''
        💡 **สาเหตุที่เป็นไปได้ และวิธีแก้ไข:**
        1. **พิมพ์ชื่อย่อหุ้นผิด:** หรือหุ้นตัวนี้ไม่มีข้อมูลในฐานข้อมูลของ Yahoo Finance
        2. **อินเทอร์เน็ตขัดข้อง (Cache ค้าง):** แนะนำให้กดปุ่ม **'🔄 ดึงข้อมูลเรียลไทม์เดี๋ยวนี้'** ที่เมนูด้านซ้ายเพื่อล้างแคช
        3. **เซิร์ฟเวอร์ถูกบล็อกชั่วคราว:** ลองเปลี่ยนเป็นหุ้นยอดฮิต (เช่น AAPL) หากยังดึงไม่ได้เหมือนกัน ให้รอสักพักแล้วลองใหม่ค่ะ
        ''')

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
                except Exception as e: st.error("⚠️ ไม่สามารถส่งข้อมูลได้ กรุณาตรวจสอบว่าสร้างชีต 'Feedback' แล้วหรือยังคะ")

# ==========================================
# หน้า 2 & 3: บัญชี พอร์ตโฟลิโอ และภาษี
# ==========================================
if st.session_state["logged_in"]:
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
        h2.download_button(label="📥 โหลดข้อมูล (Excel/CSV)", data=csv_ledger, file_name=f"Trade_Ledger_{datetime.now().strftime('%Y%m%d')}.csv", mime='text/csv', use_container_width=True)
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
        if not ed_l.equals(st.session_state.trade_ledger):
            ed_l = clean_df_types(ed_l)
            sorted_ed_l, _, _, n_rb, _ = calculate_stats(ed_l)
            st.session_state.trade_ledger = sorted_ed_l; st.rerun()
        if st.button("💾 บันทึกข้อมูลบัญชีขึ้น Cloud", type="primary", use_container_width=True):
            save_df_to_sheet("Ledger", st.session_state.trade_ledger); st.success("บันทึกสำเร็จ! ข้อมูลปลอดภัย 100%")

        st.markdown("---")
        st.subheader("📊 พอร์ตโฟลิโอปัจจุบัน (Auto Real-Time Mark to Market)")
        live_fx = get_live_fx()
        st.info(f"💱 **อัตราแลกเปลี่ยนตลาดโลก ณ วินาทีนี้ (USD/THB):** ฿{live_fx:.4f} ต่อ 1 ดอลลาร์")
        port_summary, total_invested = [], 0.0
        for t, data in holdings.items():
            if data["shares"] > 0.001:
                avg_c = data["total_cost"] / data["shares"]
                port_summary.append({"Ticker": t, "Cost_Price": avg_c, "Shares": data["shares"], "Total_Cost": data["total_cost"]})
                total_invested += data["total_cost"]
        if len(port_summary) > 0:
            current_port_df = pd.DataFrame(port_summary)
            results, total_v = [], 0.0
            active_tickers = current_port_df["Ticker"].tolist()
            with st.spinner("⏳ กำลังวิ่งไปเก็บราคาล่าสุดของหุ้นทุกตัวในพอร์ต..."):
                batch_prices = get_batch_live_prices(active_tickers)
                for _, row in current_port_df.iterrows():
                    t, avg_cost, sh, t_cost = row["Ticker"], row["Cost_Price"], row["Shares"], row["Total_Cost"]
                    curr_p = batch_prices.get(t, avg_cost)
                    val = curr_p * sh
                    profit_usd, profit_pct = val - t_cost, (val - t_cost) / t_cost * 100 if t_cost > 0 else 0
                    results.append({"หุ้น": t, "จำนวนหุ้น": sh, "ต้นทุนเฉลี่ย": avg_cost, "ราคาปัจจุบัน": curr_p, "กำไร/ขาดทุน ($)": profit_usd, "กำไร/ขาดทุน (฿)": profit_usd * live_fx, "% เปลี่ยนแปลง": profit_pct, "มูลค่ารวม": val})
                    total_v += val
            p1, p2, p3, p4 = st.columns(4)
            p1.metric("มูลค่าหุ้นรวม ($)", f"${total_v:,.2f}")
            p2.metric("ต้นทุนหุ้นทั้งหมด ($)", f"${total_invested:,.2f}")
            total_pl_usd = total_v - total_invested
            p3.metric("กำไร/ขาดทุนรวม ($)", f"${total_pl_usd:,.2f}", f"{(total_pl_usd / total_invested * 100 if total_invested > 0 else 0):.2f}%")
            p4.metric("กำไร/ขาดทุนรวม (฿)", f"฿{total_pl_usd * live_fx:,.2f}", "แปลงจาก USD อัตโนมัติ")
            res_df = pd.DataFrame(results)
            chart_col1, chart_col2 = st.columns(2)
            with chart_col1:
                fig_pie = go.Figure(data=[go.Pie(labels=res_df['หุ้น'], values=res_df['มูลค่ารวม'], hole=.4)])
                fig_pie.update_layout(title="สัดส่วนพอร์ต (Allocation)", template="plotly_dark", height=350, margin=dict(t=50, b=0, l=0, r=0))
                st.plotly_chart(fig_pie, use_container_width=True)
            with chart_col2:
                bar_colors = ['#00E676' if val >= 0 else '#FF5252' for val in res_df['กำไร/ขาดทุน ($)']]
                fig_bar = go.Figure(data=[go.Bar(x=res_df['หุ้น'], y=res_df['กำไร/ขาดทุน ($)'], marker_color=bar_colors)])
                fig_bar.update_layout(title="กำไร/ขาดทุนรายตัว (P/L)", template="plotly_dark", height=350, margin=dict(t=50, b=0, l=0, r=0))
                st.plotly_chart(fig_bar, use_container_width=True)
            def color_profit(val): return f'color: {"#FF5252" if val < 0 else "#00E676"}; font-weight: bold;'
            styled_res = res_df.style.map(color_profit, subset=["กำไร/ขาดทุน ($)", "กำไร/ขาดทุน (฿)", "% เปลี่ยนแปลง"]).format({"จำนวนหุ้น": "{:,.4f}", "ต้นทุนเฉลี่ย": "${:,.4f}", "ราคาปัจจุบัน": "${:,.4f}", "กำไร/ขาดทุน ($)": "${:,.2f}", "กำไร/ขาดทุน (฿)": "฿{:,.2f}", "% เปลี่ยนแปลง": "{:,.2f}%", "มูลค่ารวม": "${:,.2f}"})
            st.dataframe(styled_res, use_container_width=True)
            csv_port = convert_df_to_csv(res_df)
            st.download_button(label="📥 ดาวน์โหลดพอร์ตโฟลิโอ (Excel/CSV)", data=csv_port, file_name=f"Portfolio_{datetime.now().strftime('%Y%m%d')}.csv", mime='text/csv')
        else: st.info("ว่างเปล่า (ยังไม่มีหุ้นในพอร์ตค่ะ)")

    with tab_list[2]:
        t1, t2 = st.columns([8, 2])
        t1.subheader("🧾 ระบบประเมินภาษีสรรพากร ภ.ง.ด. 90")
        tax_idx = st.session_state.trade_ledger['Action'].isin(["นำเงินออกนอกประเทศ (Outward)", "นำเงินเข้าประเทศไทย (Inward)", "รับเงินปันผล (Dividend)"])
        tax_v = st.session_state.trade_ledger[tax_idx].copy()
        tax_v["Out_USD"] = np.where(tax_v["Action"] == "นำเงินออกนอกประเทศ (Outward)", tax_v["Amount_USD"], 0.0)
        tax_v["In_USD"] = np.where(tax_v["Action"].isin(["นำเงินเข้าประเทศไทย (Inward)", "รับเงินปันผล (Dividend)"]), tax_v["Amount_USD"], 0.0)
        tax_v["FX_Rate"] = pd.to_numeric(tax_v["FX_Rate"], errors='coerce').fillna(0.0)
        tax_v["WHT_USD"] = pd.to_numeric(tax_v["WHT_USD"], errors='coerce').fillna(0.0)
        tax_v["Out_THB"], tax_v["In_THB"] = tax_v["Out_USD"] * tax_v["FX_Rate"], tax_v["In_USD"] * tax_v["FX_Rate"]
        t_bals, c_t_bal = [], 0.0
        for i, r in tax_v.iterrows():
            c_t_bal += (r["Out_THB"] - r["In_THB"]); t_bals.append(c_t_bal)
        tax_v["Balance_THB"] = t_bals
        csv_tax = convert_df_to_csv(tax_v)
        t2.download_button(label="📥 โหลดตารางภาษี (Excel/CSV)", data=csv_tax, file_name=f"Tax_Report_{datetime.now().strftime('%Y%m%d')}.csv", mime='text/csv', use_container_width=True)
        ed_t = st.data_editor(tax_v, use_container_width=True, num_rows="fixed",
            column_order=["Date", "Out_USD", "In_USD", "FX_Rate", "Out_THB", "In_THB", "Balance_THB", "WHT_USD", "Ref_Doc"],
            column_config={"Date": st.column_config.Column("วันที่", disabled=True), "Out_USD": st.column_config.NumberColumn("โอนออก ($)", disabled=True), "In_USD": st.column_config.NumberColumn("นำเข้า ($)", disabled=True), "FX_Rate": st.column_config.NumberColumn("เรทเงิน (บาท/$)", format="%.4f", step=0.0001), "Out_THB": st.column_config.NumberColumn("โอนออก (฿)", disabled=True), "In_THB": st.column_config.NumberColumn("นำเข้า (฿)", disabled=True), "WHT_USD": st.column_config.NumberColumn("ภาษีหัก ตปท. ($)", format="%.2f", step=0.01), "Balance_THB": st.column_config.NumberColumn("เงินต้นคงเหลือ (฿)", disabled=True), "Ref_Doc": "หมายเหตุ"})
        if not ed_t[["FX_Rate", "WHT_USD", "Ref_Doc"]].equals(tax_v[["FX_Rate", "WHT_USD", "Ref_Doc"]]):
            ed_t = clean_df_types(ed_t)
            st.session_state.trade_ledger.loc[tax_idx, "FX_Rate"] = ed_t["FX_Rate"].values
            st.session_state.trade_ledger.loc[tax_idx, "WHT_USD"] = ed_t["WHT_USD"].values
            st.session_state.trade_ledger.loc[tax_idx, "Ref_Doc"] = ed_t["Ref_Doc"].values; st.rerun()
        if st.button("💾 บันทึกอัตราแลกเปลี่ยนลง Cloud", type="primary", use_container_width=True): save_df_to_sheet("Ledger", st.session_state.trade_ledger); st.success("บันทึกสำเร็จ!")
        sum_out_thb, sum_in_thb = tax_v["Out_THB"].sum(), tax_v["In_THB"].sum()
        sum_wht_thb, net_tax_gain = (tax_v["WHT_USD"] * tax_v["FX_Rate"]).sum(), max(0, sum_in_thb - sum_out_thb)
        st.markdown("---")
        cf1, cf2, cf3 = st.columns(3)
        cf1.metric("📤 ยอดโอนออกรวม", f"฿{sum_out_thb:,.2f}"); cf2.metric("📥 ยอดนำกลับรวม", f"฿{sum_in_thb:,.2f}"); cf3.metric("🚨 ส่วนเกินทุนสุทธิ", f"฿{net_tax_gain:,.2f}", "หักล้างเงินต้นแล้ว", delta_color="inverse")
        st.markdown("---")
        c1, c2, c3 = st.columns(3)
        with c1: tax_year = st.selectbox("📅 เลือกปีภาษี", ["2567 (2024)", "2568 (2025)", "2569 (2026)"])
        with c2: is_resident = st.radio("อาศัยอยู่ในไทยเกิน 180 วัน?", ["เกิน 180 วัน", "ไม่ถึง 180 วัน"])
        with c3: other_income = st.number_input("รายได้ประจำต่อปี (บาท)", min_value=0.0, value=500000.0, step=50000.0)
        with st.expander("📝 บันทึกค่าลดหย่อนส่วนบุคคล", expanded=True):
            col_d1, col_d2 = st.columns(2)
            spouse_deduction = col_d1.checkbox("มีคู่สมรส (ไม่มีรายได้)")
            children_count = col_d2.number_input("จำนวนบุตร (คนละ 30,000)", min_value=0, step=1)
            c_inv1, c_inv2, c_inv3 = st.columns(3)
            life_ins = c_inv1.number_input("เบี้ยประกันชีวิต", min_value=0.0, step=5000.0)
            health_ins = c_inv2.number_input("เบี้ยประกันสุขภาพ", min_value=0.0, step=5000.0)
            pvd = c_inv3.number_input("กองทุน PVD / กบข.", min_value=0.0, step=5000.0)
            ssf = c_inv1.number_input("ซื้อ SSF", min_value=0.0, step=5000.0)
            rmf = c_inv2.number_input("ซื้อ RMF", min_value=0.0, step=5000.0)
            donate = c_inv3.number_input("เงินบริจาค", min_value=0.0, step=1000.0)
        total_deductions = min(other_income * 0.5, 100000.0) + 60000.0 + (60000.0 if spouse_deduction else 0.0) + (children_count * 30000.0) + min(life_ins + min(health_ins, 25000.0), 100000.0) + min(ssf + rmf + pvd, 500000.0) + donate
        if st.button(f"📊 คำนวณภาษีสุทธิ ปี {tax_year}", type="primary", use_container_width=True):
            if "ไม่ถึง" in is_resident: st.success("🎉 ได้รับยกเว้นภาษี")
            elif net_tax_gain <= 0: st.success("🎉 ยังไม่มีกำไรส่วนเกิน ไม่ต้องเสียภาษีค่ะ")
            else:
                net_inc, net_inc_without = max(0, (other_income + net_tax_gain) - total_deductions), max(0, other_income - total_deductions)
                def calc_tax(n):
                    if n > 5000000: return (n-5000000)*0.35 + 1265000
                    if n > 2000000: return (n-2000000)*0.30 + 365000
                    if n > 1000000: return (n-1000000)*0.25 + 115000
                    if n > 750000: return (n-750000)*0.20 + 65000
                    if n > 500000: return (n-500000)*0.15 + 27500
                    if n > 300000: return (n-300000)*0.10 + 7500
                    if n > 150000: return (n-150000)*0.05
                    return 0
                tax_raw = calc_tax(net_inc) - calc_tax(net_inc_without)
                st.subheader(f"ผลการคำนวณ ภ.ง.ด. 90 (ประจำปี {tax_year})")
                r1, r2 = st.columns(2)
                r1.metric("ภาษีจากพอร์ต ตปท.", f"฿{tax_raw:,.2f}"); r2.metric("🚨 ภาษีที่ต้องจ่ายเพิ่มจริง", f"฿{max(0, tax_raw - sum_wht_thb):,.2f}")

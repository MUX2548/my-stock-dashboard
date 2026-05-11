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
        st.error(f"❌ บันทึกข้อมูลไม่สำเร็จ: {e}")
        return False

# ==========================================
# 3. 🧮 ลอจิกการคำนวณ (Business Logic)
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
        
        if action == "นำเงินออกนอกประเทศ (Outward)": cb += a; stat["outward"] += a
        elif action == "นำเงินเข้าประเทศไทย (Inward)": cb -= a; stat["inward"] += a
        elif action == "รับเงินปันผล (Dividend)": cb += a; stat["dividend"] += a
        elif action == "กำไรจากการขายหุ้น (Profit)": cb += a
        elif action == "ซื้อหุ้น (Buy)" and ticker:
            cb -= (p * s); stat["bought"] += (p * s)
            if ticker not in hld: hld[ticker] = {"shares": 0.0, "total_cost": 0.0}
            hld[ticker]["shares"] += s; hld[ticker]["total_cost"] += (p * s)
        elif action == "ขายหุ้น (Sell)" and ticker:
            cb += (p * s); stat["sold"] += (p * s)
            if ticker in hld and hld[ticker]["shares"] > 0:
                avg = hld[ticker]["total_cost"] / hld[ticker]["shares"]
                stat["realized_profit"] += (p * s) - (avg * s)
                hld[ticker]["shares"] -= s; hld[ticker]["total_cost"] -= (avg * s)
        r_bals.append(cb)
    
    df["Running_Balance"] = r_bals
    return df, cb, stat, hld

# ==========================================
# 4. 🌐 Financial Data Services
# ==========================================
@st.cache_data(ttl=60)
def load_pro_data(ticker_symbol, tf):
    stgs = {"1D (รายวัน)": {"p": "6mo", "i": "1d"}, "1W (รายสัปดาห์)": {"p": "2y", "i": "1wk"}, "1M (รายเดือน)": {"p": "5y", "i": "1mo"}}
    p, i = stgs[tf]["p"], stgs[tf]["i"]
    try:
        s = yf.Ticker(ticker_symbol)
        df = s.history(period=p, interval=i)
        if df.empty: return pd.DataFrame(), {}, None, None
        
        spy = yf.Ticker("^GSPC").history(period=p, interval=i)
        spy_trend, spy_price, vix_val = "N/A", 0.0, 20.0
        if not spy.empty:
            df['RS'] = (df['Close'].pct_change(10) - spy['Close'].pct_change(10)) * 100
            spy_price = spy['Close'].iloc[-1]
            spy_trend = "ขึ้น 📈" if spy_price > spy['Close'].ewm(span=50).mean().iloc[-1] else "ลง 📉"
        
        try: vix_val = yf.Ticker("^VIX").history(period="1d")['Close'].iloc[-1]
        except: pass

        # Technical Indicators
        df['E20'], df['E50'] = df['Close'].ewm(span=20).mean(), df['Close'].ewm(span=50).mean()
        df['RSI'] = 100 - (100 / (1 + (df['Close'].diff().where(df['Close'].diff() > 0, 0).ewm(alpha=1/14).mean() / 
                                        -df['Close'].diff().where(df['Close'].diff() < 0, 0).ewm(alpha=1/14).mean())))
        df['MACD'] = df['Close'].ewm(span=12).mean() - df['Close'].ewm(span=26).mean()
        df['Sig'] = df['MACD'].ewm(span=9).mean()
        df['Hist'] = df['MACD'] - df['Sig']
        
        last = df['Close'].iloc[-1]
        v = df['Close'].pct_change().tail(14).std()
        tr = "ขึ้น 📈" if last > df['E50'].iloc[-1] else "ลง 📉"
        mat = {"l": last * (1 - v*0.5), "u": last * (1 + v*1.0), "tr": tr}
        
        return df, s.info, mat, {"spy_trend": spy_trend, "spy_price": spy_price, "vix": vix_val}
    except: return pd.DataFrame(), {}, None, None

@st.cache_data(ttl=60)
def get_batch_live_prices(tickers):
    if not tickers: return {}
    try:
        data = yf.download(tickers, period="1d", group_by='ticker', progress=False)
        prices = {}
        if len(tickers) == 1:
            if not data.empty: prices[tickers[0]] = data['Close'].iloc[-1]
        else:
            for t in tickers:
                if t in data.columns.levels[0]: prices[t] = data[t]['Close'].iloc[-1]
        return prices
    except: return {}

@st.cache_data(ttl=60)
def get_live_fx():
    try: return yf.Ticker("USDTHB=X").history(period="1d")['Close'].iloc[-1]
    except: return 35.00

# ==========================================
# 5. Core Application Logic
# ==========================================
if "trade_ledger" not in st.session_state: st.session_state.trade_ledger = load_ledger_data()
if "logged_in" not in st.session_state: st.session_state["logged_in"] = False

# Sidebar
with st.sidebar:
    st.title("🛡️ Strategic Hub")
    if st.button("🔄 ดึงข้อมูลเรียลไทม์", use_container_width=True):
        st.cache_data.clear(); st.rerun()
    st.markdown("---")
    ticker = st.text_input("🔎 ชื่อหุ้น / ดัชนี", value="VKTX").upper()
    tf_option = st.radio("เลือกความละเอียด:", ["1D (รายวัน)", "1W (รายสัปดาห์)", "1M (รายเดือน)"])
    
    if not st.session_state["logged_in"]:
        pwd = st.text_input("🔑 Password", type="password")
        if st.button("🔓 Login", use_container_width=True):
            if pwd == st.secrets.get("app_password", "123456"):
                st.session_state["logged_in"] = True; st.rerun()
    else:
        if st.button("🚪 Logout", use_container_width=True):
            st.session_state["logged_in"] = False; st.rerun()

# --- Load Data ---
with st.spinner("⏳ Loading Data..."):
    df_chart, info, matrix, market = load_pro_data(ticker, tf_option)

tabs = ["📊 วิเคราะห์กราฟ", "💼 บัญชีและพอร์ต", "🧾 ภาษีสรรพากร"] if st.session_state["logged_in"] else ["📊 วิเคราะห์กราฟ"]
tab_list = st.tabs(tabs)

# --- TAB 1: Chart Analysis ---
with tab_list[0]:
    if not df_chart.empty:
        st.markdown(f"## 📈 {ticker} | Price: ${df_chart['Close'].iloc[-1]:,.2f}")
        if market:
            m1, m2, m3 = st.columns(3)
            m1.metric("S&P 500", f"{market['spy_price']:,.2f}", market['spy_trend'])
            m2.metric("VIX Index", f"{market['vix']:.2f}", "Risk-OFF" if market['vix'] > 25 else "Risk-ON")
            m3.info(f"🔮 Harmonic: {matrix['l']:,.2f} - {matrix['u']:,.2f}")
        
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
        fig.add_trace(go.Candlestick(x=df_chart.index, open=df_chart['Open'], high=df_chart['High'], low=df_chart['Low'], close=df_chart['Close'], name="Price"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['E50'], line=dict(color='#FF6D00'), name="EMA 50"), row=1, col=1)
        fig.add_trace(go.Bar(x=df_chart.index, y=df_chart['Hist'], name="MACD"), row=2, col=1)
        fig.update_layout(template="plotly_dark", height=600, margin=dict(l=0,r=0,t=0,b=0), xaxis_rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True)
    else: st.warning("ไม่สามารถโหลดข้อมูลได้")

# --- TAB 2: Ledger & Portfolio ---
if st.session_state["logged_in"]:
    sorted_ledger, cb, l_stat, holdings = calculate_stats(st.session_state.trade_ledger)
    st.session_state.trade_ledger = sorted_ledger

    with tab_list[1]:
        st.subheader("💼 แดชบอร์ดกระแสเงินสด")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("📤 โอนออกสะสม", f"${l_stat['outward']:,.2f}")
        col2.metric("📥 นำกลับสะสม", f"${l_stat['inward']:,.2f}")
        col3.metric("📈 ต้นทุนหุ้นปัจจุบัน", f"${l_stat['bought'] - l_stat['sold']:,.2f}")
        col4.metric("💰 Cash Balance", f"${cb:,.2f}")

        st.markdown("---")
        with st.form("ledger_update"):
            ed_l = st.data_editor(st.session_state.trade_ledger, num_rows="dynamic", use_container_width=True)
            if st.form_submit_button("💾 บันทึกข้อมูลขึ้น Cloud", use_container_width=True):
                updated_df, _, _, _ = calculate_stats(ed_l)
                st.session_state.trade_ledger = updated_df
                if save_df_to_sheet("Ledger", updated_df): 
                    st.success("บันทึกสำเร็จ!"); time.sleep(1); st.rerun()

        st.markdown("---")
        st.subheader("📊 พอร์ตโฟลิโอ Real-time")
        live_fx = get_live_fx()
        active_tickers = [t for t, d in holdings.items() if d["shares"] > 0.001]
        
        if active_tickers:
            prices = get_batch_live_prices(active_tickers)
            res_rows = []
            for t in active_tickers:
                sh, t_cost = holdings[t]["shares"], holdings[t]["total_cost"]
                curr_p = prices.get(t, t_cost/sh)
                val = curr_p * sh
                pl_usd = val - t_cost
                res_rows.append({"Ticker": t, "Shares": sh, "Cost": t_cost/sh, "Price": curr_p, "P/L $": pl_usd, "P/L %": (pl_usd/t_cost)*100 if t_cost>0 else 0, "Value $": val})
            
            res_df = pd.DataFrame(res_rows)
            st.dataframe(res_df.style.format("{:,.2f}"), use_container_width=True)
            
            with st.expander("⚖️ Portfolio Rebalancing"):
                rebal = res_df[["Ticker", "Value $"]].copy()
                rebal["Target %"] = 0.0
                ed_re = st.data_editor(rebal, use_container_width=True)
                if ed_re["Target %"].sum() > 0:
                    total_v = res_df["Value $"].sum()
                    ed_re["Diff $"] = (total_v * (ed_re["Target %"]/100)) - ed_re["Value $"]
                    st.write("ส่วนต่างที่ต้องปรับปรุง:")
                    st.dataframe(ed_re[["Ticker", "Diff $"]].style.format("{:,.2f}"))

    # --- TAB 3: Tax Section (Full) ---
    with tab_list[2]:
        st.subheader("🧾 ระบบประเมินภาษีสรรพากร ภ.ง.ด. 90")
        tax_idx = st.session_state.trade_ledger['Action'].isin(["นำเงินออกนอกประเทศ (Outward)", "นำเงินเข้าประเทศไทย (Inward)", "รับเงินปันผล (Dividend)"])
        tax_v = st.session_state.trade_ledger[tax_idx].copy()
        
        tax_v["Out_USD"] = np.where(tax_v["Action"]=="นำเงินออกนอกประเทศ (Outward)", tax_v["Amount_USD"], 0)
        tax_v["In_USD"] = np.where(tax_v["Action"].isin(["นำเงินเข้าประเทศไทย (Inward)", "รับเงินปันผล (Dividend)"]), tax_v["Amount_USD"], 0)
        tax_v["Out_THB"] = tax_v["Out_USD"] * tax_v["FX_Rate"]
        tax_v["In_THB"] = tax_v["In_USD"] * tax_v["FX_Rate"]
        
        with st.form("tax_update"):
            ed_t = st.data_editor(tax_v, use_container_width=True)
            if st.form_submit_button("💾 บันทึกข้อมูลภาษี", use_container_width=True):
                st.session_state.trade_ledger.loc[tax_idx, ["FX_Rate", "WHT_USD"]] = ed_t[["FX_Rate", "WHT_USD"]].values
                save_df_to_sheet("Ledger", st.session_state.trade_ledger); st.rerun()

        sum_out, sum_in = tax_v["Out_THB"].sum(), tax_v["In_THB"].sum()
        net_gain = max(0, sum_in - sum_out)
        
        st.markdown("---")
        c1, c2, c3 = st.columns(3)
        c1.metric("โอนออกรวม", f"฿{sum_out:,.2f}")
        c2.metric("นำกลับรวม", f"฿{sum_in:,.2f}")
        c3.metric("ส่วนเกินทุน (กำไร)", f"฿{net_gain:,.2f}", delta_color="inverse")

        st.markdown("---")
        other_inc = st.number_input("รายได้ประจำอื่นๆ (บาท)", value=500000.0)
        with st.expander("📝 ลดหย่อนส่วนบุคคล"):
            kids = st.number_input("จำนวนบุตร", value=0)
            ins = st.number_input("ประกันชีวิต/สุขภาพ", value=0.0)
            fund = st.number_input("SSF/RMF/PVD", value=0.0)

        if st.button("📊 คำนวณภาษีสุทธิ", type="primary", use_container_width=True):
            deduct = 60000 + (kids*30000) + min(ins, 100000) + min(fund, 500000) + 100000 # รวมค่าใช้จ่าย 50%
            net_total = max(0, (other_inc + net_gain) - deduct)
            
            def calc_tier(n):
                if n > 5000000: return (n-5000000)*0.35 + 1265000
                if n > 2000000: return (n-2000000)*0.30 + 365000
                if n > 1000000: return (n-1000000)*0.25 + 115000
                if n > 750000: return (n-750000)*0.20 + 65000
                if n > 500000: return (n-500000)*0.15 + 27500
                if n > 300000: return (n-300000)*0.10 + 7500
                if n > 150000: return (n-150000)*0.05
                return 0
            
            tax_bill = calc_tier(net_total) - calc_tier(max(0, other_inc - deduct))
            st.subheader(f"ภาษีที่ต้องจ่ายเพิ่มจากพอร์ต: ฿{tax_bill:,.2f}")

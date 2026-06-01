import json
import time
import os
import math
import urllib.parse
import requests
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from PIL import Image
from datetime import datetime, timezone, timedelta

# ==========================================
# 🎨 1. การตั้งค่าแบรนด์และสไตล์หน้าเพจ
# ==========================================
logo_path = "strategic_hub_logo.png"

if os.path.exists(logo_path):
    browser_icon = Image.open(logo_path)
    st.set_page_config(page_title="Strategic Hub 4.60", page_icon=browser_icon, layout="wide")
else:
    st.set_page_config(page_title="Strategic Hub 4.60", page_icon="📈", layout="wide")

st.markdown("""
    <style>
    .stButton>button { border-radius: 12px; font-weight: bold; transition: all 0.3s ease; border: 1px solid #4CAF50; }
    .stButton>button:hover { transform: translateY(-2px); box-shadow: 0 6px 15px rgba(76, 175, 80, 0.4); border-color: #4CAF50; }
    .stButton>button[data-baseweb="button"] { border-radius: 12px; }
    div[data-testid="stMetricValue"] { padding-bottom: 0px; }
    .stSpinner > div > div { border-top-color: #deff9a !important; }
    [data-testid="stSidebar"] { background-color: #0e1117; }
    [data-testid="stDataFrame"] { border-radius: 10px; overflow: hidden; }
    
    [data-testid="stMetricValue"] { font-size: 1.5rem !important; white-space: pre-wrap !important; word-break: break-word !important; }
    [data-testid="stMetricDelta"] > div { white-space: pre-wrap !important; word-break: break-word !important; }
    
    .pro-box { background-color: #1E1E1E; border-radius: 8px; padding: 15px; margin-bottom: 15px; border: 1px solid #333; }
    .pro-title { font-weight: bold; font-size: 1.1em; margin-bottom: 10px; border-bottom: 1px solid #444; padding-bottom: 5px; }
    .pro-row { display: flex; justify-content: space-between; margin-bottom: 5px; font-size: 0.95em; }
    .c-red { color: #FF5252; } .c-green { color: #00E676; } .c-yellow { color: #FFD600; } .c-gray { color: #B0BEC5; }
    </style>
""", unsafe_allow_html=True)

tz_th = timezone(timedelta(hours=7))
current_date = datetime.now(tz_th).strftime("%d/%m/%Y")
current_time = datetime.now(tz_th).strftime("%H:%M:%S")

# ==========================================
# 🔐 2. การบริหารสถานะข้อมูลระบบ (Persistent Memory)
# ==========================================
if "current_ticker" not in st.session_state:
    st.session_state.current_ticker = "RKLB"
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if "radar_tickers" not in st.session_state:
    st.session_state.radar_tickers = [
        "ASTS", "RKLB", "NVTS", "IREN", "RGTI", "C", "TSLA", "PLTR", "ONDS", "OKLO", 
        "EOSE", "IONQ", "NOW", "MNDY", "ADBE", "CRWD", "AMKR", "NVDA", "MSFT", "GOOGL"
    ]

@st.cache_resource(ttl=3600)
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
        if col in df_clean.columns: df_clean[col] = pd.to_numeric(df_clean[col], errors='coerce').fillna(0.0)
    str_cols = ["Date", "Action", "Ticker", "Ref_Doc"]
    for col in str_cols:
        if col in df_clean.columns: df_clean[col] = df_clean[col].fillna("").astype(str).replace(["None", "nan", "<NA>", "NaN"], "")
    return df_clean

def load_ledger_data():
    try:
        global sh
        ws = sh.worksheet("Ledger")
        records = ws.get_all_records()
        if not records:
            df = pd.DataFrame(columns=["Date", "Action", "Ticker", "Price", "Shares", "Amount_USD", "Running_Balance", "FX_Rate", "WHT_USD", "Ref_Doc"])
            return clean_df_types(df)
        df = pd.DataFrame(records)
        df.replace(["", "None", "nan", None], np.nan, inplace=True)
        df.dropna(how="all", inplace=True)
    except: df = pd.DataFrame()
    req_cols = ["Date", "Action", "Ticker", "Price", "Shares", "Amount_USD", "Running_Balance", "FX_Rate", "WHT_USD", "Ref_Doc"]
    for col in req_cols:
        if col not in df.columns: df[col] = ""
    df = clean_df_types(df)
    if not df.empty and "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], format="%d/%m/%Y", errors="coerce").dt.strftime("%d/%m/%Y").replace("NaT", "")
    return df[req_cols]

def load_plans_data():
    req_cols = ["Date", "Ticker", "Entry", "Stop_Loss", "Take_Profit", "Risk_Budget", "Max_Shares", "Note"]
    try:
        global sh
        ws = sh.worksheet("Trading_Plans")
        records = ws.get_all_records()
        if records:
            df = pd.DataFrame(records)
            for col in req_cols:
                if col not in df.columns: df[col] = ""
            return df[req_cols]
    except gspread.exceptions.WorksheetNotFound:
        try:
            ws = sh.add_worksheet(title="Trading_Plans", rows="1000", cols="10")
            ws.append_row(req_cols)
            return pd.DataFrame(columns=req_cols)
        except: pass
    except: pass
    return pd.DataFrame(columns=req_cols)

def save_df_to_sheet(worksheet_name, df):
    global sh
    try: ws = sh.worksheet(worksheet_name)
    except:
        sh = init_connection()
        try: ws = sh.worksheet(worksheet_name)
        except gspread.exceptions.WorksheetNotFound:
            ws = sh.add_worksheet(title=worksheet_name, rows="1000", cols="15")
    try:
        ws.clear()
        clean_df = df.copy()
        clean_df = clean_df.astype(str).replace(["nan", "None", "<NA>", "NaN"], "")
        data_list = [clean_df.columns.values.tolist()] + clean_df.values.tolist()
        ws.update(values=data_list, range_name='A1')
        return True
    except Exception as e:
        st.error(f"❌ เกิดข้อผิดพลาดขณะเขียนข้อมูลลง Cloud: {e}")
        return False

if "trade_ledger" not in st.session_state: st.session_state.trade_ledger = load_ledger_data()
if "trading_plans" not in st.session_state: st.session_state.trading_plans = load_plans_data()

def log_visitor():
    try:
        ws = sh.worksheet("Visitor_Log")
        if "has_logged_visit" not in st.session_state:
            ws.append_row([datetime.now(tz_th).strftime("%d/%m/%Y %H:%M:%S")])
            st.session_state.has_logged_visit = True
        return len(ws.col_values(1))
    except Exception: return "N/A"

visitor_count = log_visitor()

# ==========================================
# 📊 3. ลอจิกบัญชี & ฟังก์ชันคำนวณระบบตลาด
# ==========================================
def calculate_stats(df_input):
    df = clean_df_types(df_input)
    if not df.empty and "Date" in df.columns:
        df["Date_Temp"] = pd.to_datetime(df["Date"], format="%d/%m/%Y", errors="coerce")
        df = df.sort_values(by="Date_Temp").drop(columns=["Date_Temp"]).reset_index(drop=True)
    cb = 0.0
    stat = {"outward": 0.0, "inward": 0.0, "bought": 0.0, "sold": 0.0, "dividend": 0.0, "realized_profit": 0.0}
    r_bals, hld = [], {}
    df = df[~df['Action'].isin(['None', '', 'nan', 'กำไรจากการขายหุ้น (Profit)'])].copy().reset_index(drop=True)
    for idx, row in df.iterrows():
        action = str(row.get("Action", "")).strip()
        ticker_item = str(row.get("Ticker", "")).strip().upper()
        p, s = float(row.get("Price", 0.0)), float(row.get("Shares", 0.0))
        manual_amount = float(row.get("Amount_USD", 0.0))
        trade_value = p * s
        a = manual_amount if manual_amount > 0 and action not in ["ซื้อหุ้น (Buy)", "ขายหุ้น (Sell)"] else trade_value
        if action == "นำเงินออกนอกประเทศ (Outward)": cb += a; stat["outward"] += a
        elif action == "นำเงินเข้าประเทศไทย (Inward)": cb -= a; stat["inward"] += a
        elif action == "รับเงินปันผล (Dividend)": cb += a; stat["dividend"] += a
        elif action == "ซื้อหุ้น (Buy)" and ticker_item:
            cb -= trade_value; stat["bought"] += trade_value
            if ticker_item not in hld: hld[ticker_item] = {"shares": 0.0, "total_cost": 0.0}
            hld[ticker_item]["shares"] += s; hld[ticker_item]["total_cost"] += trade_value
        elif action == "ขายหุ้น (Sell)" and ticker_item:
            cb += trade_value; stat["sold"] += trade_value
            if ticker_item in hld and hld[ticker_item]["shares"] > 0:
                avg_cost = hld[ticker_item]["total_cost"] / hld[ticker_item]["shares"]
                cogs = avg_cost * s
                realized_pl = trade_value - cogs
                stat["realized_profit"] += realized_pl
                hld[ticker_item]["shares"] -= s; hld[ticker_item]["total_cost"] -= cogs
                old_ref = str(row.get("Ref_Doc", "")).replace("nan", "")
                if "P/L:" not in old_ref: df.at[idx, "Ref_Doc"] = f"P/L: ${realized_pl:.2f} | {old_ref}"
        r_bals.append(cb)
    df["Running_Balance"] = r_bals
    return df, cb, stat, r_bals, hld

@st.cache_data
def convert_df_to_csv(df): return df.to_csv(index=False).encode('utf-8-sig')

@st.cache_data(ttl=86400)
def translate_to_thai(text):
    if not text or text == 'N/A': return "ไม่มีข้อมูล"
    try:
        short_text = text[:350]
        if '.' in short_text: short_text = short_text.rsplit('.', 1)[0] + '.'
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=th&dt=t&q={urllib.parse.quote(short_text)}"
        res = requests.get(url, timeout=5)
        return "".join([s[0] for s in res.json()[0]])
    except: return short_text + "..."

@st.cache_data(ttl=60)
def load_pro_data(ticker_symbol, tf):
    stgs = {"1D (รายวัน)": {"p": "6mo", "i": "1d"}, "1W (รายสัปดาห์)": {"p": "2y", "i": "1wk"}, "1M (รายเดือน)": {"p": "5y", "i": "1mo"}}
    p, i = stgs[tf]["p"], stgs[tf]["i"]
    
    df = pd.DataFrame()
    for attempt in range(3):
        try:
            s = yf.Ticker(ticker_symbol)
            df = s.history(period=p, interval=i)
            if df.empty:
                df = yf.download(ticker_symbol, period=p, interval=i, progress=False)
            if not df.empty:
                df = df.dropna(subset=['Close'])
                if not df.empty:
                    break
        except Exception:
            pass
        time.sleep(1.5)
        
    if df.empty: return pd.DataFrame(), {}, None, None, {}
    
    try:
        info = s.info
        en_summary = info.get('longBusinessSummary', 'N/A')
        th_summary = translate_to_thai(en_summary)
        
        market_signal = {"spy_trend": "N/A", "spy_price": 0.0, "vix": 0.0, "vix_ts": 0.0, "smart_money": "N/A"}
        try:
            spy = yf.Ticker("^GSPC").history(period=p, interval=i)
            if not spy.empty:
                df['RS'] = (df['Close'].pct_change(10) - spy['Close'].pct_change(10)) * 100
                spy_p = spy['Close'].iloc[-1]
                market_signal["spy_price"] = float(spy_p)
                market_signal["spy_trend"] = "ขึ้น 📈" if spy_p > spy['Close'].ewm(span=50).mean().iloc[-1] else "ลง 📉"
        except: df['RS'] = 0
        try:
            vix = yf.Ticker("^VIX").history(period="1mo")
            if not vix.empty: market_signal["vix"] = float(vix['Close'].iloc[-1])
            vix3m = yf.Ticker("^VIX3M").history(period="1mo")
            if not vix3m.empty and market_signal["vix"] > 0: market_signal["vix_ts"] = float(market_signal["vix"] / vix3m['Close'].iloc[-1])
        except: pass
        try:
            hyg = yf.Ticker("HYG").history(period="6mo")['Close']
            ief = yf.Ticker("IEF").history(period="6mo")['Close']
            if not hyg.empty and not ief.empty:
                df_sm = pd.concat([hyg, ief], axis=1).dropna()
                df_sm.columns = ['HYG', 'IEF']
                hyg_ief_ratio = df_sm['HYG'] / df_sm['IEF']
                market_signal["smart_money"] = "Risk ON 🟢" if hyg_ief_ratio.iloc[-1] > hyg_ief_ratio.ewm(span=20).mean().iloc[-1] else "Risk OFF 🔴"
        except: pass
        
        earnings_date = "N/A"
        try:
            cal = s.calendar
            if isinstance(cal, dict) and 'Earnings Date' in cal:
                e_dates = cal['Earnings Date']
                if isinstance(e_dates, list) and len(e_dates) > 0:
                    earnings_date = e_dates[0].strftime("%d/%m/%Y")
            elif hasattr(s, 'get_earnings_dates'):
                e_df = s.get_earnings_dates(limit=1)
                if e_df is not None and not e_df.empty:
                    earnings_date = e_df.index[0].strftime("%d/%m/%Y")
        except: pass
        
        if earnings_date == "N/A":
            ts = info.get('earningsTimestamp')
            if ts: earnings_date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d/%m/%Y")
            else: earnings_date = "รอประกาศ"
        
        df['E10'] = df['Close'].ewm(span=10).mean()
        df['E25'] = df['Close'].ewm(span=25).mean()
        df['E50'] = df['Close'].ewm(span=50).mean()
        df['E200'] = df['Close'].ewm(span=200).mean()
        
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14).mean()
        df['RSI'] = 100 - (100 / (1 + gain/loss))
        df['MACD'] = df['Close'].ewm(span=12).mean() - df['Close'].ewm(span=26).mean()
        df['Sig'] = df['MACD'].ewm(span=9).mean()
        df['Hist'] = df['MACD'] - df['Sig']
        
        div_y = info.get('dividendYield', 0)
        fund = {
            "ps": f"{float(info.get('priceToSalesTrailing12Months', 0) or 0):.2f}", 
            "pe": f"{float(info.get('trailingPE', 0) or 0):.2f}", 
            "roe": f"{float(info.get('returnOnEquity', 0) or 0)*100:.2f}%",
            "rev_growth": f"{float(info.get('revenueGrowth', 0) or 0)*100:.2f}%",
            "dividend": f"{(float(div_y) * 100):.2f}%" if div_y else "ไม่มีปันผล",
            "earnings_date": earnings_date,
            "business_desc_th": th_summary,
            "industry": info.get('industry', 'N/A'),
            "sector": info.get('sector', 'N/A'),
            "location": f"{info.get('city', '')}, {info.get('country', '')}" if info.get('city', '') else info.get('country', ''),
            "website": info.get('website', '#'),
            "pe_val": float(info.get('trailingPE', 0) or 0),
            "roe_val": float(info.get('returnOnEquity', 0) or 0)
        }
        
        last = df['Close'].iloc[-1]
        v = df['Close'].pct_change().tail(14).std()
        tr = "ขึ้น 📈" if last > df['E50'].iloc[-1] else "ลง 📉"
        mat = {"l": last * (1 - v*1.0) if tr == "ลง 📉" else last * (1 - v*0.5), "u": last * (1 - v*0.5) if tr == "ลง 📉" else last * (1 + v*1.0), "tr": tr}
        
        atr_proxy = df['High'].tail(14).max() - df['Low'].tail(14).min()
        levels = {
            "r1": last + (atr_proxy * 0.5), "r2": last + (atr_proxy * 1.0), "r3": last + (atr_proxy * 1.5), "r4": last + (atr_proxy * 2.0),
            "s1": last - (atr_proxy * 0.5), "s2": last - (atr_proxy * 1.0), "s3": last - (atr_proxy * 1.5)
        }
        return df, fund, mat, market_signal, levels
    except Exception: 
        return pd.DataFrame(), {}, None, None, {}

@st.cache_data(ttl=60)
def get_batch_live_prices(tickers):
    if not tickers: return {}
    try:
        df = pd.DataFrame()
        for attempt in range(3):
            df = yf.download(tickers, period="1d", progress=False)
            if not df.empty: break
            time.sleep(1)
            
        prices = {}
        if len(tickers) == 1:
            if not df.empty and 'Close' in df.columns: prices[tickers[0]] = float(df['Close'].iloc[-1])
        elif 'Close' in df.columns:
            for t in tickers:
                if t in df['Close'].columns and pd.notna(df['Close'][t].iloc[-1]): prices[t] = float(df['Close'][t].iloc[-1])
        return prices
    except: return {}

@st.cache_data(ttl=60)
def get_live_fx():
    try: return yf.Ticker("USDTHB=X").history(period="1d")['Close'].iloc[-1]
    except: return 35.00

@st.cache_data(ttl=300)
def run_ai_screener(tickers):
    if not tickers: return pd.DataFrame()
    results = []
    for t in tickers:
        try:
            hist = yf.Ticker(t).history(period="6mo")
            if hist.empty: continue
            
            recent_prices = hist['Close'].tail(30).tolist()
            close = hist['Close'].iloc[-1]
            ema50 = hist['Close'].ewm(span=50).mean().iloc[-1]
            delta = hist['Close'].diff()
            gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14).mean()
            loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14).mean()
            rsi_val = (100 - (100 / (1 + gain/loss))).iloc[-1]
            macd = hist['Close'].ewm(span=12).mean() - hist['Close'].ewm(span=26).mean()
            sig = macd.ewm(span=9).mean()
            macd_val, sig_val = macd.iloc[-1], sig.iloc[-1]
            
            trend = "🟢 ขาขึ้น" if close > ema50 else "🔴 ขาลง"
            momentum = "🟢 บวก" if macd_val > sig_val else "🔴 ลบ"
            
            if close > ema50 and macd_val > sig_val and rsi_val < 65: action = "⭐ STRONG BUY (สะสม)"
            elif close < ema50 and macd_val > sig_val and rsi_val < 35: action = "⚡ SPECULATE (ลุ้นเด้ง)"
            elif close > ema50 and rsi_val >= 70: action = "🔥 OVERBOUGHT (แบ่งขาย)"
            else: action = "⏳ WAIT (รอดูทรง)"
                
            results.append({
                "หุ้น": t, "กราฟ 30 วัน": recent_prices, "ราคาล่าสุด": f"${close:.2f}", 
                "EMA50": f"${ema50:.2f}", "เทรนด์": trend, "โมเมนตัม": momentum, 
                "RSI": f"{rsi_val:.1f}", "คำแนะนำ AI": action
            })
        except: pass
    return pd.DataFrame(results)

# 🔮 ฟังก์ชันพยากรณ์ Monte Carlo (Pitbull Forecaster)
@st.cache_data(ttl=3600)
def run_monte_carlo(ticker_symbol, days_to_predict=30, simulations=100):
    try:
        hist = yf.Ticker(ticker_symbol).history(period="1y")
        if hist.empty: return None, 0, 0, 0, 0
        
        closes = hist['Close']
        daily_returns = closes.pct_change().dropna()
        
        mu = daily_returns.mean()
        sigma = daily_returns.std()
        
        last_price = closes.iloc[-1]
        
        simulation_df = pd.DataFrame()
        for x in range(simulations):
            count = 0
            price_series = []
            price = last_price
            
            for y in range(days_to_predict):
                if count == 251: break
                price = price * (1 + np.random.normal(mu, sigma))
                price_series.append(price)
                count += 1
            simulation_df[x] = price_series
            
        expected_price = simulation_df.iloc[-1].mean()
        upper_bound = simulation_df.iloc[-1].quantile(0.95)
        lower_bound = simulation_df.iloc[-1].quantile(0.05)
        
        return simulation_df, expected_price, upper_bound, lower_bound, last_price
    except:
        return None, 0, 0, 0, 0

# ==========================================
# 🎛️ 4. UI Layout: แถบเมนูด้านซ้าย (Sidebar)
# ==========================================
with st.sidebar:
    if os.path.exists(logo_path): st.image(logo_path, use_container_width=True)
    else: st.title("🛡️ Strategic Hub 4.60")
    
    if st.button("🔄 ดึงข้อมูลเรียลไทม์เดี๋ยวนี้", use_container_width=True): 
        st.cache_data.clear()
        st.rerun()
        
    st.info(f"👁️ ยอดผู้เข้าชม: {visitor_count} ครั้ง")
    st.markdown("---")
    
    ticker_input = st.text_input("🔎 ชื่อหุ้น / ดัชนี (ดูรายตัว)", value=st.session_state.current_ticker).upper().strip()
    
    if ticker_input != st.session_state.current_ticker and ticker_input != "":
        st.session_state.current_ticker = ticker_input
        st.rerun() 
        
    ticker = st.session_state.current_ticker
    
    tf_option = st.radio("เลือกความละเอียด:", ["1D (รายวัน)", "1W (รายสัปดาห์)", "1M (รายเดือน)"], index=0)
    st.markdown("---")
    st.subheader("🧮 คำนวณ (Public)")
    t_cap = st.number_input("เงินทุนรวม ($)", value=10000.0)
    r_pct = st.slider("ความเสี่ยงต่อไม้ (%)", 1.0, 5.0, 2.0)
    b_p = st.number_input("ต้นทุนสมมติ ($)", min_value=0.0, step=0.1)
    st.markdown("---")
    if not st.session_state["logged_in"]:
        pwd = st.text_input("🔑 รหัสผ่าน", type="password")
        if st.button("🔓 เข้าสู่ระบบ", use_container_width=True, type="primary"):
            if pwd == st.secrets.get("app_password", "123456"): 
                st.session_state["logged_in"] = True
                st.rerun()
            else: st.error("❌ รหัสผิด")
    else:
        st.success("✅ โหมดเจ้าของพอร์ต")
        if st.button("🚪 ออกจากระบบ", use_container_width=True): 
            st.session_state["logged_in"] = False
            st.rerun()

if not ticker:
    st.info("👈 กรุณาพิมพ์ชื่อหุ้นในช่องค้นหาด้านซ้ายมือ (เช่น RKLB หรือ TSLA) แล้วกด Enter บนแป้นพิมพ์ค่ะ")
    st.stop()

holdings = {}
if st.session_state["logged_in"]:
    sorted_df, cb, l_stat, r_bals, holdings = calculate_stats(st.session_state.trade_ledger)
    st.session_state.trade_ledger = sorted_df

with st.spinner(f"⏳ กำลังประมวลผลดึงข้อมูลสดจากตลาด..."):
    df, fund, matrix, market_signal, levels = load_pro_data(ticker, tf_option)

tabs_list = ["📊 วิเคราะห์รายตัว", "🔬 หาจุดเข้าซื้อ (Technical)", "🎯 เรดาร์สแกนหุ้น"]
if st.session_state["logged_in"]: 
    tabs_list.extend(["💼 บัญชีลงทุน", "🧾 ระบบภาษี", "🔮 พิทบูลพยากรณ์", "📝 แผนการเทรด"])
tabs = st.tabs(tabs_list)

# ==========================================
# หน้า 1: วิเคราะห์กราฟรายตัว (ภาพรวมหลัก)
# ==========================================
with tabs[0]:
    if not df.empty:
        last_candle_date = df.index[-1].strftime("%d/%m/%Y")
        last_p = df['Close'].iloc[-1]
        prev_p = df['Close'].iloc[-2] if len(df) > 1 else last_p
        rsi_val = df['RSI'].iloc[-1]
        is_uptrend = last_p > df['E50'].iloc[-1]
        is_bullish_macd = df['MACD'].iloc[-1] > df['Sig'].iloc[-1]
        
        daily_diff = last_p - prev_p
        daily_pct = (daily_diff / prev_p) * 100 if prev_p > 0 else 0.0
        
        st.markdown(f"## 📈 {ticker} | <span style='color:#00E676;'>${last_p:,.2f}</span>", unsafe_allow_html=True)
        st.markdown(f"<span style='color:#B0BEC5;'>📅 ข้อมูลกราฟล่าสุด ณ: {last_candle_date} | 🕒 เวลาอัปเดตระบบ: {current_time}</span>", unsafe_allow_html=True)
        
        m_c1, m_c2 = st.columns(2)
        m_c1.metric("💵 ราคาตลาดล่าสุด (Real-Time)", f"${last_p:,.2f}")
        m_c2.metric("📊 การเปลี่ยนแปลงจากราคาปิดวันก่อนหน้า (Daily Change)", 
                    f"{'+' if daily_diff >= 0 else ''}{daily_diff:,.2f} USD", 
                    delta=f"{daily_pct:+.2f}%")
        
        with st.expander("🏢 ข้อมูลธุรกิจ (Company Profile)", expanded=False):
            st.markdown(f"**🇹🇭 สรุปธุรกิจ:**")
            st.info(f"{fund.get('business_desc_th', 'ไม่มีข้อมูล')}")
            c_b1, c_b2, c_b3 = st.columns(3)
            c_b1.markdown(f"**🏷️ กลุ่ม:** {fund.get('industry', 'N/A')}")
            c_b2.markdown(f"**📍 ที่ตั้ง:** {fund.get('location', 'N/A')}")
            website = fund.get('website', '#')
            if website != '#': c_b3.markdown(f"**🌐 เว็บไซต์:** <a href='{website}' target='_blank'>คลิกดูเว็บไซต์</a>", unsafe_allow_html=True)

        spy_t = market_signal.get("spy_trend", "N/A")
        spy_p = market_signal.get("spy_price", 0.0)
        v_val = market_signal.get("vix", 0.0)
        vix_ts = market_signal.get("vix_ts", 0.0)
        sm_flow = market_signal.get("smart_money", "N/A")
        
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("ตลาดโลก (S&P 500)", f"{spy_p:,.2f}" if spy_p > 0 else "N/A", spy_t if spy_p > 0 else None, delta_color="normal" if "ขึ้น" in spy_t else "inverse" if "ลง" in spy_t else "off")
        vix_stat = "Risk ON" if 0 < v_val < 20 else "Neutral" if 0 < v_val < 30 else "Panic"
        m2.metric("ความกลัว (VIX)", f"{v_val:.2f}" if v_val > 0 else "N/A", vix_stat if v_val > 0 else None, delta_color="normal" if 0 < v_val < 25 else "inverse" if v_val >= 25 else "off")
        ts_label = "🟢 สงบ" if 0 < vix_ts < 1 else "🔴 ตระหนก" if vix_ts > 0 else "N/A"
        m3.metric("โครงสร้าง (VIX/VIX3M)", f"{vix_ts:.2f}" if vix_ts > 0 else "N/A", ts_label if vix_ts > 0 else None, delta_color="normal" if 0 < vix_ts < 1 else "inverse" if vix_ts >= 1 else "off")
        m4.metric("เงินใหญ่ (HYG/IEF)", "Credit Flow", sm_flow if sm_flow != "N/A" else None, delta_color="normal" if "ON" in sm_flow else "inverse" if "OFF" in sm_flow else "off")

        is_market_good = "ขึ้น" in spy_t and (0 < v_val < 25)
        
        if is_market_good and is_uptrend and is_bullish_macd and rsi_val < 70:
            rec, color = "STRONG BUY / HOLD", "#00E676"
            msg = f"**'จังหวะน้ำขึ้นต้องรีบตัก'** - ตลาดเอื้ออำนวย หุ้นเป็นขาขึ้นเต็มตัว โมเมนตัมบวก แนะนำให้สะสมหรือรันเทรนด์ต่อ"
        elif is_uptrend and rsi_val >= 70:
            rec, color = "HOLD / TAKE PROFIT", "#FFD600"
            msg = f"**'ระวังความร้อนแรง'** - หุ้นเป็นขาขึ้นแต่เข้าเขตซื้อมากเกินไป ไม่ควรไล่ราคา แนะนำรันเทรนด์แบบยก Stop Loss ตาม"
        elif not is_uptrend and is_bullish_macd and rsi_val < 35:
            rec, color = "SPECULATIVE BUY", "#2962FF"
            msg = f"**'ลุ้นรีบาวด์'** - หุ้นเสียทรงขาขึ้นแต่เริ่มมีแรงซื้อกลับ เหมาะเก็งกำไรระยะสั้น (ต้องมีจุดตัดขาดทุนชัดเจน)"
        elif not is_uptrend:
            rec, color = "AVOID / WAIT", "#FF5252"
            msg = f"**'ทับมือรักษาเงินต้น'** - ภาพรวมเป็นขาลง โมเมนตัมอ่อนแอ แนะนำให้รอดูสถานการณ์ไปก่อน"
        else:
            rec, color = "NEUTRAL / SIDEWAY", "#B0BEC5"
            msg = f"**'รอเลือกทาง'** - กราฟแกว่งตัว สัญญาณขัดแย้งกัน แนะนำเทรดในกรอบสั้นๆ หรือรอจนกว่าจะชัดเจน"

        st.markdown(f"""
        <div style="background-color: #1E1E1E; border-left: 8px solid {color}; padding: 20px; border-radius: 8px; margin: 15px 0;">
            <h4 style="color: {color}; margin-top: 0;">🤵 ทัศนะเทรดเดอร์: {rec}</h4>
            <p style="color: #E0E0E0; margin-bottom: 0;">{msg}</p>
        </div>
        """, unsafe_allow_html=True)

        rs_val = df['RS'].iloc[-1]
        rs_t = f" | **Relative Strength:** {'🟢 ชนะตลาด' if rs_val > 0 else '🔴 อ่อนแอ'} ({rs_val:.2f}%)" if not np.isnan(rs_val) else ""
        if matrix: st.info(f"🔮 **ทิศทาง {tf_option}:** {matrix['tr']} | **เป้าหมาย (Harmonic Matrix):** {matrix['l']:,.2f} - {matrix['u']:,.2f} {rs_t}")
        
        c_l, c_r = st.columns([7, 3])
        with c_l:
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name="Price"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['E10'], line=dict(color='#00E676', width=1), name="EMA 10"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['E25'], line=dict(color='#BA68C8', width=1.5), name="EMA 25"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['E50'], line=dict(color='#FF6D00', width=2), name="EMA 50"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['E200'], line=dict(color='#E0E0E0', width=1, dash='dot'), name="EMA 200"), row=1, col=1)
            
            actual_cost = holdings[ticker]["total_cost"] / holdings[ticker]["shares"] if st.session_state["logged_in"] and holdings.get(ticker, {}).get("shares", 0) > 0.001 else b_p
            if actual_cost > 0: fig.add_hline(y=actual_cost, line_dash="dash", line_color="cyan", annotation_text="ต้นทุนเฉลี่ย", row=1, col=1)
            
            fig.add_trace(go.Bar(x=df.index, y=df['Hist'], marker_color=['#00E676' if v >= 0 else '#FF5252' for v in df['Hist']], name="MACD"), row=2, col=1)
            fig.update_layout(template="plotly_dark", height=600, margin=dict(l=0,r=0,t=0,b=0), showlegend=False, xaxis_rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)
            
            st.subheader("📊 ข้อมูลพื้นฐาน (Fundamental)")
            pe_v = fund.get('pe_val', 0)
            if pe_v <= 0: pe_status = "🔴 ขาดทุน"
            elif pe_v < 15: pe_status = "🟢 ถูก (Value)"
            elif pe_v < 30: pe_status = "🟡 เหมาะสม"
            else: pe_status = "🟠 แพง"
            f1, f2, f3 = st.columns(3)
            f1.metric("P/S Ratio", fund.get('ps','N/A'))
            f2.metric("P/E Ratio", fund.get('pe','N/A'), pe_status, delta_color="off")
            f3.metric("ROE", fund.get('roe','N/A'))
            st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)
            f4, f5, f6 = st.columns(3)
            f4.metric("การเติบโตรายได้", fund.get('rev_growth','N/A'))
            f5.metric("💰 เงินปันผล", fund.get('dividend','ไม่มี'), "ต่อปี", delta_color="normal" if fund.get('dividend') != "ไม่มีปันผล" else "off")
            f6.metric("📅 ประกาศงบ (Earnings)", fund.get('earnings_date', 'รอประกาศ'))
            if (pe_v <= 0) or (fund.get('roe_val', 0) < 0): st.error("⚠️ หุ้นเก็งกำไรความเสี่ยงสูง (ขาดทุน หรือ ROE ติดลบ) ระบบจะปรับลดงบเข้าซื้ออัตโนมัติ")
        
        with c_r:
            if levels:
                st.markdown(f"""
                <div class="pro-box" style="border-top: 3px solid #FF5252;">
                    <div class="pro-title c-red">แนวต้าน (RESISTANCE)</div>
                    <div class="pro-row"><span>ด่านแรก</span> <span>${levels['r1']:.2f}</span></div>
                    <div class="pro-row"><span>ด่านจริง</span> <span>${levels['r2']:.2f}</span></div>
                    <div class="pro-row"><span>ด่านถัดไป</span> <span>${levels['r3']:.2f}</span></div>
                    <div class="pro-row"><span>เป้าหมายถัดไป</span> <span>${levels['r4']:.2f}</span></div>
                </div>
                <div class="pro-box" style="border-top: 3px solid #00E676;">
                    <div class="pro-title c-green">แนวรับ (SUPPORT)</div>
                    <div class="pro-row"><span>แนวรับแรก</span> <span>${levels['s1']:.2f}</span></div>
                    <div class="pro-row"><span>แนวรับลึก</span> <span>${levels['s2']:.2f}</span></div>
                    <div class="pro-row"><span>แนวรับถัดไป</span> <span>${levels['s3']:.2f}</span></div>
                </div>
                """, unsafe_allow_html=True)
            
            if is_uptrend and is_bullish_macd:
                p_main, summary = "ย่อ = ซื้อเพิ่ม / ถือรันเทรนด์", "🟢 'เกมลุย'"
                not_to_do = "❌ ห้ามสวนเทรนด์ (Short/Put)<br>❌ อย่ารีบขายหมู"
                t_flow = f"หลุด {levels['s1']:.2f} (ระวัง) ➡ ยืน {levels['s1']:.2f} (ลุ้นต่อ) ➡ เบรก {levels['r2']:.2f} (ไปต่อยาว)"
            elif not is_uptrend:
                p_main, summary = "เด้ง = หนี / ลดความเสี่ยง", "🔴 'เกมป้องกัน'"
                not_to_do = "❌ ห้ามไล่ซื้อสวนทาง<br>❌ ห้ามถัวเพิ่มเด็ดขาด"
                t_flow = f"หลุด {levels['s2']:.2f} (ลงต่อลึก) ➡ ยืน {levels['r1']:.2f} ได้ (ลุ้นกลับตัว)"
            else:
                p_main, summary = "รอจังหวะ / เลือกทาง", "🟡 'เกมระวัง'"
                not_to_do = "❌ ห้ามทุ่มสุดตัว<br>❌ อย่าเชื่อสัญญาณเดียว"
                t_flow = f"หลุด {levels['s2']:.2f} (จบรอบ) ➡ แขว่งกรอบ {levels['s2']:.2f}-{levels['r1']:.2f}"
                
            st.markdown(f"""
            <div class="pro-box" style="border-top: 3px solid #FFD600;">
                <div class="pro-title c-yellow">แผนการเทรด (AI Update)</div>
                <div style="margin-bottom:8px;"><b>🎯 แผนหลัก (ตอนนี้)</b><br><span class="c-gray">{p_main}</span></div>
            </div>
            
            <div class="pro-box" style="border-top: 3px solid #FF5252; background-color: rgba(255, 82, 82, 0.05);">
                <div class="pro-title c-red">สิ่งที่ไม่ควรทำตอนนี้ ⚠️</div>
                <div class="c-red">{not_to_do}</div>
            </div>
            
            <div class="pro-box">
                <div class="c-gray">💡 <b>สรุปสั้นๆ:</b> {summary}<br><br><b>แผนภาพแนวโน้ม:</b> {t_flow}</div>
            </div>
            """, unsafe_allow_html=True)
            
            sup_val = df['E50'].iloc[-1]
            if actual_cost > 0:
                pl = ((last_p - actual_cost) / actual_cost) * 100
                st.write(f"**P/L ของคุณ:** {pl:.2f}%")
                sl = sup_val * 0.99 if b_p == 0 else actual_cost * 0.92
                st.error(f"🛡️ **จุดหนี (Stop Loss): ${sl:.2f}**")
                ra = t_cap * (r_pct / 100.0)
                if last_p > sl: st.success(f"🧮 **เข้าซื้อได้สูงสุด:** {ra/(last_p-sl):.0f} หุ้น")
    else: 
        st.warning(f"❌ ระบบถูก Yahoo บล็อกสัญญาณชั่วคราวค่ะ โปรดรอ 1-2 นาทีแล้วกดปุ่ม 'ดึงข้อมูลเรียลไทม์เดี๋ยวนี้' ด้านซ้ายบนอีกครั้งค่ะ")

# ==========================================
# หน้า 2: โซนเข้าซื้อเทคนิคอล (Action Zones เจาะลึก)
# ==========================================
with tabs[1]:
    if not df.empty:
        st.markdown(f"## 🔬 โซนเข้าซื้อ (Action Zones) : {ticker}")
        st.markdown("หน้าต่างพิเศษสำหรับสาย Technical เพื่อหาจังหวะ **'ย่อซื้อ (Buy the Dip)'** หรือ **'ทะลุซื้อ (Breakout)'** โดยอิงจากข้อมูล Real-time")
        
        last_close = df['Close'].iloc[-1]
        ema10 = df['E10'].iloc[-1]
        ema25 = df['E25'].iloc[-1]
        ema50 = df['E50'].iloc[-1]
        ema200 = df['E200'].iloc[-1]
        rsi = df['RSI'].iloc[-1]
        macd = df['MACD'].iloc[-1]
        sig = df['Sig'].iloc[-1]
        is_bullish_macd = macd > sig
        is_uptrend = last_close > ema50
        
        st.markdown(f"💡 **ราคาตลาดปัจจุบัน:** `${last_close:,.2f} USD` | **ส่วนต่างราคารายวันนับจากปิดวานนี้:** `{daily_diff:+,.2f} USD ({daily_pct:+.2f}%)`")
        
        if last_close > ema200: 
            trend_main = "🟢 ขาขึ้นระยะยาว (Bullish)"
            trend_desc = "ราคาอยู่เหนือเส้น EMA 200 วัน แสดงว่าเทรนด์หลักเป็นขาขึ้น แนะนำให้หาจังหวะ **'ย่อซื้อ'** จะได้เปรียบที่สุด"
        else: 
            trend_main = "🔴 ขาลงระยะยาว (Bearish)"
            trend_desc = "ราคาอยู่ใต้เส้น EMA 200 วัน เทรนด์หลักอ่อนแอ หากจะเล่นต้องเป็นสาย **'เก็งกำไรเด้งสั้น'** เท่านั้น ห้ามถือนาน"
            
        action_signal = ""
        action_desc = ""
        action_color = ""
        
        if last_close > ema200:
            if last_close < ema25 and last_close >= (ema50 * 0.98) and rsi < 50:
                action_signal = "🟢 ย่อตัวลงมาในโซนซื้อ (Buy the Dip)"
                action_desc = f"ราคาย่อตัวลงมาพักฐานใกล้แนวรับสำคัญ (EMA 50 = ${ema50:.2f}) และความร้อนแรง (RSI) ลดลงแล้ว เป็นจังหวะดีในการแบ่งไม้สะสม"
                action_color = "#00E676"
            elif macd > sig and last_close > ema10 and df['Close'].iloc[-2] <= df['E10'].iloc[-2]:
                action_signal = "🔥 สัญญาณซื้อเพิ่งเกิด (Fresh Breakout)"
                action_desc = "ราคาเพิ่งทะลุเส้นระยะสั้น (EMA 10) ขึ้นมาได้ พร้อมโมเมนตัม MACD สนับสนุน สามารถพิจารณา 'ซื้อตามน้ำ' ได้เลย"
                action_color = "#FFD600"
            elif rsi > 70:
                action_signal = "🔴 ตึงตัวเกินไป (Overbought)"
                action_desc = f"ราคาปรับตัวขึ้นมาแรงมากจน RSI ทะลุ 70 มีความเสี่ยงที่จะโดนเทขายทำกำไร **ห้ามไล่ซื้อเด็ดขาด** ให้รอราคาย่อตัวก่อน"
                action_color = "#FF5252"
            else:
                action_signal = "⏳ รอจังหวะชัดเจน (Wait & See)"
                action_desc = "กราฟกำลังสร้างฐานสะสมพลัง หรือสัญญาณยังขัดแย้งกัน แนะนำให้ทับมือรอดูไปก่อน"
                action_color = "#B0BEC5"
        else:
            if rsi < 30 and macd > sig:
                action_signal = "⚡ เก็งกำไรเด้งสั้น (Speculative Rebound)"
                action_desc = "ราคาลงมาลึกมากจนเริ่มมีสัญญาณซื้อสวนทาง (Oversold) เหมาะสำหรับเล่นเด้งสั้นๆ แต่ต้องมีจุดตัดขาดทุน (Stop Loss) ที่เคร่งครัด"
                action_color = "#2962FF"
            else:
                action_signal = "❌ ทับมือ ห้ามรับมีด (Downtrend Risk)"
                action_desc = "เทรนด์เป็นขาลงชัดเจนและยังไม่มีสัญญาณกลับตัว การเข้าไปซื้อตอนนี้เสมือนการเข้าไปรับมีดที่กำลังตกลงมา แนะนำให้อยู่เฉยๆ"
                action_color = "#FF5252"

        c_t1, c_t2 = st.columns(2)
        with c_t1:
            st.markdown(f"""
            <div class="pro-box" style="border-top: 4px solid #82B1FF;">
                <div style="font-size: 0.9em; color: #B0BEC5;">ภาพรวมกระแสน้ำ (Primary Trend)</div>
                <div style="font-size: 1.4em; font-weight: bold; margin: 10px 0;">{trend_main}</div>
                <div style="color: #E0E0E0; font-size: 0.95em;">{trend_desc}</div>
            </div>
            """, unsafe_allow_html=True)
        with c_t2:
            st.markdown(f"""
            <div class="pro-box" style="border-top: 4px solid {action_color}; background-color: {action_color}11;">
                <div style="font-size: 0.9em; color: #B0BEC5;">สถานะจุดเข้า (Entry Action)</div>
                <div style="font-size: 1.4em; font-weight: bold; color: {action_color}; margin: 10px 0;">{action_signal}</div>
                <div style="color: #E0E0E0; font-size: 0.95em;">{action_desc}</div>
            </div>
            """, unsafe_allow_html=True)
            
        # =========================================================
        # 👑 THE ULTIMATE CONSENSUS (บทสรุปเอกฉันท์ 3 มิติ - ไร้อคติ) 
        # =========================================================
        st.markdown("---")
        st.markdown("### 👑 บทสรุปเอกฉันท์ (The Objective Consensus)")
        with st.spinner("⏳ ประมวลผลข้อมูล มหภาค + เทคนิค + พิทบูลพยากรณ์ อย่างเป็นกลาง..."):
            sim_df_quick, exp_p_quick, up_b_quick, low_b_quick, _ = run_monte_carlo(ticker, days_to_predict=30)
            if sim_df_quick is not None:
                upside_quick = ((exp_p_quick - last_close) / last_close) * 100
                
                # ตรรกะใหม่: เข้มงวดขึ้น ไร้อคติ และตรวจสอบโมเมนตัมปัจจุบัน
                if last_close > ema50 and is_bullish_macd and rsi < 70 and exp_p_quick > last_close and is_market_good:
                    m_col, m_sig = "#00E676", "🌟 FULLY ALIGNED (สอดคล้องทุกมิติ: ทยอยสะสม)"
                    m_desc = f"สอดคล้อง 3 มิติ! **ตลาดโลกเป็นใจ** + **กราฟเทคนิค**เป็นขาขึ้นชัดเจนและโมเมนตัมสนับสนุน (MACD ตัดขึ้น) หนุนด้วย**สถิติพยากรณ์**ที่ให้เป้าหมาย 30 วันไปที่ **${exp_p_quick:.2f}** (+{upside_quick:.2f}%) แนะนำหาจังหวะย่อซื้อที่แนวรับและตั้ง Stop Loss เสมอ"
                elif last_close > ema200 and (not is_bullish_macd or rsi >= 70):
                    m_col, m_sig = "#FF9800", "⚠️ PULLBACK WARNING (สัญญาณพักฐาน: ชะลอการลงทุน)"
                    m_desc = f"ระวัง! เทรนด์ยาวยังเป็นขาขึ้น แต่ **ภาพระยะสั้นโมเมนตัมกำลังหักหัวลง (MACD อ่อนแรง) หรือเข้าเขตซื้อมากเกินไป (Overbought)** แม้สถิติจะมองเป้าที่ **${exp_p_quick:.2f}** แต่ในทางปฏิบัติ นี่คือ 'การพักฐาน' แนะนำให้ **ทับมือ (Wait & See)** เพื่อรอรับที่แนวรับ ไม่ควรไล่ราคา"
                elif last_close < ema50 and exp_p_quick < last_close:
                    m_col, m_sig = "#FF5252", "🚨 HIGH RISK (ทิศทางขาลง: หลีกเลี่ยง)"
                    m_desc = f"อันตราย! **กราฟเทคนิค**เป็นขาลงชัดเจน สอดคล้องกับ**สถิติพยากรณ์**ที่ประเมินว่าราคาจะไหลลงไปที่ **${exp_p_quick:.2f}** ({upside_quick:.2f}%) แนะนำให้ 'หลีกเลี่ยง' หรือหนีตายหากหลุด ${low_b_quick:.2f}"
                else:
                    m_col, m_sig = "#FFD600", "⚖️ NEUTRAL / DIVERGENCE (สัญญาณขัดแย้ง: รอเลือกทาง)"
                    m_desc = f"สัญญาณจาก 3 มิติยังขัดแย้งกัน (เช่น ตลาดดีแต่กราฟกำลังพักฐาน หรือกราฟดีแต่สถิติมองลง) แนะนำให้ **เทรดอย่างระมัดระวังในกรอบแคบๆ** หรือรอดูความชัดเจนจนกว่าแนวโน้มและโมเมนตัมจะไปในทิศทางเดียวกัน"

                st.markdown(f"""
                <div style="background-color: #1E1E1E; border-left: 8px solid {m_col}; padding: 20px; border-radius: 8px; margin: 15px 0;">
                    <h4 style="color: {m_col}; margin-top: 0;">{m_sig}</h4>
                    <p style="color: #E0E0E0; margin-bottom: 0; font-size: 1.05em;">{m_desc}</p>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.warning("⚠️ ไม่สามารถดึงข้อมูลพิทบูลมาสรุปผลได้ในขณะนี้")
        st.markdown("---")

        # ปรับปรุงข้อความกราฟซูมให้สัมพันธ์กับ Timeframe ที่เลือก
        if tf_option == "1D (รายวัน)":
            zoom_text = "60 วันทำการล่าสุด (~3 เดือน)"
        elif tf_option == "1W (รายสัปดาห์)":
            zoom_text = "60 สัปดาห์ล่าสุด (~1 ปี 2 เดือน)"
        else:
            zoom_text = "60 เดือนล่าสุด (5 ปี)"
            
        st.markdown(f"### 🔎 กราฟเจาะลึก ({zoom_text})")
        df_zoom = df.tail(60)
        
        fig_zoom = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.04, row_heights=[0.6, 0.2, 0.2])
        
        fig_zoom.add_trace(go.Candlestick(x=df_zoom.index, open=df_zoom['Open'], high=df_zoom['High'], low=df_zoom['Low'], close=df_zoom['Close'], name="Price"), row=1, col=1)
        fig_zoom.add_trace(go.Scatter(x=df_zoom.index, y=df_zoom['E10'], line=dict(color='#00E676', width=1.5), name="EMA 10 (ระยะสั้น)"), row=1, col=1)
        fig_zoom.add_trace(go.Scatter(x=df_zoom.index, y=df_zoom['E25'], line=dict(color='#BA68C8', width=1.5), name="EMA 25 (กลางสั้น)"), row=1, col=1)
        fig_zoom.add_trace(go.Scatter(x=df_zoom.index, y=df_zoom['E50'], line=dict(color='#FF6D00', width=2), name="EMA 50 (แนวรับหลัก)"), row=1, col=1)
        fig_zoom.add_trace(go.Scatter(x=df_zoom.index, y=df_zoom['E200'], line=dict(color='#E0E0E0', width=1.5, dash='dot'), name="EMA 200 (เทรนด์ใหญ่)"), row=1, col=1)
        
        if last_close < ema25 and last_close >= (ema50 * 0.95):
             fig_zoom.add_hline(y=ema50, line_dash="solid", line_color="#00E676", annotation_text="โซนเฝ้าระวังเข้าซื้อ (Buy Zone)", row=1, col=1, opacity=0.5)

        # 📐 ระบบวาดเส้น Fibonacci อัตโนมัติ 
        st.markdown("---")
        show_fibo = st.checkbox(f"📐 ตีเส้น Fibonacci Retracement (อ้างอิงรอบสวิง {zoom_text})", value=False)
        if show_fibo:
            max_p = df_zoom['High'].max()
            min_p = df_zoom['Low'].min()
            diff = max_p - min_p
            f_levels = [
                (0.0, "0.0% (High)", "#FF5252"),
                (0.236, "23.6%", "#FFB74D"),
                (0.382, "38.2%", "#FFF176"),
                (0.5, "50.0%", "#E0E0E0"),
                (0.618, "61.8% (Golden Ratio)", "#00E676"),
                (0.786, "78.6%", "#4DD0E1"),
                (1.0, "100.0% (Low)", "#FF5252")
            ]
            for ratio, label, color in f_levels:
                fibo_y = max_p - (diff * ratio)
                fig_zoom.add_hline(y=fibo_y, line_dash="dot", line_color=color, annotation_text=f"{label} : ${fibo_y:.2f}", row=1, col=1, opacity=0.8)
                
            st.markdown("#### 🧠 บทสรุปวิเคราะห์ Fibonacci")
            fibo_382 = max_p - (diff * 0.382)
            fibo_618 = max_p - (diff * 0.618)
            fibo_786 = max_p - (diff * 0.786)
            
            if last_close > fibo_382:
                f_sum = "🟢 **แนวโน้มแข็งแกร่ง (Strong Uptrend):** ราคายืนอยู่เหนือระดับ 38.2% แสดงถึงเทรนด์ขาขึ้นที่มีแรงขายออกเพียงเล็กน้อย หุ้นมีโอกาสทำจุดสูงสุดใหม่ (New High) ต่อได้"
            elif last_close > fibo_618:
                f_sum = f"🟡 **โซนสัดส่วนทองคำ (Golden Zone):** ราคาพักตัวลงมาที่โซนสมดุล (50% - 61.8%) นี่คือ **'จุดย่อซื้อ (Buy the Dip)'** ที่ได้เปรียบที่สุดทางคณิตศาสตร์ แนะนำให้เฝ้าระวังการกลับตัว"
            elif last_close > fibo_786:
                f_sum = "🟠 **พักตัวลึก (Deep Pullback):** ราคาลงมาลึกมากถึงระดับ 78.6% ควรระมัดระวัง อาจเป็นการเตือนว่าเทรนด์ขาขึ้นเริ่มหมดแรง และเตรียมเปลี่ยนเป็นแนวโน้มขาลง"
            else:
                f_sum = "🔴 **เปลี่ยนเป็นขาลง (Downtrend):** ราคาหลุดสัดส่วนฟิโบนาชชีทั้งหมดไปแล้ว แสดงถึงการพักตัวล้มเหลว และได้เปลี่ยนเทรนด์เป็นขาลงเต็มตัวเรียบร้อยแล้ว แนะนำให้หลีกเลี่ยง"
            st.info(f_sum)

        fig_zoom.add_trace(go.Bar(x=df_zoom.index, y=df_zoom['Hist'], marker_color=['#00E676' if v >= 0 else '#FF5252' for v in df_zoom['Hist']], name="MACD Hist"), row=2, col=1)
        fig_zoom.add_trace(go.Scatter(x=df_zoom.index, y=df_zoom['MACD'], line=dict(color='#2962FF', width=1.5), name="MACD Line"), row=2, col=1)
        fig_zoom.add_trace(go.Scatter(x=df_zoom.index, y=df_zoom['Sig'], line=dict(color='#FFD600', width=1.5), name="Signal Line"), row=2, col=1)
        
        fig_zoom.add_trace(go.Scatter(x=df_zoom.index, y=df_zoom['RSI'], line=dict(color='#FF9800', width=1.5), name="RSI"), row=3, col=1)
        fig_zoom.add_hline(y=70, line_dash="dot", line_color="#FF5252", row=3, col=1) 
        fig_zoom.add_hline(y=30, line_dash="dot", line_color="#00E676", row=3, col=1) 
        fig_zoom.update_yaxes(range=[0, 100], row=3, col=1)
        
        fig_zoom.update_layout(
            template="plotly_dark", 
            height=750,  
            margin=dict(l=0,r=0,t=40,b=0), 
            showlegend=True, 
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0)
        )
        fig_zoom.update_xaxes(rangeslider_visible=False)
        st.plotly_chart(fig_zoom, use_container_width=True)

# ==========================================
# หน้า 3: เรดาร์สแกนหุ้น (AI Screener)
# ==========================================
with tabs[2]:
    st.markdown("## 🎯 เรดาร์สแกนหุ้น (AI Screener & Mini-Chart)")
    st.markdown("### 📋 จัดการรายชื่อหุ้นในเรดาร์ (สูงสุด 20 ตัว)")
    
    c_rad1, c_rad2 = st.columns([7, 3])
    with c_rad1:
        default_pool = ["ASTS", "RKLB", "NVTS", "IREN", "RGTI", "C", "TSLA", "PLTR", "ONDS", "OKLO", "EOSE", "IONQ", "NOW", "MNDY", "ADBE", "CRWD", "AMKR", "NVDA", "MSFT", "GOOGL"]
        all_options = sorted(list(set(st.session_state.radar_tickers + default_pool)))
        
        selected_radar = st.multiselect("หุ้นที่กำลังเฝ้าจับตา (กด X เพื่อลบออก):", options=all_options, default=st.session_state.radar_tickers)
        if selected_radar != st.session_state.radar_tickers:
            if len(selected_radar) > 20:
                st.error("⚠️ ไม่สามารถเลือกเกิน 20 ตัวได้ค่ะ! ระบบจำกัดรายชื่อเพื่อเสถียรภาพสูงสุด")
            else:
                st.session_state.radar_tickers = selected_radar
                st.rerun()
                
    with c_rad2:
        new_ticker = st.text_input("➕ เพิ่มหุ้นใหม่", placeholder="เช่น AMZN").upper().strip()
        if st.button("เพิ่มเข้าเรดาร์", use_container_width=True):
            if len(st.session_state.radar_tickers) >= 20:
                st.error("⚠️ เรดาร์เต็ม 20 ตัวแล้วค่ะ! กรุณากดปุ่มกากบาท (X) ลบตัวเก่าออกก่อนถึงจะเพิ่มตัวใหม่ได้นะคะ")
            elif new_ticker and new_ticker not in st.session_state.radar_tickers:
                st.session_state.radar_tickers.append(new_ticker)
                st.rerun()

    if st.button("🚀 สแกนและอัปเดตกราฟ", type="primary", use_container_width=True):
        with st.spinner("⏳ AI กำลังวิ่งดึงกราฟและข้อมูลทีละตัว..."):
            screener_df = run_ai_screener(st.session_state.radar_tickers)
            if not screener_df.empty:
                def color_action(val):
                    if "STRONG BUY" in str(val): return 'background-color: rgba(0, 230, 118, 0.2); color: #00E676; font-weight: bold;'
                    elif "SPECULATE" in str(val): return 'color: #82B1FF; font-weight: bold;'
                    elif "OVERBOUGHT" in str(val): return 'background-color: rgba(255, 214, 0, 0.2); color: #FFD600; font-weight: bold;'
                    elif "WAIT" in str(val): return 'color: #FF5252;'
                    return ''
                st.dataframe(
                    screener_df.style.map(color_action, subset=["คำแนะนำ AI"]),
                    column_config={"กราฟ 30 วัน": st.column_config.LineChartColumn("ทิศทาง (30 วัน)")},
                    use_container_width=True,
                    height=600  
                )
            else: st.warning("ไม่พบข้อมูล กรุณาตรวจสอบรายชื่อหุ้นอีกครั้ง")

# ==========================================
# หน้า 4 & 5: บัญชี, พอร์ตโฟลิโอ และระบบภาษี
# ==========================================
if st.session_state["logged_in"]:
    with tabs[3]:
        st.subheader("💼 แดชบอร์ดกระแสเงินสด")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("📤 โอนออก (ลงทุน)", f"${l_stat['outward']:,.2f}")
        col2.metric("📥 โอนกลับ (ถอน)", f"${l_stat['inward']:,.2f}")
        col3.metric("📈 ต้นทุนหุ้นในพอร์ต", f"${l_stat['bought'] - l_stat['sold']:,.2f}")
        col4.metric("💰 เงินสดคงเหลือ", f"${cb:,.2f}")
        
        st.markdown("---")
        h1, h2 = st.columns([8, 2])
        h1.subheader("📝 สมุดบัญชี (Cloud Ledger)")
        h2.download_button("📥 โหลด (Excel)", convert_df_to_csv(st.session_state.trade_ledger), f"Ledger_{datetime.now().strftime('%Y%m%d')}.csv", 'text/csv', use_container_width=True)
        
        with st.expander("📤 นำเข้าข้อมูลจากไฟล์ Excel / CSV", expanded=False):
            template_df = pd.DataFrame(columns=["Date", "Action", "Ticker", "Price", "Shares", "Amount_USD", "Running_Balance", "FX_Rate", "WHT_USD", "Ref_Doc"])
            st.download_button("📝 โหลดไฟล์ Template ว่าง (Excel/CSV)", convert_df_to_csv(template_df), "Trade_Template.csv", "text/csv")
            
            uploaded_file = st.file_uploader("ลากไฟล์มาวาง หรือ กดเพื่อเลือกไฟล์", type=['csv', 'xlsx'])
            if uploaded_file is not None:
                st.warning("⚠️ โปรดเลือกวิธีนำเข้าข้อมูล (เพื่อป้องกันข้อมูลเดิมหาย)")
                c_imp1, c_imp2 = st.columns(2)
                
                with c_imp1:
                    if st.button("➕ เพิ่มข้อมูลต่อท้าย (Append)", use_container_width=True):
                        try:
                            if uploaded_file.name.endswith('.csv'): df_imported = pd.read_csv(uploaded_file)
                            else: df_imported = pd.read_excel(uploaded_file)
                            
                            if 'Date' in df_imported.columns:
                                df_imported['Date'] = pd.to_datetime(df_imported['Date'], errors='coerce').dt.strftime("%d/%m/%Y").replace("NaT", "")
                            
                            req_cols = ["Date", "Action", "Ticker", "Price", "Shares", "Amount_USD", "Running_Balance", "FX_Rate", "WHT_USD", "Ref_Doc"]
                            for col in req_cols:
                                if col not in df_imported.columns: df_imported[col] = ""
                            
                            st.session_state.trade_ledger = pd.concat([st.session_state.trade_ledger, clean_df_types(df_imported[req_cols])], ignore_index=True)
                            st.success("✅ นำข้อมูลใหม่ไปต่อท้ายตารางเรียบร้อย!")
                            time.sleep(2)
                            st.rerun()
                        except Exception as e: st.error(f"❌ อ่านไฟล์ไม่สำเร็จ: {e}")
                        
                with c_imp2:
                    if st.button("🔄 แทนที่ทั้งหมด (Overwrite)", type="primary", use_container_width=True):
                        try:
                            if uploaded_file.name.endswith('.csv'): df_imported = pd.read_csv(uploaded_file)
                            else: df_imported = pd.read_excel(uploaded_file)
                            
                            if 'Date' in df_imported.columns:
                                df_imported['Date'] = pd.to_datetime(df_imported['Date'], errors='coerce').dt.strftime("%d/%m/%Y").replace("NaT", "")
                                
                            req_cols = ["Date", "Action", "Ticker", "Price", "Shares", "Amount_USD", "Running_Balance", "FX_Rate", "WHT_USD", "Ref_Doc"]
                            for col in req_cols:
                                if col not in df_imported.columns: df_imported[col] = ""
                            
                            st.session_state.trade_ledger = clean_df_types(df_imported[req_cols])
                            st.success("✅ แทนที่ตารางด้วยข้อมูลจากไฟล์ใหม่เรียบร้อย!")
                            time.sleep(2)
                            st.rerun()
                        except Exception as e: st.error(f"❌ อ่านไฟล์ไม่สำเร็จ: {e}")
        
        ed_l = st.data_editor(st.session_state.trade_ledger, num_rows="dynamic", use_container_width=True,
            column_config={
                "Date": "วันที่", "Action": st.column_config.SelectboxColumn("ประเภท", options=["นำเงินออกนอกประเทศ (Outward)", "นำเงินเข้าประเทศไทย (Inward)", "ซื้อหุ้น (Buy)", "ขายหุ้น (Sell)", "รับเงินปันผล (Dividend)"]),
                "Ticker": "ชื่อหุ้น", "Price": st.column_config.NumberColumn("ราคา ($)", format="%.4f"), "Shares": st.column_config.NumberColumn("จำนวนหุ้น", format="%.4f"),
                "Amount_USD": st.column_config.NumberColumn("จำนวนเงิน ($)", format="%.2f"), "Running_Balance": st.column_config.NumberColumn("เงินสดคงเหลือ ($)", disabled=True, format="%.2f"), 
                "FX_Rate": st.column_config.NumberColumn("เรทเงิน", format="%.4f"), "WHT_USD": st.column_config.NumberColumn("ภาษี ($)", format="%.2f"), "Ref_Doc": "หมายเหตุ"
            })
        if not ed_l.equals(st.session_state.trade_ledger):
            st.session_state.trade_ledger = calculate_stats(clean_df_types(ed_l))[0]
            st.rerun()
            
        if st.button("💾 บันทึกข้อมูลบัญชีขึ้น Cloud", type="primary", use_container_width=True):
            if save_df_to_sheet("Ledger", st.session_state.trade_ledger): 
                st.success("บันทึกสำเร็จ!")
                time.sleep(1)
                st.rerun()

        st.markdown("---")
        st.subheader("📊 พอร์ตโฟลิโอ (Auto Mark-to-Market)")
        live_fx = get_live_fx()
        st.info(f"💱 **เรท USD/THB ล่าสุด:** ฿{live_fx:.4f}")
        port_summary, total_invested = [], 0.0
        for t, data in holdings.items():
            if data["shares"] > 0.001:
                port_summary.append({"Ticker": t, "Cost_Price": data["total_cost"] / data["shares"], "Shares": data["shares"], "Total_Cost": data["total_cost"]})
                total_invested += data["total_cost"]
        if len(port_summary) > 0:
            current_port_df = pd.DataFrame(port_summary)
            results, total_v = [], 0.0
            with st.spinner("⏳ อัปเดตราคาล่าสุด..."):
                batch_prices = get_batch_live_prices(current_port_df["Ticker"].tolist())
                for _, row in current_port_df.iterrows():
                    t, avg_cost, sh, t_cost = row["Ticker"], row["Cost_Price"], row["Shares"], row["Total_Cost"]
                    curr_p = batch_prices.get(t, avg_cost)
                    val = curr_p * sh
                    profit_usd = val - t_cost
                    results.append({"หุ้น": t, "จำนวนหุ้น": sh, "ต้นทุนเฉลี่ย": avg_cost, "ราคาปัจจุบัน": curr_p, "กำไร/ขาดทุน ($)": profit_usd, "กำไร/ขาดทุน (฿)": profit_usd * live_fx, "% เปลี่ยนแปลง": (profit_usd / t_cost) * 100 if t_cost > 0 else 0, "มูลค่ารวม": val})
                    total_v += val
            
            p1, p2, p3, p4 = st.columns(4)
            p1.metric("มูลค่าหุ้นรวม ($)", f"${total_v:,.2f}")
            p2.metric("ต้นทุนทั้งหมด ($)", f"${total_invested:,.2f}")
            p3.metric("กำไร/ขาดทุนรวม ($)", f"${total_v - total_invested:,.2f}", f"{((total_v - total_invested) / total_invested * 100 if total_invested > 0 else 0):.2f}%")
            p4.metric("กำไร/ขาดทุนรวม (฿)", f"฿{(total_v - total_invested) * live_fx:,.2f}")
            
            res_df = pd.DataFrame(results)
            chart_col1, chart_col2 = st.columns(2)
            with chart_col1:
                fig_pie = go.Figure(data=[go.Pie(labels=res_df['หุ้น'], values=res_df['มูลค่ารวม'], hole=.4)])
                fig_pie.update_layout(title="สัดส่วนพอร์ต", template="plotly_dark", height=350, margin=dict(t=50, b=0, l=0, r=0))
                st.plotly_chart(fig_pie, use_container_width=True)
            with chart_col2:
                fig_bar = go.Figure(data=[go.Bar(x=res_df['หุ้น'], y=res_df['กำไร/ขาดทุน ($)'], marker_color=['#00E676' if val >= 0 else '#FF5252' for val in res_df['กำไร/ขาดทุน ($)']])])
                fig_bar.update_layout(title="กำไร/ขาดทุนรายตัว", template="plotly_dark", height=350, margin=dict(t=50, b=0, l=0, r=0))
                st.plotly_chart(fig_bar, use_container_width=True)
                
            def color_profit(val): return f'color: {"#FF5252" if val < 0 else "#00E676"}; font-weight: bold;'
            st.dataframe(res_df.style.map(color_profit, subset=["กำไร/ขาดทุน ($)", "กำไร/ขาดทุน (฿)", "% เปลี่ยนแปลง"]).format({"จำนวนหุ้น": "{:,.4f}", "ต้นทุนเฉลี่ย": "${:,.4f}", "ราคาปัจจุบัน": "${:,.4f}", "กำไร/ขาดทุน ($)": "${:,.2f}", "กำไร/ขาดทุน (฿)": "฿{:,.2f}", "% เปลี่ยนแปลง": "{:,.2f}%", "มูลค่ารวม": "${:,.2f}"}), use_container_width=True)
            st.download_button("📥 โหลดพอร์ต (Excel)", convert_df_to_csv(res_df), f"Portfolio_{datetime.now().strftime('%Y%m%d')}.csv", 'text/csv')
        else: st.info("ว่างเปล่า (ยังไม่มีหุ้นในพอร์ต)")

    with tabs[4]:
        t1, t2 = st.columns([8, 2])
        t1.subheader("🧾 ประเมินภาษี ภ.ง.ด. 90")
        st.info("💡 **หลักการภาษีใหม่:** การนำเงินกลับไทยจะถูกหักจาก 'เงินต้นสะสม' ก่อน หากหักเงินต้นหมดแล้ว ยอดที่นำกลับจึงจะถือเป็น 'กำไรที่ต้องเสียภาษี'")
        
        tax_idx = st.session_state.trade_ledger['Action'].isin(["นำเงินออกนอกประเทศ (Outward)", "นำเงินเข้าประเทศไทย (Inward)", "รับเงินปันผล (Dividend)"])
        tax_v = st.session_state.trade_ledger[tax_idx].copy()
        tax_v["Out_USD"] = np.where(tax_v["Action"] == "นำเงินออกนอกประเทศ (Outward)", tax_v["Amount_USD"], 0.0)
        tax_v["In_USD"] = np.where(tax_v["Action"].isin(["นำเงินเข้าประเทศไทย (Inward)", "รับเงินปันผล (Dividend)"]), tax_v["Amount_USD"], 0.0)
        tax_v["FX_Rate"] = pd.to_numeric(tax_v["FX_Rate"], errors='coerce').fillna(0.0)
        tax_v["WHT_USD"] = pd.to_numeric(tax_v["WHT_USD"], errors='coerce').fillna(0.0)
        tax_v["Out_THB"], tax_v["In_THB"] = tax_v["Out_USD"] * tax_v["FX_Rate"], tax_v["In_USD"] * tax_v["FX_Rate"]
        
        capital_pool, taxable_gains_thb, running_bals = 0.0, [], []
        for i, r in tax_v.iterrows():
            if r['Action'] == "นำเงินออกนอกประเทศ (Outward)":
                capital_pool += r['Out_THB']; taxable_gains_thb.append(0.0)
            elif r['Action'] == "นำเงินเข้าประเทศไทย (Inward)":
                capital_pool -= r['In_THB']
                taxable_gains_thb.append(abs(capital_pool) if capital_pool < 0 else 0.0)
                if capital_pool < 0: capital_pool = 0.0
            elif r['Action'] == "รับเงินปันผล (Dividend)": taxable_gains_thb.append(r['In_THB'])
            else: taxable_gains_thb.append(0.0)
            running_bals.append(capital_pool)

        tax_v['Taxable_Gain_THB'], tax_v['Balance_THB'] = taxable_gains_thb, running_bals
        t2.download_button("📥 โหลดภาษี (Excel)", convert_df_to_csv(tax_v), f"Tax_{datetime.now().strftime('%Y%m%d')}.csv", 'text/csv', use_container_width=True)
        
        ed_t = st.data_editor(tax_v, use_container_width=True, num_rows="fixed", column_order=["Date", "Out_USD", "In_USD", "FX_Rate", "Out_THB", "In_THB", "Balance_THB", "Taxable_Gain_THB", "WHT_USD"])
        if not ed_t[["FX_Rate", "WHT_USD"]].equals(tax_v[["FX_Rate", "WHT_USD"]]):
            st.session_state.trade_ledger.loc[tax_idx, "FX_Rate"] = clean_df_types(ed_t)["FX_Rate"].values
            st.session_state.trade_ledger.loc[tax_idx, "WHT_USD"] = clean_df_types(ed_t)["WHT_USD"].values
            st.rerun()
        if st.button("💾 บันทึกภาษีลง Cloud", type="primary", use_container_width=True): 
            if save_df_to_sheet("Ledger", st.session_state.trade_ledger): 
                st.success("บันทึกสำเร็จ!")
                time.sleep(1)
                st.rerun()

        st.markdown("---")
        c1, c2, c3 = st.columns(3)
        with c1: selected_year = st.selectbox("📅 ปีภาษี", [
            "2567 (2024)", "2568 (2025)", "2569 (2026)", 
            "2570 (2027)", "2571 (2028)", "2572 (2029)", "2573 (2030)"
        ]).split("(")[1][:4]
        with c2: is_resident = st.radio("อาศัยในไทย?", ["เกิน 180 วัน", "ไม่ถึง 180 วัน"])
        with c3: other_income = st.number_input("รายได้อื่นๆ (บาท)", min_value=0.0, value=500000.0, step=50000.0)

        t_yr = tax_v[tax_v['Date'].str.endswith(selected_year)]
        net_tax_gain_yr = t_yr["Taxable_Gain_THB"].sum()
        sum_wht_thb_yr = (t_yr["WHT_USD"] * t_yr["FX_Rate"]).sum()

        cf1, cf2, cf3 = st.columns(3)
        cf1.metric("📤 โอนออกปีนี้", f"฿{t_yr['Out_THB'].sum():,.2f}")
        cf2.metric("📥 นำกลับปีนี้", f"฿{t_yr['In_THB'].sum():,.2f}")
        cf3.metric("🚨 กำไรที่เสียภาษี", f"฿{net_tax_gain_yr:,.2f}", delta_color="inverse")

        st.markdown("---")
        with st.expander("📝 ลดหย่อน", expanded=False):
            d1, d2 = st.columns(2)
            s_deduct = d1.checkbox("คู่สมรสไม่มีรายได้")
            c_count = d2.number_input("บุตร", min_value=0)
            inv1, inv2, inv3 = st.columns(3)
            life = inv1.number_input("ประกันชีวิต", min_value=0.0)
            health = inv2.number_input("ประกันสุขภาพ", min_value=0.0)
            pvd = inv3.number_input("PVD", min_value=0.0)
        
        t_deduct = min(other_income * 0.5, 100000) + 60000 + (60000 if s_deduct else 0) + (c_count * 30000) + min(life + min(health, 25000), 100000) + min(pvd, 500000)
        
        if st.button(f"📊 ประเมินภาษี {selected_year}", type="primary", use_container_width=True):
            if "ไม่ถึง" in is_resident: st.success("🎉 ยกเว้นภาษี (อยู่ในไทยไม่ถึง 180 วัน)")
            elif net_tax_gain_yr <= 0: st.success(f"🎉 ปี {selected_year} ไม่มีส่วนกำไรที่ถูกดึงกลับเข้าประเทศ")
            else:
                def calc_tax(n):
                    if n > 5000000: return (n-5000000)*0.35 + 1265000
                    if n > 2000000: return (n-2000000)*0.30 + 365000
                    if n > 1000000: return (n-1000000)*0.25 + 115000
                    if n > 750000: return (n-750000)*0.20 + 65000
                    if n > 500000: return (n-500000)*0.15 + 27500
                    if n > 300000: return (n-300000)*0.10 + 7500
                    if n > 150000: return (n-150000)*0.05
                    return 0
                tax_raw = calc_tax(max(0, (other_income + net_tax_gain_yr) - t_deduct)) - calc_tax(max(0, other_income - t_deduct))
                st.subheader(f"ผลการประเมิน (ปี {selected_year})")
                r1, r2 = st.columns(2)
                r1.metric("ภาษีจากพอร์ต ตปท.", f"฿{tax_raw:,.2f}")
                r2.metric(f"🚨 จ่ายเพิ่มจริง (หักเครดิต ตปท.)", f"฿{max(0, tax_raw - sum_wht_thb_yr):,.2f}")

# ==========================================
# หน้า 6: พิทบูลพยากรณ์ (Monte Carlo Forecast)
# ==========================================
if st.session_state["logged_in"]:
    with tabs[5]:
        st.markdown(f"## 🔮 พิทบูลพยากรณ์ (AI Monte Carlo Simulation) : {ticker}")
        st.info("💡 **หลักการทำงาน:** ระบบจำลองมอนติคาร์โล (Monte Carlo) จะนำความผันผวนของราคาหุ้นในอดีต 1 ปี มาสุ่มสร้างเส้นทางจำลอง 100 รูปแบบ เพื่อคำนวณหาความน่าจะเป็นของราคาในอนาคต **(เป็นเพียงความน่าจะเป็นทางสถิติเท่านั้น ไม่ใช่ข้อเท็จจริงในอนาคต)**")
        
        sim_days = st.slider("จำนวนวันพยากรณ์ไปข้างหน้า:", 5, 90, 30)
        
        if st.button("🎲 เริ่มการจำลองพยากรณ์อนาคต", type="primary", use_container_width=True):
            with st.spinner("พิทบูลกำลังเคี้ยวข้อมูลและคำนวณความน่าจะเป็น 100 เส้นทาง..."):
                sim_df, exp_p, up_b, low_b, last_price = run_monte_carlo(ticker, days_to_predict=sim_days)
                
                if sim_df is not None:
                    c1, c2, c3 = st.columns(3)
                    c1.metric("📉 กรณีเลวร้าย (Lower 5%)", f"${low_b:.2f}")
                    c2.metric("🎯 ราคาคาดหวัง (Expected)", f"${exp_p:.2f}")
                    c3.metric("📈 กรณีดีที่สุด (Upper 95%)", f"${up_b:.2f}")
                    
                    fig_sim = go.Figure()
                    for col in sim_df.columns:
                        fig_sim.add_trace(go.Scatter(x=sim_df.index, y=sim_df[col], mode='lines', line=dict(width=1, color='rgba(130, 177, 255, 0.1)'), showlegend=False))
                    
                    fig_sim.add_trace(go.Scatter(x=[0, sim_days-1], y=[last_price, exp_p], mode='lines+markers', name='Expected Path', line=dict(color='#00E676', width=3, dash='dash')))
                    fig_sim.add_hline(y=up_b, line_dash="dot", line_color="#FFD600", annotation_text="Upper Bound (95%)")
                    fig_sim.add_hline(y=low_b, line_dash="dot", line_color="#FF5252", annotation_text="Lower Bound (5%)")
                    
                    fig_sim.update_layout(title=f"การจำลอง 100 รูปแบบในอีก {sim_days} วันของ {ticker}", template="plotly_dark", height=500, xaxis_title="วันทำการในอนาคต", yaxis_title="ราคา (USD)")
                    st.plotly_chart(fig_sim, use_container_width=True)
                    
                    st.markdown("---")
                    st.markdown("#### 🐶 สรุปคำทำนายพิทบูล (Pitbull Analysis)")
                    upside = ((exp_p - last_price) / last_price) * 100
                    
                    if exp_p > last_price:
                        p_msg = f"🟢 **แนวโน้มเชิงบวก (Bullish Drift):** ในอีก {sim_days} วันข้างหน้า อิงจากความผันผวนทางสถิติ ราคามีโอกาสปรับตัวขึ้นไปที่ **${exp_p:.2f}** (บวก {upside:+.2f}%) แต่หากตลาดผันผวนแรงอาจลงไปแตะกรอบล่างที่ **${low_b:.2f}** แนะนำให้ใช้ข้อมูลนี้ประกอบกับกราฟเทคนิคเท่านั้น (อย่าเชื่อจนหมดใจ)"
                        st.success(p_msg)
                    else:
                        p_msg = f"🔴 **แนวโน้มอ่อนแอ (Bearish Drift):** ในอีก {sim_days} วันข้างหน้า ราคามีเกณฑ์แกว่งตัวออกข้างหรือปรับฐานลงไปที่ **${exp_p:.2f}** (ติดลบ {upside:+.2f}%) ระวังความเสี่ยงหากราคาหลุดลึกไปถึง **${low_b:.2f}** แนะนำให้ชะลอการลงทุน"
                        st.warning(p_msg)
                else:
                    st.error("ไม่สามารถดึงข้อมูลเพื่อจำลองได้ กรุณาลองใหม่อีกครั้งค่ะ")

# ==========================================
# หน้า 7: แผนการเทรด (Trading Plan)
# ==========================================
if st.session_state["logged_in"]:
    with tabs[6]:
        st.markdown(f"## 📝 แผนการเทรด (Trading Plan) : {ticker}")
        st.info("💡 **Position Sizing Calculator:** วางแผนจุดเข้าซื้อ จุดตัดขาดทุน และเป้าหมายทำกำไร เพื่อคำนวณจำนวนหุ้นที่เหมาะสมตามหลักบริหารความเสี่ยง (Risk Management)")
        
        if not df.empty:
            curr_price = df['Close'].iloc[-1]
            ema_50_val = df['E50'].iloc[-1]
            
            c_plan1, c_plan2 = st.columns(2)
            with c_plan1:
                st.markdown("#### 1️⃣ ตั้งค่าความเสี่ยง (Risk Setup)")
                plan_cap = st.number_input("เงินทุนรวมทั้งหมด ($)", value=float(t_cap), step=100.0)
                plan_risk_pct = st.number_input("ยอมรับความเสี่ยงที่จะขาดทุนต่อไม้ (%)", value=float(r_pct), step=0.5)
                risk_budget = plan_cap * (plan_risk_pct / 100.0)
                st.write(f"💸 **งบประมาณที่ยอมเสียได้สูงสุด (Risk Budget):** :red[${risk_budget:,.2f}]")

            with c_plan2:
                st.markdown("#### 2️⃣ จุดทำการ (Action Points)")
                plan_entry = st.number_input("🎯 ราคาตั้งใจจะเข้าซื้อ (Entry Price)", value=float(curr_price), step=0.5)
                
                default_sl = float(ema_50_val) if ema_50_val < curr_price else float(curr_price * 0.9)
                plan_sl = st.number_input("🛑 จุดตัดขาดทุน (Stop Loss)", value=default_sl, step=0.5)
                
                default_tp = plan_entry + ((plan_entry - plan_sl) * 2) if plan_entry > plan_sl else float(curr_price * 1.1)
                plan_tp = st.number_input("🏆 เป้าหมายทำกำไร (Take Profit)", value=default_tp, step=0.5)

            st.markdown("---")
            st.markdown("#### 📊 สรุปแผนการเทรด (Trade Summary)")

            if plan_entry > plan_sl:
                risk_per_share = plan_entry - plan_sl
                reward_per_share = plan_tp - plan_entry
                
                max_shares_raw = risk_budget / risk_per_share if risk_per_share > 0 else 0
                max_shares = math.floor(max_shares_raw)
                
                position_value = max_shares * plan_entry
                rr_ratio = reward_per_share / risk_per_share if risk_per_share > 0 else 0
                expected_profit = max_shares * reward_per_share

                if rr_ratio >= 2.0:
                    rr_status = "🟢 ดีเยี่ยม (Very Good)"
                    rr_color = "normal"
                elif rr_ratio >= 1.5:
                    rr_status = "🟡 พอใช้ได้ (Acceptable)"
                    rr_color = "off"
                else:
                    rr_status = "🔴 ไม่คุ้มเสี่ยง (Poor)"
                    rr_color = "inverse"

                c_sum1, c_sum2, c_sum3, c_sum4 = st.columns(4)
                c_sum1.metric("🛒 ซื้อได้สูงสุด", f"{max_shares:,} หุ้น")
                c_sum2.metric("💳 ใช้เงินลงทุนรวม", f"${position_value:,.2f}")
                c_sum3.metric("⚖️ Risk/Reward Ratio", f"1 : {rr_ratio:.2f}", rr_status, delta_color=rr_color)
                c_sum4.metric("💰 คาดหวังกำไรสุทธิ", f"${expected_profit:,.2f}")

                if position_value > plan_cap:
                    st.warning(f"⚠️ **คำเตือน:** เงินลงทุนที่ต้องใช้ (${position_value:,.2f}) มากกว่าเงินทุนรวมทั้งหมดที่คุณมี (${plan_cap:,.2f}) แนะนำให้ **ปรับลด % ความเสี่ยงลง** หรือเติมเงินทุนเข้าพอร์ตค่ะ")
                
                # --- ส่วนที่อัปเกรดเพื่อบันทึกข้อมูล ---
                st.markdown("#### 💾 บันทึกแผน (Save Plan)")
                c_save1, c_save2 = st.columns([7, 3])
                with c_save1:
                    plan_note = st.text_input("📝 หมายเหตุ (ตัวอย่าง: รอราคาย่อมาแตะ EMA50 ค่อยกดซื้อ)")
                with c_save2:
                    st.markdown("<br>", unsafe_allow_html=True)
                    if st.button("💾 บันทึกแผนนี้เก็บไว้ดูภายหลัง", type="primary", use_container_width=True):
                        new_plan = pd.DataFrame([{
                            "Date": current_date,
                            "Ticker": ticker,
                            "Entry": plan_entry,
                            "Stop_Loss": plan_sl,
                            "Take_Profit": plan_tp,
                            "Risk_Budget": risk_budget,
                            "Max_Shares": max_shares,
                            "Note": plan_note
                        }])
                        st.session_state.trading_plans = pd.concat([st.session_state.trading_plans, new_plan], ignore_index=True)
                        if save_df_to_sheet("Trading_Plans", st.session_state.trading_plans):
                            st.success("✅ บันทึกแผนสำเร็จ! เลื่อนลงไปดูที่ตารางด้านล่างได้เลยค่ะ")
                        else:
                            st.error("❌ บันทึกไม่สำเร็จ กรุณาลองใหม่อีกครั้ง")

                st.markdown("---")
                st.markdown("### 📚 ประวัติแผนการเทรดของฉัน (Saved Plans)")
                st.info("💡 แผนทั้งหมดในตารางนี้จะถูกบันทึกขึ้นไปเก็บบน Google Sheets อัตโนมัติ (อยู่ในชีทใหม่ชื่อ 'Trading_Plans' ค่ะ)")
                
                # --- [อัปเกรด V4.59] ระบบตารางที่มีปุ่มลบสำหรับแท็บเล็ต ---
                display_df = st.session_state.trading_plans.copy()
                
                if not display_df.empty:
                    # แทรกคอลัมน์ใหม่ด้านหน้าสุด เอาไว้ให้ลูกค้าติ๊กถูก
                    display_df.insert(0, "Select_Delete", False)
                    
                    ed_plans = st.data_editor(display_df, num_rows="dynamic", use_container_width=True,
                        column_config={
                            "Select_Delete": st.column_config.CheckboxColumn("🗑️ เลือกเพื่อลบ", default=False),
                            "Date": "วันที่บันทึก",
                            "Ticker": "ชื่อหุ้น",
                            "Entry": st.column_config.NumberColumn("ราคาเข้าซื้อ ($)", format="%.2f"),
                            "Stop_Loss": st.column_config.NumberColumn("จุดตัดขาดทุน ($)", format="%.2f"),
                            "Take_Profit": st.column_config.NumberColumn("เป้าทำกำไร ($)", format="%.2f"),
                            "Risk_Budget": st.column_config.NumberColumn("งบความเสี่ยง ($)", format="%.2f"),
                            "Max_Shares": st.column_config.NumberColumn("โควตาที่ซื้อได้ (หุ้น)", format="%d"),
                            "Note": "หมายเหตุ"
                        })
                    
                    # เช็คว่ามีการติ๊กถูกในช่องลบหรือไม่
                    if ed_plans["Select_Delete"].any():
                        st.warning("⚠️ คุณได้ติ๊กเลือกแผนที่ต้องการลบแล้ว กดปุ่มสีแดงด้านล่างเพื่อยืนยันการลบถาวรค่ะ")
                        if st.button("🗑️ ยืนยันการลบแผนที่เลือก", type="primary", use_container_width=True):
                            # กรองเอาเฉพาะบรรทัดที่ไม่ได้ติ๊กถูก แล้วเซฟทับ
                            st.session_state.trading_plans = ed_plans[~ed_plans["Select_Delete"]].drop(columns=["Select_Delete"])
                            save_df_to_sheet("Trading_Plans", st.session_state.trading_plans)
                            st.success("✅ ลบข้อมูลสำเร็จ!")
                            time.sleep(1)
                            st.rerun()
                    else:
                        # กรณีมีการแก้ไขข้อมูลอื่นๆ ในตาราง
                        updated_df = ed_plans.drop(columns=["Select_Delete"])
                        if not updated_df.equals(st.session_state.trading_plans):
                            st.session_state.trading_plans = updated_df.copy()
                            save_df_to_sheet("Trading_Plans", st.session_state.trading_plans)
                            st.rerun()
                else:
                    st.info("ยังไม่มีประวัติแผนการเทรดค่ะ ลองคำนวณและกดบันทึกแผนด้านบนดูนะคะ!")

            else:
                st.error("⚠️ การคำนวณผิดพลาด: **จุดตัดขาดทุน (Stop Loss)** ต้องตั้งให้น้อยกว่า **ราคาเข้าซื้อ (Entry Price)** เสมอนะคะ")
        else:
            st.warning("⏳ กรุณารอข้อมูลกราฟโหลดเสร็จสิ้นเพื่อคำนวณแผนการเทรดค่ะ...")
            import sqlite3
import pandas as pd
import numpy as np
import yfinance as yf

# ==========================================
# 🗄️ ส่วนที่ 1: การตั้งค่าระบบฐานข้อมูลออฟไลน์
# ==========================================
def init_backtest_db():
    conn = sqlite3.connect("backtest_history.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS backtest_trades (
            trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT,
            entry_date TEXT,
            entry_price REAL,
            exit_date TEXT,
            exit_price REAL,
            p_l_usd REAL,
            p_l_pct REAL,
            exit_reason TEXT
        )
    """)
    conn.commit()
    conn.close()

# ==========================================
# 📊 ส่วนที่ 2: ฟังก์ชันคำนวณอินดิเคเตอร์ 3 ประสาน
# ==========================================
def calculate_indicators(df):
    # 1. EMA 50
    df['EMA50'] = df['Close'].ewm(span=50, adjust=False).mean()
    
    # 2. RSI 14
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14).mean()
    df['RSI'] = 100 - (100 / (1 + gain/loss))
    
    # 3. MACD (12, 26, 9)
    df['MACD'] = df['Close'].ewm(span=12, adjust=False).mean() - df['Close'].ewm(span=26, adjust=False).mean()
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    
    return df.dropna(subset=['EMA50', 'RSI', 'MACD', 'Signal'])

# ==========================================
# 🚀 ส่วนที่ 3: ระบบประมวลผล Backtest Engine
# ==========================================
def run_3_prasan_backtest(ticker_symbol, period_years=3, initial_capital=10000.0):
    # ดึงข้อมูลย้อนหลังตามขอบเขตที่กำหนด
    end_date = pd.Timestamp.now()
    start_date = end_date - pd.DateOffset(years=period_years)
    
    df = yf.download(ticker_symbol, start=start_date, end=end_date, progress=False)
    if df.empty:
        return "❌ ไม่พบข้อมูลสินทรัพย์"
        
    df = calculate_indicators(df)
    
    # สถานะการจำลองพอร์ต
    in_position = False
    entry_price = 0.0
    entry_date = None
    shares_held = 0
    cash = initial_capital
    
    trade_logs = []
    
    # วิ่งไล่ตรวจเช็คราคาทีละวันทำการ (เคร่งครัดตามกฎ ไร้อคติมองอนาคต)
    for idx, row in df.iterrows():
        current_price = float(row['Close'])
        current_date_str = idx.strftime("%d/%m/%Y")
        
        # 🟢 เงื่อนไขการเข้าซื้อ (Entry Rule)
        if not in_position:
            if current_price > float(row['EMA50']) and float(row['MACD']) > float(row['Signal']) and 50 <= float(row['RSI']) <= 65:
                in_position = True
                entry_price = current_price
                entry_date = current_date_str
                # แบ่งเงินซื้อหมดไม้ชั่วคราวเพื่อคำนวณสถิติ
                shares_held = cash / entry_price
                cash = 0.0
                
        # 🔴 เงื่อนไขการขายออก (Exit Rule)
        elif in_position:
            is_rsi_overbought = float(row['RSI']) > 70
            is_momentum_negative = float(row['MACD']) < float(row['Signal'])
            
            if is_rsi_overbought or is_momentum_negative:
                in_position = False
                exit_price = current_price
                cash = shares_held * exit_price
                
                # คำนวณผลลัพธ์ประจำไม้
                p_l_usd = (exit_price - entry_price) * shares_held
                p_l_pct = ((exit_price - entry_price) / entry_price) * 100
                reason = "RSI Overbought" if is_rsi_overbought else "MACD Dead Cross"
                
                trade_logs.append({
                    "ticker": ticker_symbol,
                    "entry_date": entry_date,
                    "entry_price": entry_price,
                    "exit_date": current_date_str,
                    "exit_price": exit_price,
                    "p_l_usd": p_l_usd,
                    "p_l_pct": p_l_pct,
                    "exit_reason": reason
                })
                shares_held = 0
                
    # นำเงินกลับมาคำนวณมูลค่าสุทธิกรณีไม้สุดท้ายยังไม่ปิดสัญญา
    final_portfolio_value = cash if cash > 0 else (shares_held * float(df['Close'].iloc[-1]))
    
    return pd.DataFrame(trade_logs), final_portfolio_value

# ==========================================
# 📊 ส่วนที่ 4: การคำนวณสถิติระดับสูง (Advanced Metrics)
# ==========================================
def calculate_performance_metrics(trades_df, initial_capital, final_value):
    if trades_df.empty:
        return {}
        
    win_trades = trades_df[trades_df['p_l_usd'] > 0]
    win_rate = (len(win_trades) / len(trades_df)) * 100
    total_return_pct = ((final_value - initial_capital) / initial_capital) * 100
    
    # คำนวณ Maximum Drawdown แบบคร่าวๆ จากประวัติไม้เทรด
    trades_df['cum_balance'] = initial_capital + trades_df['p_l_usd'].cumsum()
    trades_df['peak'] = trades_df['cum_balance'].cummax()
    trades_df['drawdown'] = (trades_df['cum_balance'] - trades_df['peak']) / trades_df['peak'] * 100
    max_drawdown = trades_df['drawdown'].min()
    
    return {
        "win_rate": win_rate,
        "total_trades": len(trades_df),
        "final_value": final_value,
        "total_return_pct": total_return_pct,
        "max_drawdown": max_drawdown
    }

            

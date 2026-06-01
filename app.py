import json
import time
import os
import math
import sqlite3
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
    st.set_page_config(page_title="Strategic Hub 4.75", page_icon=browser_icon, layout="wide")
else:
    st.set_page_config(page_title="Strategic Hub 4.75", page_icon="📈", layout="wide")

st.markdown("""
    <style>
    .stButton>button { border-radius: 12px; font-weight: bold; transition: all 0.3s ease; border: 1px solid #4CAF50; }
    .stButton>button:hover { transform: translateY(-2px); box-shadow: 0 6px 15px rgba(76, 175, 80, 0.4); border-color: #4CAF50; }
    div[data-testid="stMetricValue"] { padding-bottom: 0px; font-size: 1.5rem !important; white-space: pre-wrap !important; word-break: break-word !important; }
    [data-testid="stMetricDelta"] > div { white-space: pre-wrap !important; word-break: break-word !important; }
    .stSpinner > div > div { border-top-color: #deff9a !important; }
    [data-testid="stSidebar"] { background-color: #0e1117; }
    [data-testid="stDataFrame"] { border-radius: 10px; overflow: hidden; }
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
if "current_ticker" not in st.session_state: st.session_state.current_ticker = "RKLB"
if "logged_in" not in st.session_state: st.session_state["logged_in"] = False
if "radar_tickers" not in st.session_state:
    st.session_state.radar_tickers = ["ASTS", "RKLB", "NVTS", "IREN", "RGTI", "C", "TSLA", "PLTR", "ONDS", "OKLO", "EOSE", "IONQ", "NOW", "MNDY", "ADBE", "CRWD", "AMKR", "NVDA", "MSFT", "GOOGL"]

@st.cache_resource(ttl=3600)
def init_connection():
    creds_dict = json.loads(st.secrets["google_creds_json"])
    sheet_url = st.secrets["spreadsheet_url"]
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc = gspread.authorize(credentials)
    return gc.open_by_url(sheet_url)

try: sh = init_connection()
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
        ws = sh.worksheet("Ledger")
        records = ws.get_all_records()
        if not records: return clean_df_types(pd.DataFrame(columns=["Date", "Action", "Ticker", "Price", "Shares", "Amount_USD", "Running_Balance", "FX_Rate", "WHT_USD", "Ref_Doc"]))
        df = pd.DataFrame(records).replace(["", "None", "nan", None], np.nan).dropna(how="all")
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
        ws = sh.worksheet("Trading_Plans")
        records = ws.get_all_records()
        if records:
            df = pd.DataFrame(records)
            for col in req_cols:
                if col not in df.columns: df[col] = ""
            return df[req_cols]
    except: pass
    return pd.DataFrame(columns=req_cols)

def save_df_to_sheet(worksheet_name, df):
    global sh
    try: ws = sh.worksheet(worksheet_name)
    except:
        try:
            sh = init_connection()
            ws = sh.worksheet(worksheet_name)
        except gspread.exceptions.WorksheetNotFound:
            ws = sh.add_worksheet(title=worksheet_name, rows="1000", cols="15")
    try:
        ws.clear()
        clean_df = df.copy().astype(str).replace(["nan", "None", "<NA>", "NaN"], "")
        ws.update(values=[clean_df.columns.values.tolist()] + clean_df.values.tolist(), range_name='A1')
        return True
    except Exception as e:
        st.error(f"❌ เกิดข้อผิดพลาดขณะเขียนข้อมูลลง Cloud: {e}")
        return False

# ==========================================
# 🧪 3. ส่วนระบบจำลองกลยุทธ์ (Backtest Engine)
# ==========================================
def init_backtest_db():
    conn = sqlite3.connect("backtest_history.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS backtest_trades (
            trade_id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, entry_date TEXT, entry_price REAL,
            exit_date TEXT, exit_price REAL, p_l_usd REAL, p_l_pct REAL, exit_reason TEXT
        )
    """)
    conn.commit()
    conn.close()

def run_3_prasan_backtest(ticker_symbol, period_years=3, initial_capital=10000.0):
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=period_years*365)
    try:
        df_hist = yf.Ticker(ticker_symbol).history(start=start_dt, end=end_dt, interval="1d")
        if df_hist.empty: return pd.DataFrame(), initial_capital
    except: return pd.DataFrame(), initial_capital

    df_hist['EMA50'] = df_hist['Close'].ewm(span=50, adjust=False).mean()
    delta = df_hist['Close'].diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14).mean()
    df_hist['RSI'] = 100 - (100 / (1 + gain/loss))
    df_hist['MACD'] = df_hist['Close'].ewm(span=12, adjust=False).mean() - df_hist['Close'].ewm(span=26, adjust=False).mean()
    df_hist['Signal'] = df_hist['MACD'].ewm(span=9, adjust=False).mean()
    df_clean = df_hist.dropna(subset=['EMA50', 'RSI', 'MACD', 'Signal'])

    in_position, entry_p, entry_d, shares, cash = False, 0.0, None, 0.0, initial_capital
    logs = []

    for idx, row in df_clean.iterrows():
        close_p, rsi_v, macd_v, sig_v, ema_v = float(row['Close']), float(row['RSI']), float(row['MACD']), float(row['Signal']), float(row['EMA50'])
        date_str = idx.strftime("%d/%m/%Y")
        if not in_position:
            if close_p > ema_v and macd_v > sig_v and 50 <= rsi_v <= 65:
                in_position, entry_p, entry_d, shares, cash = True, close_p, date_str, cash / close_p, 0.0
        elif in_position:
            if rsi_v > 70 or macd_v < sig_v:
                in_position, exit_p = False, close_p
                cash = shares * exit_p
                logs.append({"ticker": ticker_symbol, "entry_date": entry_d, "entry_price": entry_p, "exit_date": date_str, "exit_price": exit_p, "p_l_usd": (exit_p - entry_p) * shares, "p_l_pct": ((exit_p - entry_p) / entry_p) * 100, "exit_reason": "RSI Overbought (>70)" if rsi_v > 70 else "โมเมนตัมตัดลง (MACD)"})
                shares = 0.0

    final_val = cash if cash > 0 else (shares * float(df_clean['Close'].iloc[-1]))
    return pd.DataFrame(logs), final_val

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
# 📊 4. ลอจิกบัญชี & ฟังก์ชันคำนวณตลาด
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
        action, ticker_item = str(row.get("Action", "")).strip(), str(row.get("Ticker", "")).strip().upper()
        p, s = float(row.get("Price", 0.0)), float(row.get("Shares", 0.0))
        trade_value = p * s
        manual_amount = float(row.get("Amount_USD", 0.0))
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
                cogs = (hld[ticker_item]["total_cost"] / hld[ticker_item]["shares"]) * s
                stat["realized_profit"] += trade_value - cogs
                hld[ticker_item]["shares"] -= s; hld[ticker_item]["total_cost"] -= cogs
                old_ref = str(row.get("Ref_Doc", "")).replace("nan", "")
                if "P/L:" not in old_ref: df.at[idx, "Ref_Doc"] = f"P/L: ${trade_value - cogs:.2f} | {old_ref}"
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
            if df.empty: df = yf.download(ticker_symbol, period=p, interval=i, progress=False)
            if not df.empty:
                df = df.dropna(subset=['Close'])
                if not df.empty: break
        except Exception: pass
        time.sleep(1.5)
    if df.empty: return pd.DataFrame(), {}, None, None, {}
    
    try:
        info = s.info
        th_summary = translate_to_thai(info.get('longBusinessSummary', 'N/A'))
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
                market_signal["smart_money"] = "Risk ON 🟢" if (hyg/ief).iloc[-1] > (hyg/ief).ewm(span=20).mean().iloc[-1] else "Risk OFF 🔴"
        except: pass
        
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
        
        # --- กู้คืนข้อมูลพื้นฐาน Fundamental อย่างครบถ้วน ---
        earnings_date = "N/A"
        try:
            cal = s.calendar
            if isinstance(cal, dict) and 'Earnings Date' in cal:
                e_dates = cal['Earnings Date']
                if isinstance(e_dates, list) and len(e_dates) > 0:
                    earnings_date = e_dates[0].strftime("%d/%m/%Y")
        except: pass
        if earnings_date == "N/A" and info.get('earningsTimestamp'):
            earnings_date = datetime.fromtimestamp(info.get('earningsTimestamp'), tz=timezone.utc).strftime("%d/%m/%Y")
        
        fund = {
            "ps": f"{float(info.get('priceToSalesTrailing12Months', 0) or 0):.2f}", 
            "pe": f"{float(info.get('trailingPE', 0) or 0):.2f}", 
            "roe": f"{float(info.get('returnOnEquity', 0) or 0)*100:.2f}%",
            "rev_growth": f"{float(info.get('revenueGrowth', 0) or 0)*100:.2f}%",
            "dividend": f"{(float(div_y) * 100):.2f}%" if div_y else "ไม่มีปันผล",
            "earnings_date": earnings_date if earnings_date != "N/A" else "รอประกาศ", 
            "business_desc_th": th_summary,
            "industry": info.get('industry', 'N/A'), "sector": info.get('sector', 'N/A'),
            "location": info.get('country', 'N/A'), "website": info.get('website', '#'),
            "pe_val": float(info.get('trailingPE', 0) or 0), "roe_val": float(info.get('returnOnEquity', 0) or 0)
        }
        
        last = df['Close'].iloc[-1]
        v = df['Close'].pct_change().tail(14).std()
        tr = "ขึ้น 📈" if last > df['E50'].iloc[-1] else "ลง 📉"
        mat = {"l": last * (1 - v*0.5), "u": last * (1 + v*1.0), "tr": tr}
        atr = df['High'].tail(14).max() - df['Low'].tail(14).min()
        levels = {"r1": last + (atr * 0.5), "r2": last + (atr * 1.0), "r3": last + (atr * 1.5), "r4": last + (atr * 2.0), "s1": last - (atr * 0.5), "s2": last - (atr * 1.0), "s3": last - (atr * 1.5)}
        return df, fund, mat, market_signal, levels
    except Exception: return pd.DataFrame(), {}, None, None, {}

@st.cache_data(ttl=300)
def run_ai_screener(tickers):
    if not tickers: return pd.DataFrame()
    results = []
    for t in tickers:
        try:
            hist = yf.Ticker(t).history(period="6mo")
            if hist.empty: continue
            close = hist['Close'].iloc[-1]
            ema50 = hist['Close'].ewm(span=50).mean().iloc[-1]
            delta = hist['Close'].diff()
            gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14).mean()
            loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14).mean()
            rsi_val = (100 - (100 / (1 + gain/loss))).iloc[-1]
            macd = hist['Close'].ewm(span=12).mean() - hist['Close'].ewm(span=26).mean()
            sig = macd.ewm(span=9).mean()
            action = "⏳ WAIT (รอดูทรง)"
            if close > ema50 and macd.iloc[-1] > sig.iloc[-1] and rsi_val < 65: action = "⭐ STRONG BUY"
            elif close < ema50 and macd.iloc[-1] > sig.iloc[-1] and rsi_val < 35: action = "⚡ SPECULATE"
            elif close > ema50 and rsi_val >= 70: action = "🔥 OVERBOUGHT"
            results.append({"หุ้น": t, "ราคาล่าสุด": f"${close:.2f}", "EMA50": f"${ema50:.2f}", "RSI": f"{rsi_val:.1f}", "คำแนะนำ AI": action})
        except: pass
    return pd.DataFrame(results)

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
            count, price, price_series = 0, last_price, []
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
    except: return None, 0, 0, 0, 0

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

# ==========================================
# 🎛️ 5. UI Layout: แถบเมนูด้านซ้าย (Sidebar)
# ==========================================
with st.sidebar:
    if os.path.exists(logo_path): st.image(logo_path, use_container_width=True)
    else: st.title("🛡️ Strategic Hub 4.75")
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
    st.info("👈 กรุณาพิมพ์ชื่อหุ้นในช่องค้นหาด้านซ้ายมือ แล้วกด Enter ค่ะ")
    st.stop()

holdings = {}
if st.session_state["logged_in"]:
    sorted_df, cb, l_stat, r_bals, holdings = calculate_stats(st.session_state.trade_ledger)
    st.session_state.trade_ledger = sorted_df

with st.spinner("⏳ กำลังดึงข้อมูลสดจากตลาด..."):
    df, fund, matrix, market_signal, levels = load_pro_data(ticker, tf_option)

tabs_list = ["📊 วิเคราะห์รายตัว", "🔬 หาจุดเข้าซื้อ (Technical)", "🎯 เรดาร์สแกนหุ้น"]
if st.session_state["logged_in"]: 
    tabs_list.extend(["💼 บัญชีลงทุน", "🧾 ระบบภาษี", "🔮 พิทบูลพยากรณ์", "📝 แผนการเทรด", "🧪 แบคเทส 3 ประสาน"])
tabs = st.tabs(tabs_list)

# ==========================================
# หน้า 1: วิเคราะห์รายตัว (ภาพรวมหลัก & คืนชีพข้อมูลพื้นฐาน)
# ==========================================
with tabs[0]:
    if not df.empty:
        last_p = df['Close'].iloc[-1]
        prev_p = df['Close'].iloc[-2] if len(df) > 1 else last_p
        rsi_val = df['RSI'].iloc[-1]
        is_uptrend = last_p > df['E50'].iloc[-1]
        is_bullish_macd = df['MACD'].iloc[-1] > df['Sig'].iloc[-1]
        daily_diff = last_p - prev_p
        daily_pct = (daily_diff / prev_p) * 100 if prev_p > 0 else 0.0
        
        st.markdown(f"## 📈 {ticker} | <span style='color:#00E676;'>${last_p:,.2f}</span>", unsafe_allow_html=True)
        m_c1, m_c2 = st.columns(2)
        m_c1.metric("💵 ราคาตลาดล่าสุด (Real-Time)", f"${last_p:,.2f}")
        m_c2.metric("📊 การเปลี่ยนแปลงประจำวัน", f"{'+' if daily_diff >= 0 else ''}{daily_diff:,.2f} USD", delta=f"{daily_pct:+.2f}%")
        
        with st.expander("🏢 ข้อมูลธุรกิจ (Company Profile)"):
            st.info(f"{fund.get('business_desc_th', 'ไม่มีข้อมูล')}")

        spy_t = market_signal.get("spy_trend", "N/A")
        spy_p = market_signal.get("spy_price", 0.0)
        v_val = market_signal.get("vix", 0.0)
        vix_ts = market_signal.get("vix_ts", 0.0)
        sm_flow = market_signal.get("smart_money", "N/A")
        
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("ตลาดโลก (S&P 500)", f"{spy_p:,.2f}" if spy_p > 0 else "N/A", spy_t)
        m2.metric("ความกลัว (VIX)", f"{v_val:.2f}", "Risk ON" if v_val < 20 else "Panic")
        m3.metric("โครงสร้าง VIX/VIX3M", f"{vix_ts:.2f}", "🟢 สงบ" if vix_ts < 1 else "🔴 ตระหนก")
        m4.metric("เงินใหญ่ (HYG/IEF)", "Credit Flow", sm_flow)

        if "ขึ้น" in spy_t and (v_val < 25) and is_uptrend and is_bullish_macd and rsi_val < 70:
            rec, color, msg = "STRONG BUY / HOLD", "#00E676", "ตลาดเอื้ออำนวย หุ้นเป็นขาขึ้นเต็มตัว โมเมนตัมบวก แนะนำให้สะสมหรือรันเทรนด์ต่อ"
        elif is_uptrend and rsi_val >= 70:
            rec, color, msg = "HOLD / TAKE PROFIT", "#FFD600", "หุ้นเข้าเขตซื้อมากเกินไป ไม่ควรไล่ราคา แนะนำยก Stop Loss ตาม"
        elif not is_uptrend and is_bullish_macd and rsi_val < 35:
            rec, color, msg = "SPECULATIVE BUY", "#2962FF", "เหมาะเก็งกำไรระยะสั้นลุ้นรีบาวด์ (ต้องมีจุดตัดขาดทุนชัดเจน)"
        elif not is_uptrend:
            rec, color, msg = "AVOID / WAIT", "#FF5252", "ภาพรวมเป็นขาลง โมเมนตัมอ่อนแอ แนะนำให้รอดูสถานการณ์ทับมือรักษาเงินต้น"
        else:
            rec, color, msg = "NEUTRAL / SIDEWAY", "#B0BEC5", "กราฟแกว่งตัว รอเลือกทาง แนะนำเทรดในกรอบสั้นๆ"

        st.markdown(f'<div class="pro-box" style="border-left: 8px solid {color};"><h4>🤵 ทัศนะเทรดเดอร์: {rec}</h4><p>{msg}</p></div>', unsafe_allow_html=True)
        
        c_l, c_r = st.columns([7, 3])
        with c_l:
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close']), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['E50'], line=dict(color='#FF6D00', width=2), name="EMA 50"), row=1, col=1)
            fig.add_trace(go.Bar(x=df.index, y=df['Hist'], marker_color=['#00E676' if v >= 0 else '#FF5252' for v in df['Hist']]), row=2, col=1)
            fig.update_layout(template="plotly_dark", height=450, showlegend=False, xaxis_rangeslider_visible=False, margin=dict(l=0,r=0,t=0,b=0))
            st.plotly_chart(fig, use_container_width=True)
            
            # --- [คืนชีพ 100%] ข้อมูลพื้นฐาน Fundamental กลับมาแล้ว! ---
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
            if (pe_v <= 0) or (fund.get('roe_val', 0) < 0): 
                st.error("⚠️ หุ้นเก็งกำไรความเสี่ยงสูง (ขาดทุน หรือ ROE ติดลบ) ระบบจะปรับลดงบเข้าซื้ออัตโนมัติ")

        with c_r:
            if levels:
                st.markdown(f"""
                <div class="pro-box" style="border-top: 3px solid #FF5252;"><div class="pro-title c-red">แนวต้าน (RESISTANCE)</div><div class="pro-row"><span>ด่านแรก</span> <span>${levels['r1']:.2f}</span></div><div class="pro-row"><span>ด่านจริง</span> <span>${levels['r2']:.2f}</span></div></div>
                <div class="pro-box" style="border-top: 3px solid #00E676;"><div class="pro-title c-green">แนวรับ (SUPPORT)</div><div class="pro-row"><span>แนวรับแรก</span> <span>${levels['s1']:.2f}</span></div><div class="pro-row"><span>แนวรับลึก</span> <span>${levels['s2']:.2f}</span></div></div>
                """, unsafe_allow_html=True)
    else: st.warning("❌ ไม่พบข้อมูลราคาตลาด")

# ==========================================
# หน้า 2: โซนเข้าซื้อเทคนิคอล (คืนชีพบทสรุปเอกฉันท์ & กราฟซูมฟิโบนาชชี)
# ==========================================
with tabs[1]:
    if not df.empty:
        st.markdown(f"## 🔬 โซนเข้าซื้อ (Action Zones) : {ticker}")
        last_close = df['Close'].iloc[-1]
        rsi = df['RSI'].iloc[-1]
        macd = df['MACD'].iloc[-1]
        sig = df['Sig'].iloc[-1]
        ema50 = df['E50'].iloc[-1]
        is_bullish_macd = macd > sig
        
        if last_close > df['E200'].iloc[-1]:
            trend_main = "🟢 ขาขึ้นระยะยาว (Bullish)"
            if last_close < df['E25'].iloc[-1] and last_close >= (ema50 * 0.98) and rsi < 50:
                m_col, m_sig, m_desc = "#00E676", "🟢 โดนแรงขายย่อตัวมาที่แนวรับ (Buy the Dip)", "ราคาย่อตัวลงมาพักฐานใกล้เส้นแนวรับ EMA 50 ความร้อนแรงลดลง เป็นจังหวะแบ่งไม้สะสม"
            elif not is_bullish_macd or rsi >= 70:
                m_col, m_sig, m_desc = "#FF9800", "⚠️ PULLBACK WARNING (ระวังการพักฐาน)", "ระยะยาวเป็นขาขึ้น แต่ระยะสั้นโมเมนตัมหักหัวลงพักฐาน (MACD ตัดลงใต้ Signal) หรือซื้อมากเกินไป ห้ามไล่ซื้อเด็ดขาด"
            else:
                m_col, m_sig, m_desc = "#B0BEC5", "⏳ รอจังหวะพักฐานเสร็จสมบูรณ์", "ราคากำลังแกว่งตัวสะสมพลังเพื่อเลือกทาง"
        else:
            trend_main = "🔴 ขาลงระยะยาว (Bearish)"
            m_col, m_sig, m_desc = "#FF5252", "❌ ทับมือ ห้ามรับมีดความเสี่ยงสูง", "ราคาอยู่ใต้เส้นเทรนด์ใหญ่ขาลง สัญญาณอ่อนแรง ไม่เหมาะแก่การถือลงทุน"

        st.markdown(f'<div class="pro-box" style="border-top: 4px solid {m_col};"><h3>{m_sig}</h3><p>{m_desc}</p></div>', unsafe_allow_html=True)
        st.markdown("---")

        # --- [คืนชีพ 100%] บทสรุปเอกฉันท์ 3 มิติ (The Objective Consensus) ---
        st.markdown("### 👑 บทสรุปเอกฉันท์ (The Objective Consensus)")
        with st.spinner("⏳ ประมวลผลข้อมูล มหภาค + เทคนิค + พิทบูลพยากรณ์ อย่างเป็นกลาง..."):
            sim_df_quick, exp_p_quick, up_b_quick, low_b_quick, _ = run_monte_carlo(ticker, days_to_predict=30)
            if sim_df_quick is not None:
                upside_quick = ((exp_p_quick - last_close) / last_close) * 100
                if last_close > ema50 and is_bullish_macd and rsi < 70 and exp_p_quick > last_close and is_market_good:
                    mc_col, mc_sig = "#00E676", "🌟 FULLY ALIGNED (สอดคล้องทุกมิติ: ทยอยสะสม)"
                    mc_desc = f"สอดคล้อง 3 มิติ! **ตลาดโลกเป็นใจ** + **กราฟเทคนิค**เป็นขาขึ้นและโมเมนตัมบวก หนุนด้วย**สถิติพยากรณ์**ที่ให้เป้าหมาย 30 วันไปที่ **${exp_p_quick:.2f}** (+{upside_quick:.2f}%) แนะนำย่อซื้อที่แนวรับ"
                elif last_close > df['E200'].iloc[-1] and (not is_bullish_macd or rsi >= 70):
                    mc_col, mc_sig = "#FF9800", "⚠️ PULLBACK WARNING (สัญญาณพักฐาน: ชะลอการลงทุน)"
                    mc_desc = f"ระวัง! เทรนด์ยาวยังเป็นขาขึ้น แต่ **ภาพระยะสั้นโมเมนตัมกำลังหักหัวลง (MACD อ่อนแรง) หรือเข้าเขต Overbought** แม้สถิติจะมองเป้าที่ **${exp_p_quick:.2f}** แนะนำให้ **ทับมือ (Wait & See)** ไม่ควรไล่ราคา"
                elif last_close < ema50 and exp_p_quick < last_close:
                    mc_col, mc_sig = "#FF5252", "🚨 HIGH RISK (ทิศทางขาลง: หลีกเลี่ยง)"
                    mc_desc = f"อันตราย! **กราฟเทคนิค**เป็นขาลงชัดเจน สอดคล้องกับ**สถิติพยากรณ์**ที่ประเมินว่าราคาจะไหลลงไปที่ **${exp_p_quick:.2f}** ({upside_quick:.2f}%) แนะนำให้ 'หลีกเลี่ยง' หรือตั้งจุดหนีตาย"
                else:
                    mc_col, mc_sig = "#FFD600", "⚖️ NEUTRAL / DIVERGENCE (สัญญาณขัดแย้ง: รอเลือกทาง)"
                    mc_desc = f"สัญญาณจาก 3 มิติยังขัดแย้งกัน แนะนำให้ **เทรดอย่างระมัดระวังในกรอบแคบๆ** หรือรอดูความชัดเจนจนกว่าแนวโน้มและโมเมนตัมจะไปในทิศทางเดียวกัน"

                st.markdown(f'<div style="background-color: #1E1E1E; border-left: 8px solid {mc_col}; padding: 20px; border-radius: 8px; margin: 15px 0;"><h4 style="color: {mc_col}; margin-top: 0;">{mc_sig}</h4><p style="color: #E0E0E0; margin-bottom: 0;">{mc_desc}</p></div>', unsafe_allow_html=True)
            else: st.warning("⚠️ ไม่สามารถดึงข้อมูลพิทบูลมาสรุปผลได้ในขณะนี้")
        st.markdown("---")
        
        # --- [คืนชีพ 100%] กราฟเจาะลึก 3 เดือน & ระบบเส้น Fibonacci ตัวเต็ม ---
        if tf_option == "1D (รายวัน)": zoom_text = "60 วันทำการล่าสุด (~3 เดือน)"
        elif tf_option == "1W (รายสัปดาห์)": zoom_text = "60 สัปดาห์ล่าสุด (~1 ปี 2 เดือน)"
        else: zoom_text = "60 เดือนล่าสุด (5 ปี)"
        
        st.markdown(f"### 🔎 กราฟเจาะลึกแบบซูมระยะประชิด ({zoom_text})")
        df_zoom = df.tail(60)
        
        fig_zoom = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.04, row_heights=[0.6, 0.2, 0.2])
        fig_zoom.add_trace(go.Candlestick(x=df_zoom.index, open=df_zoom['Open'], high=df_zoom['High'], low=df_zoom['Low'], close=df_zoom['Close'], name="Price"), row=1, col=1)
        fig_zoom.add_trace(go.Scatter(x=df_zoom.index, y=df_zoom['E10'], line=dict(color='#00E676', width=1.5), name="EMA 10"), row=1, col=1)
        fig_zoom.add_trace(go.Scatter(x=df_zoom.index, y=df_zoom['E50'], line=dict(color='#FF6D00', width=2), name="EMA 50"), row=1, col=1)
        fig_zoom.add_trace(go.Scatter(x=df_zoom.index, y=df_zoom['E200'], line=dict(color='#E0E0E0', width=1.5, dash='dot'), name="EMA 200"), row=1, col=1)
        
        show_fibo = st.checkbox(f"📐 เปิดใช้ระบบตีเส้น Fibonacci Retracement ({zoom_text})", value=True)
        if show_fibo:
            max_p, min_p = df_zoom['High'].max(), df_zoom['Low'].min()
            diff = max_p - min_p
            f_levels = [(0.0, "0.0% (High)", "#FF5252"), (0.382, "38.2%", "#FFF176"), (0.5, "50.0%", "#E0E0E0"), (0.618, "61.8% (Golden Ratio)", "#00E676"), (1.0, "100.0% (Low)", "#FF5252")]
            for ratio, label, color in f_levels:
                fibo_y = max_p - (diff * ratio)
                fig_zoom.add_hline(y=fibo_y, line_dash="dot", line_color=color, annotation_text=f"{label} : ${fibo_y:.2f}", row=1, col=1, opacity=0.8)
                
        fig_zoom.add_trace(go.Bar(x=df_zoom.index, y=df_zoom['Hist'], marker_color=['#00E676' if v >= 0 else '#FF5252' for v in df_zoom['Hist']], name="MACD Hist"), row=2, col=1)
        fig_zoom.add_trace(go.Scatter(x=df_zoom.index, y=df_zoom['RSI'], line=dict(color='#FF9800', width=1.5), name="RSI"), row=3, col=1)
        fig_zoom.add_hline(y=70, line_dash="dot", line_color="#FF5252", row=3, col=1)
        fig_zoom.add_hline(y=30, line_dash="dot", line_color="#00E676", row=3, col=1)
        fig_zoom.update_layout(template="plotly_dark", height=650, margin=dict(l=0,r=0,t=20,b=0), showlegend=True)
        fig_zoom.update_xaxes(rangeslider_visible=False)
        st.plotly_chart(fig_zoom, use_container_width=True)

# ==========================================
# หน้า 3: เรดาร์สแกนหุ้น (AI Screener)
# ==========================================
with tabs[2]:
    st.markdown("## 🎯 เรดาร์สแกนหุ้น (AI Screener)")
    if st.button("🚀 สแกนและอัปเดตหุ้นในเรดาร์ทั้ง 20 ตัว", type="primary", use_container_width=True):
        screener_df = run_ai_screener(st.session_state.radar_tickers)
        st.dataframe(screener_df, use_container_width=True)

# ==========================================
# หน้า 4: บัญชีลงทุน (คืนชีพพอร์ตโฟลิโอ & กราฟครบครัน)
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
        st.subheader("📝 สมุดบัญชีเงินสด (Ledger Editor)")
        ed_l = st.data_editor(st.session_state.trade_ledger, num_rows="dynamic", use_container_width=True,
            column_config={
                "Date": "วันที่", "Action": st.column_config.SelectboxColumn("ประเภท", options=["นำเงินออกนอกประเทศ (Outward)", "นำเงินเข้าประเทศไทย (Inward)", "ซื้อหุ้น (Buy)", "ขายหุ้น (Sell)", "รับเงินปันผล (Dividend)"]),
                "Ticker": "ชื่อหุ้น", "Price": st.column_config.NumberColumn("ราคา ($)", format="%.4f"), "Shares": st.column_config.NumberColumn("จำนวนหุ้น", format="%.4f"),
                "Amount_USD": st.column_config.NumberColumn("จำนวนเงิน ($)", format="%.2f"), "Running_Balance": st.column_config.NumberColumn("เงินสดคงเหลือ ($)", disabled=True, format="%.2f")
            })
        if not ed_l.equals(st.session_state.trade_ledger):
            st.session_state.trade_ledger = calculate_stats(clean_df_types(ed_l))[0]
            st.rerun()
            
        if st.button("💾 บันทึกข้อมูลสมุดบัญชีขึ้นระบบ Cloud", type="primary", use_container_width=True):
            if save_df_to_sheet("Ledger", st.session_state.trade_ledger): st.success("✅ บันทึกข้อมูลสำเร็จ!")

        # --- [คืนชีพ 100%] แดชบอร์ดสรุปพอร์ตและกราฟวงกลม/กราฟแท่ง ---
        st.markdown("---")
        st.subheader("📊 ตารางสรุปพอร์ตโฟลิโอปัจจุบัน (Auto Mark-to-Market)")
        live_fx = get_live_fx()
        st.info(f"💱 **เรทอัตราแลกเปลี่ยน USD/THB ประจำวัน:** ฿{live_fx:.4f}")
        
        port_summary, total_invested = [], 0.0
        for t, data in holdings.items():
            if data["shares"] > 0.001:
                port_summary.append({"Ticker": t, "Cost_Price": data["total_cost"] / data["shares"], "Shares": data["shares"], "Total_Cost": data["total_cost"]})
                total_invested += data["total_cost"]
                
        if len(port_summary) > 0:
            current_port_df = pd.DataFrame(port_summary)
            results, total_v = [], 0.0
            batch_prices = get_batch_live_prices(current_port_df["Ticker"].tolist())
            for _, row in current_port_df.iterrows():
                t, avg_cost, sh, t_cost = row["Ticker"], row["Cost_Price"], row["Shares"], row["Total_Cost"]
                curr_p = batch_prices.get(t, avg_cost)
                val = curr_p * sh
                profit_usd = val - t_cost
                results.append({"หุ้น": t, "จำนวนหุ้น": sh, "ต้นทุนเฉลี่ย": avg_cost, "ราคาปัจจุบัน": curr_p, "กำไร/ขาดทุน ($)": profit_usd, "กำไร/ขาดทุน (฿)": profit_usd * live_fx, "% เปลี่ยนแปลง": (profit_usd / t_cost) * 100, "มูลค่ารวม": val})
                total_v += val
            
            p1, p2, p3, p4 = st.columns(4)
            p1.metric("มูลค่าหุ้นรวมทั้งหมด", f"${total_v:,.2f}")
            p2.metric("ต้นทุนหุ้นทั้งหมด", f"${total_invested:,.2f}")
            p3.metric("กำไร/ขาดทุนรวม ($)", f"${total_v - total_invested:,.2f}", f"{((total_v - total_invested) / total_invested * 100):.2f}%")
            p4.metric("กำไร/ขาดทุนรวม (฿)", f"฿{(total_v - total_invested) * live_fx:,.2f}")
            
            res_df = pd.DataFrame(results)
            ch_c1, ch_c2 = st.columns(2)
            with ch_c1:
                fig_pie = go.Figure(data=[go.Pie(labels=res_df['หุ้น'], values=res_df['มูลค่ารวม'], hole=.4)])
                fig_pie.update_layout(title="สัดส่วนมูลค่าพอร์ตการลงทุน", template="plotly_dark", height=300, margin=dict(t=40,b=0,l=0,r=0))
                st.plotly_chart(fig_pie, use_container_width=True)
            with ch_c2:
                fig_bar = go.Figure(data=[go.Bar(x=res_df['หุ้น'], y=res_df['กำไร/ขาดทุน ($)'], marker_color=['#00E676' if val >= 0 else '#FF5252' for val in res_df['กำไร/ขาดทุน ($)']])])
                fig_bar.update_layout(title="ผลกำไร/ขาดทุนแยกรายตัว ($)", template="plotly_dark", height=300, margin=dict(t=40,b=0,l=0,r=0))
                st.plotly_chart(fig_bar, use_container_width=True)
                
            def color_profit(val): return f'color: {"#FF5252" if val < 0 else "#00E676"}; font-weight: bold;'
            st.dataframe(res_df.style.map(color_profit, subset=["กำไร/ขาดทุน ($)", "กำไร/ขาดทุน (฿)", "% เปลี่ยนแปลง"]).format({"จำนวนหุ้น": "{:,.2f}", "ต้นทุนเฉลี่ย": "${:,.2f}", "ราคาปัจจุบัน": "${:,.2f}", "กำไร/ขาดทุน ($)": "${:,.2f}", "กำไร/ขาดทุน (฿)": "฿{:,.2f}", "% เปลี่ยนแปลง": "{:,.2f}%", "มูลค่ารวม": "${:,.2f}"}), use_container_width=True)
        else: st.info("💼 พอร์ตว่างเปล่า ยังไม่มีหุ้นถือครองในระบบค่ะ")

# ==========================================
# หน้า 5: ระบบภาษี (คืนชีพเครื่องประเมิน ภ.ง.ด. 90 ตัวเต็ม)
# ==========================================
    with tabs[4]:
        st.subheader("🧾 ระบบประเมินภาษีเงินได้บุคคลธรรมดา (ภ.ง.ด. 90)")
        st.info("💡 **เกณฑ์จัดเก็บแบบใหม่:** ระบบจะคำนวณหักจากเงินต้นสะสมก่อน เมื่อยอดนำกลับประเทศไทยเกินเงินต้นก้อนแรก ส่วนต่างกำไรจึงจะถูกนำมาประเมินภาษี")
        
        tax_idx = st.session_state.trade_ledger['Action'].isin(["นำเงินออกนอกประเทศ (Outward)", "นำเงินเข้าประเทศไทย (Inward)", "รับเงินปันผล (Dividend)"])
        tax_v = st.session_state.trade_ledger[tax_idx].copy()
        tax_v["Out_USD"] = np.where(tax_v["Action"] == "นำเงินออกนอกประเทศ (Outward)", tax_v["Amount_USD"], 0.0)
        tax_v["In_USD"] = np.where(tax_v["Action"].isin(["นำเงินเข้าประเทศไทย (Inward)", "รับเงินปันผล (Dividend)"]), tax_v["Amount_USD"], 0.0)
        tax_v["FX_Rate"] = pd.to_numeric(tax_v["FX_Rate"], errors='coerce').fillna(live_fx)
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
        st.data_editor(tax_v, use_container_width=True, column_order=["Date", "Action", "Out_USD", "In_USD", "FX_Rate", "Out_THB", "In_THB", "Balance_THB", "Taxable_Gain_THB"])
        
        st.markdown("---")
        c1, c2, c3 = st.columns(3)
        with c1: selected_year = st.selectbox("📅 เลือกปีภาษีที่ต้องการประเมิน", ["2567 (2024)", "2568 (2025)", "2569 (2026)", "2570 (2027)"]).split("(")[1][:4]
        with c2: is_resident = st.radio("ระยะเวลาพำนักในประเทศไทยปีนี้", ["เกิน 180 วัน (เข้าเกณฑ์เสียภาษี)", "ไม่ถึง 180 วัน (ได้รับยกเว้น)"])
        with c3: other_income = st.number_input("รายได้พึงประเมินอื่นๆ ในไทย (บาท/ปี)", min_value=0.0, value=500000.0)

        t_yr = tax_v[tax_v['Date'].str.endswith(selected_year)]
        net_tax_gain_yr = t_yr["Taxable_Gain_THB"].sum()
        sum_wht_thb_yr = (t_yr["WHT_USD"] * t_yr["FX_Rate"]).sum()

        cf1, cf2, cf3 = st.columns(3)
        cf1.metric("📤 ยอดโอนออกสะสมปีนี้", f"฿{t_yr['Out_THB'].sum():,.2f}")
        cf2.metric("📥 ยอดดึงกลับประเทศปีนี้", f"฿{t_yr['In_THB'].sum():,.2f}")
        cf3.metric("🚨 ส่วนต่างกำไรที่ต้องประเมินภาษี", f"฿{net_tax_gain_yr:,.2f}")

        with st.expander("📝 ตั้งค่าข้อมูลลดหย่อนภาษีส่วนตัว"):
            d1, d2 = st.columns(2)
            s_deduct = d1.checkbox("คู่สมรสไม่มีรายได้ (ลดหย่อน 60,000 บาท)")
            c_count = d2.number_input("จำนวนบุตร (คนละ 30,000 บาท)", min_value=0, step=1)
            
        t_deduct = 100000 + 60000 + (60000 if s_deduct else 0) + (c_count * 30000)
        
        if st.button(f"📊 คำนวณประมาณการภาษีประจำปี {selected_year}", type="primary", use_container_width=True):
            if "ไม่ถึง" in is_resident: st.success("🎉 ได้รับยกเว้นเนื่องจากอยู่อาศัยในไทยไม่ถึง 180 วันในปีภาษีนี้")
            elif net_tax_gain_yr <= 0: st.success("🎉 ไม่มีกำไรส่วนเกินที่ถูกดึงกลับประเทศเข้าเกณฑ์ต้องเสียภาษี")
            else:
                def calc_tax_brackets(n):
                    if n > 5000000: return (n-5000000)*0.35 + 1265000
                    if n > 2000000: return (n-2000000)*0.30 + 365000
                    if n > 1000000: return (n-1000000)*0.25 + 115000
                    if n > 750000: return (n-750000)*0.20 + 65000
                    if n > 500000: return (n-500000)*0.15 + 27500
                    if n > 300000: return (n-300000)*0.10 + 7500
                    if n > 150000: return (n-150000)*0.05
                    return 0
                total_net_income = max(0, (other_income + net_tax_gain_yr) - t_deduct)
                base_net_income = max(0, other_income - t_deduct)
                tax_raw = calc_tax_brackets(total_net_income) - calc_tax_brackets(base_net_income)
                
                st.subheader("📋 สรุปรายการภาษีพอร์ตต่างประเทศ")
                r1, r2 = st.columns(2)
                r1.metric("ภาษีที่คำนวณจากกำไรพอร์ต", f"฿{tax_raw:,.2f}")
                r2.metric("🚨 ยอดที่ต้องชำระเพิ่มจริงหลังหักเครดิต", f"฿{max(0, tax_raw - sum_wht_thb_yr):,.2f}")

# ==========================================
# หน้า 6: พิทบูลพยากรณ์ (คืนชีพกราฟจำลอง 100 เส้นทาง)
# ==========================================
    with tabs[5]:
        st.markdown(f"## 🔮 พิทบูลพยากรณ์ (AI Monte Carlo Simulation) : {ticker}")
        st.info("💡 ระบบจะดึงความผันผวนย้อนหลังมาทำการสุ่มโอกาสทางสถิติรูปแบบเส้นทางเดินราคา 100 รูปแบบในอนาคต")
        sim_days = st.slider("เลือกจำนวนวันพยากรณ์ล่วงหน้า (วันทำการ):", 5, 90, 30)
        
        if st.button("🎲 เริ่มการประมวลผลสุ่มจำลองมอนติคาร์โล", type="primary", use_container_width=True):
            sim_df, exp_p, up_b, low_b, last_price = run_monte_carlo(ticker, days_to_predict=sim_days)
            if sim_df is not None:
                c1, c2, c3 = st.columns(3)
                c1.metric("📉 กรณีเลวร้ายที่สุด (Lower 5%)", f"${low_b:.2f}")
                c2.metric("🎯 ราคาคาดหวังตามสถิติ (Expected)", f"${exp_p:.2f}")
                c3.metric("📈 กรณีมองโลกแง่ดีที่สุด (Upper 95%)", f"${up_b:.2f}")
                
                # --- [คืนชีพ 100%] ตัววาดเส้นกราฟจำลองข่ายใยแมงมุม 100 เส้นทาง ---
                fig_sim = go.Figure()
                for col in sim_df.columns:
                    fig_sim.add_trace(go.Scatter(x=sim_df.index, y=sim_df[col], mode='lines', line=dict(width=1, color='rgba(130, 177, 255, 0.1)'), showlegend=False))
                fig_sim.add_trace(go.Scatter(x=[0, sim_days-1], y=[last_price, exp_p], mode='lines+markers', name='Expected Path', line=dict(color='#00E676', width=3, dash='dash')))
                fig_sim.add_hline(y=up_b, line_dash="dot", line_color="#FFD600", annotation_text="Upper Bound")
                fig_sim.add_hline(y=low_b, line_dash="dot", line_color="#FF5252", annotation_text="Lower Bound")
                fig_sim.update_layout(title=f"โครงข่ายวิเคราะห์ทิศทางราคาอนาคตของ {ticker}", template="plotly_dark", height=400, xaxis_title="วันในอนาคต", yaxis_title="ราคา (USD)")
                st.plotly_chart(fig_sim, use_container_width=True)
            else: st.error("❌ ดึงข้อมูลประมวลผลจำลองไม่สำเร็จ")

# ==========================================
# หน้า 7: แผนการเทรด (ตารางระบบลบข้อมูลแท็บเล็ตลื่นนิ้ว)
# ==========================================
    with tabs[6]:
        st.markdown(f"## 📝 แผนการเทรด (Trading Plan) : {ticker}")
        curr_p = df['Close'].iloc[-1] if not df.empty else 10.0
        c_plan1, c_plan2 = st.columns(2)
        with c_plan1:
            st.markdown("#### 1️⃣ ตั้งค่าบริหารหน้าตักความเสี่ยง")
            plan_cap = st.number_input("เงินทุนหน้าตักรวม ($)", value=float(t_cap))
            plan_risk_pct = st.number_input("เปอร์เซ็นต์ความเสี่ยงต่อไม้ที่รับได้ (%)", value=float(r_pct))
            risk_budget = plan_cap * (plan_risk_pct / 100.0)
            st.write(f"💸 **จำนวนเงินสูงสุดที่ยอมตัดขาดทุนได้ในไม้นี้:** :red[${risk_budget:,.2f}]")
        with c_plan2:
            st.markdown("#### 2️⃣ ตั้งค่าราคาจุดปฏิบัติการ")
            plan_entry = st.number_input("🎯 ระบุราคาใจสั่งให้เข้าซื้อ ($)", value=float(curr_p))
            plan_sl = st.number_input("🛑 ระบุจุดตั้งตัดขาดทุน Stop Loss ($)", value=float(curr_p*0.9))
            plan_tp = st.number_input("🏆 ระบุจุดตั้งเป้าทำกำไร Take Profit ($)", value=float(curr_p*1.2))
            plan_note = st.text_input("📝 บันทึกช่วยจำเพิ่มเติม")

        if plan_entry > plan_sl:
            risk_per_share = plan_entry - plan_sl
            max_shares = math.floor(risk_budget / risk_per_share) if risk_per_share > 0 else 0
            position_value = max_shares * plan_entry
            rr_ratio = (plan_tp - plan_entry) / risk_per_share if risk_per_share > 0 else 0
            
            c_sum1, c_sum2, c_sum3 = st.columns(3)
            c_sum1.metric("🛒 โควตาหุ้นที่ควรซื้อ", f"{max_shares:,} หุ้น")
            c_sum2.metric("💳 รวมมูลค่าเงินที่ต้องใช้", f"${position_value:,.2f}")
            c_sum3.metric("⚖️ อัตราส่วน Risk/Reward", f"1 : {rr_ratio:.2f}")
            
            if st.button("💾 กดบันทึกแผนการเทรดนี้เก็บเข้าสมุดจำย้อนหลัง", type="primary", use_container_width=True):
                new_plan = pd.DataFrame([{"Date": current_date, "Ticker": ticker, "Entry": plan_entry, "Stop_Loss": plan_sl, "Take_Profit": plan_tp, "Risk_Budget": risk_budget, "Max_Shares": max_shares, "Note": plan_note}])
                st.session_state.trading_plans = pd.concat([st.session_state.trading_plans, new_plan], ignore_index=True)
                save_df_to_sheet("Trading_Plans", st.session_state.trading_plans)
                st.success("✅ บันทึกแผนเรียบร้อยแล้วค่ะ!")
                time.sleep(0.5)
                st.rerun()

        st.markdown("---")
        st.markdown("### 📚 สมุดประวัติแผนการเทรดที่บันทึกไว้ (Saved Plans Table)")
        display_df = st.session_state.trading_plans.copy()
        if not display_df.empty:
            display_df.insert(0, "Select_Delete", False)
            ed_plans = st.data_editor(display_df, use_container_width=True, column_config={"Select_Delete": st.column_config.CheckboxColumn("🗑️ เลือกเพื่อลบ", default=False)})
            if ed_plans["Select_Delete"].any():
                st.warning("⚠️ ติ๊กเลือกรายการลบแล้ว โปรดกดปุ่มยันยันสีแดงด้านล่างค่ะ")
                if st.button("🗑️ ยืนยันการลบแผนการเทรดที่เลือกออกจากฐานข้อมูล", type="primary", use_container_width=True):
                    st.session_state.trading_plans = ed_plans[~ed_plans["Select_Delete"]].drop(columns=["Select_Delete"])
                    save_df_to_sheet("Trading_Plans", st.session_state.trading_plans)
                    st.success("ลบแผนออกจากระบบสำเร็จ!")
                    time.sleep(0.5)
                    st.rerun()
        else: st.info("📝 ยังไม่มีแผนการเทรดถูกบันทึกไว้ค่ะ")

# ==========================================
# หน้า 8: ระบบแบคเทสกลยุทธ์ 3 ประสาน
# ==========================================
    with tabs[7]:
        st.markdown(f"## 🧪 ระบบทดสอบกลยุทธ์ย้อนหลัง 3 ประสาน (EMA + MACD + RSI)")
        st.info("💡 ระบบจะสแกนข้อมูลราคาย้อนหลังดิบ 3 ปีเต็มในอดีตแบบเป็นกลาง เพื่อพิสูจน์ความแม่นยำของหน้าเทรด")
        test_ticker = st.text_input("🧬 พิมพ์ชื่อหุ้นที่ต้องการทดสอบกลยุทธ์ (เช่น AMSC, NOW, TSLA):", value=ticker).upper().strip()
        
        if st.button("📊 เริ่มการคำนวณแบคเทสจำลองพอร์ตเดี๋ยวนี้", type="primary", use_container_width=True):
            init_backtest_db()
            with st.spinner("🚀 ระบบหลังบ้าน SQLite กำลังประมวลผลความแม่นยำทีละวันทำการ..."):
                trades_df, final_value = run_3_prasan_backtest(test_ticker, period_years=3)
                if not trades_df.empty:
                    win_trades = trades_df[trades_df['p_l_usd'] > 0]
                    win_rate = (len(win_trades) / len(trades_df)) * 100
                    total_ret = ((final_value - 10000.0) / 10000.0) * 100
                    
                    conn = sqlite3.connect("backtest_history.db")
                    trades_df.to_sql("backtest_trades", conn, if_exists="append", index=False)
                    conn.close()
                    
                    c_bt1, c_bt2, c_bt3 = st.columns(3)
                    c_bt1.metric("🎯 อัตราการชนะ (Win Rate)", f"{win_rate:.2f}%")
                    c_bt2.metric("📈 ผลตอบแทนสะสมโมเดล (3 ปี)", f"{total_ret:+.2f}%")
                    c_bt3.metric("📋 จำนวนไม้ที่สแกนเจอตามกฎ", f"{len(trades_df)} ไม้")
                    
                    st.markdown("### 📋 ตารางบันทึกรายงานผลคำสั่งซื้อขายในอดีต")
                    display_bt = trades_df.rename(columns={
                        "entry_date": "วันที่เข้าซื้อ", "entry_price": "ราคาซื้อ ($)",
                        "exit_date": "วันที่ขายปิดไม้", "exit_price": "ราคาขาย ($)",
                        "p_l_pct": "เปอร์เซ็นต์ กำไร/ขาดทุน", "exit_reason": "สัญญาณที่ระบบสั่งขาย"
                    })
                    st.dataframe(display_bt[["วันที่เข้าซื้อ", "ราคาซื้อ ($)", "วันที่ขายปิดไม้", "ราคาขาย ($)", "เปอร์เซ็นต์ กำไร/ขาดทุน", "สัญญาณที่ระบบสั่งขาย"]], use_container_width=True)
                else: st.error("⚠️ ไม่พบจังหวะสัญญาณที่เข้าเกณฑ์กฎ 3 ประสานในช่วง 3 ปีที่ผ่านมาสำหรับหุ้นตัวนี้ค่ะ")

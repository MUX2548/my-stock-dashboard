import json
import time
import os
import math
import sqlite3
import urllib.parse
import random
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
    st.set_page_config(page_title="Strategic Hub 5.15", page_icon=browser_icon, layout="wide")
else:
    st.set_page_config(page_title="Strategic Hub 5.15", page_icon="📈", layout="wide")

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
# 🔐 2. การบริหารสถานะข้อมูลระบบ
# ==========================================
if "current_ticker" not in st.session_state: st.session_state.current_ticker = "RKLB"
if "logged_in" not in st.session_state: st.session_state["logged_in"] = False
if "radar_tickers" not in st.session_state: st.session_state.radar_tickers = ["ASTS", "RKLB", "TSLA"]

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
    st.error(f"❌ ไม่สามารถเชื่อมต่อฐานข้อมูล Google Sheets ได้: {e}")
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
    req_cols = ["Date", "Action", "Ticker", "Price", "Shares", "Amount_USD", "Running_Balance", "FX_Rate", "WHT_USD", "Ref_Doc"]
    try:
        ws = sh.worksheet("Ledger")
        records = ws.get_all_records()
        if not records: 
            return clean_df_types(pd.DataFrame(columns=req_cols))
        df = pd.DataFrame(records).replace(["", "None", "nan"], np.nan).fillna(np.nan).dropna(how="all")
    except Exception as e: 
        df = pd.DataFrame(columns=req_cols)
        
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
    except Exception: pass
    return pd.DataFrame(columns=req_cols)

def save_df_to_sheet(worksheet_name, df):
    global sh
    try: ws = sh.worksheet(worksheet_name)
    except Exception:
        try:
            sh = init_connection()
            ws = sh.worksheet(worksheet_name)
        except Exception: 
            ws = sh.add_worksheet(title=worksheet_name, rows="1000", cols="15")
    try:
        ws.clear()
        clean_df = df.copy().astype(str).replace(["nan", "None", "<NA>", "NaN"], "")
        ws.update(values=[clean_df.columns.values.tolist()] + clean_df.values.tolist(), range_name='A1')
        return True
    except Exception as e: 
        st.error(f"❌ บันทึกข้อมูลไม่สำเร็จ: {e}")
        return False

# ==========================================
# 🧪 3. ส่วนระบบจำลองกลยุทธ์ (Backtest Engine)
# ==========================================
def init_backtest_db():
    conn = sqlite3.connect("backtest_history.db")
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS backtest_trades (trade_id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, entry_date TEXT, entry_price REAL, exit_date TEXT, exit_price REAL, p_l_usd REAL, p_l_pct REAL, exit_reason TEXT)")
    conn.commit()
    conn.close()

def run_3_prasan_backtest(ticker_symbol, period_years=3, initial_capital=10000.0):
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=period_years*365)
    try:
        df_hist = yf.Ticker(ticker_symbol).history(start=start_dt, end=end_dt, interval="1d")
        if df_hist.empty: return pd.DataFrame(), initial_capital
    except Exception: return pd.DataFrame(), initial_capital

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
    cb, stat = 0.0, {"outward": 0.0, "inward": 0.0, "bought": 0.0, "sold": 0.0, "dividend": 0.0, "realized_profit": 0.0}
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
    except Exception: return short_text + "..."

def get_random_headers():
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0"
    ]
    return {"User-Agent": random.choice(user_agents), "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.5"}

@st.cache_data(ttl=900)
def load_pro_data(ticker_symbol, tf):
    stgs = {"1D (รายวัน)": {"p": "6mo", "i": "1d"}, "1W (รายสัปดาห์)": {"p": "2y", "i": "1wk"}, "1M (รายเดือน)": {"p": "5y", "i": "1mo"}}
    p, i = stgs[tf]["p"], stgs[tf]["i"]
    session = requests.Session()
    session.headers.update(get_random_headers())
    
    df = pd.DataFrame()
    for attempt in range(3):
        try:
            s = yf.Ticker(ticker_symbol, session=session)
            df = s.history(period=p, interval=i)
            if df.empty: df = yf.download(ticker_symbol, period=p, interval=i, progress=False)
            if not df.empty:
                df = df.dropna(subset=['Close'])
                if not df.empty: break
        except Exception: pass
        time.sleep(1)
        
    if df.empty: return pd.DataFrame(), {}, None, None, {}
    
    fund = {
        "ps": "N/A", "pe": "N/A", "roe": "N/A", "rev_growth": "N/A", "dividend": "ไม่มีข้อมูล",
        "earnings_date": "รอประกาศ", "business_desc_th": "ข้อมูลถูกจำกัดจาก Yahoo ชั่วคราว (ระบบกราฟยังทำงานปกติค่ะ)",
        "industry": "N/A", "sector": "N/A", "location": "N/A", "website": "#", "pe_val": 0, "roe_val": 0
    }
    
    try:
        info = s.info
        if 'longBusinessSummary' in info:
            fund["business_desc_th"] = translate_to_thai(info.get('longBusinessSummary', 'N/A'))
        div_y = info.get('dividendYield', 0)
        earnings_date = "N/A"
        if 'earningsTimestamp' in info and info['earningsTimestamp']:
            earnings_date = datetime.fromtimestamp(info['earningsTimestamp'], tz=timezone.utc).strftime("%d/%m/%Y")
            
        fund.update({
            "ps": f"{float(info.get('priceToSalesTrailing12Months', 0) or 0):.2f}", 
            "pe": f"{float(info.get('trailingPE', 0) or 0):.2f}", 
            "roe": f"{float(info.get('returnOnEquity', 0) or 0)*100:.2f}%",
            "rev_growth": f"{float(info.get('revenueGrowth', 0) or 0)*100:.2f}%",
            "dividend": f"{(float(div_y) * 100):.2f}%" if div_y else "ไม่มีปันผล",
            "earnings_date": earnings_date if earnings_date != "N/A" else "รอประกาศ",
            "industry": info.get('industry', 'N/A'), "sector": info.get('sector', 'N/A'),
            "location": info.get('country', 'N/A'), "website": info.get('website', '#'),
            "pe_val": float(info.get('trailingPE', 0) or 0), "roe_val": float(info.get('returnOnEquity', 0) or 0)
        })
    except Exception: pass 

    market_signal = {"spy_trend": "N/A", "spy_price": 0.0, "vix": 0.0, "vix_ts": 0.0, "smart_money": "N/A"}
    try:
        spy = yf.Ticker("^GSPC", session=session).history(period=p, interval=i)
        if not spy.empty:
            df['RS'] = (df['Close'].pct_change(10) - spy['Close'].pct_change(10)) * 100
            spy_p = spy['Close'].iloc[-1]
            market_signal["spy_price"] = float(spy_p)
            market_signal["spy_trend"] = "ขึ้น 📈" if spy_p > spy['Close'].ewm(span=50).mean().iloc[-1] else "ลง 📉"
    except Exception: df['RS'] = 0
    try:
        vix = yf.Ticker("^VIX", session=session).history(period="1mo")
        if not vix.empty: market_signal["vix"] = float(vix['Close'].iloc[-1])
        vix3m = yf.Ticker("^VIX3M", session=session).history(period="1mo")
        if not vix3m.empty and market_signal["vix"] > 0: market_signal["vix_ts"] = float(market_signal["vix"] / vix3m['Close'].iloc[-1])
    except Exception: pass
    try:
        hyg = yf.Ticker("HYG", session=session).history(period="6mo")['Close']
        ief = yf.Ticker("IEF", session=session).history(period="6mo")['Close']
        if not hyg.empty and not ief.empty:
            market_signal["smart_money"] = "Risk ON 🟢" if (hyg/ief).iloc[-1] > (hyg/ief).ewm(span=20).mean().iloc[-1] else "Risk OFF 🔴"
    except Exception: pass
    
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
    
    last = df['Close'].iloc[-1]
    v = df['Close'].pct_change().tail(14).std()
    tr = "ขึ้น 📈" if last > df['E50'].iloc[-1] else "ลง 📉"
    mat = {"l": last * (1 - v*0.5), "u": last * (1 + v*1.0), "tr": tr}
    atr = df['High'].tail(14).max() - df['Low'].tail(14).min()
    levels = {"r1": last + (atr * 0.5), "r2": last + (atr * 1.0), "r3": last + (atr * 1.5), "r4": last + (atr * 2.0), "s1": last - (atr * 0.5), "s2": last - (atr * 1.0), "s3": last - (atr * 1.5)}
    
    return df, fund, mat, market_signal, levels

@st.cache_data(ttl=300)
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
            if not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    prices[tickers[0]] = float(df['Close'][tickers[0]].iloc[-1])
                elif 'Close' in df.columns:
                    prices[tickers[0]] = float(df['Close'].iloc[-1])
        elif 'Close' in df.columns:
            for t in tickers:
                if isinstance(df.columns, pd.MultiIndex):
                    if t in df['Close'].columns and pd.notna(df['Close'][t].iloc[-1]): prices[t] = float(df['Close'][t].iloc[-1])
                else:
                    if t in df.columns and pd.notna(df['Close'].iloc[-1]): prices[t] = float(df['Close'].iloc[-1])
        return prices
    except Exception: return {}

@st.cache_data(ttl=60)
def get_live_fx():
    try: return yf.Ticker("USDTHB=X").history(period="1d")['Close'].iloc[-1]
    except Exception: return 35.00

@st.cache_data(ttl=1800)
def run_ai_screener(tickers):
    if not tickers: return pd.DataFrame()
    results = []
    session = requests.Session()
    session.headers.update(get_random_headers())
    for t in tickers:
        try:
            hist = yf.Ticker(t, session=session).history(period="6mo")
            if hist.empty: 
                hist = yf.download(t, period="6mo", progress=False)
            if hist.empty or 'Close' not in hist.columns: continue
            
            if isinstance(hist.columns, pd.MultiIndex): close_series = hist['Close'][t]
            else: close_series = hist['Close']
            close_series = close_series.dropna()
            if len(close_series) < 50: continue

            close = float(close_series.iloc[-1])
            ema50 = float(close_series.ewm(span=50).mean().iloc[-1])
            delta = close_series.diff()
            gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14).mean()
            loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14).mean()
            rsi_val = float((100 - (100 / (1 + gain/loss))).iloc[-1])
            
            macd = close_series.ewm(span=12).mean() - close_series.ewm(span=26).mean()
            sig = macd.ewm(span=9).mean()
            macd_val = float(macd.iloc[-1])
            sig_val = float(sig.iloc[-1])
            
            action = "⏳ WAIT (รอดูทรง)"
            if close > ema50 and macd_val > sig_val and rsi_val < 65: action = "⭐ STRONG BUY"
            elif close < ema50 and macd_val > sig_val and rsi_val < 35: action = "⚡ SPECULATE"
            elif close > ema50 and rsi_val >= 70: action = "🔥 OVERBOUGHT"
            
            results.append({"หุ้น": t, "ราคาล่าสุด": f"${close:.2f}", "EMA50": f"${ema50:.2f}", "RSI": f"{rsi_val:.1f}", "คำแนะนำ AI": action})
        except Exception: pass
        time.sleep(1.5) 
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
    except Exception: return None, 0, 0, 0, 0

# ==========================================
# 🎛️ 5. UI Layout: แถบเมนูด้านซ้าย (Sidebar)
# ==========================================
with st.sidebar:
    if os.path.exists(logo_path): st.image(logo_path, use_container_width=True)
    else: st.title("🛡️ Strategic Hub 5.15")
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

with st.spinner("⏳ กำลังประมวลผลดึงข้อมูลสดจากตลาด..."):
    df, fund, matrix, market_signal, levels = load_pro_data(ticker, tf_option)

if not df.empty:
    spy_t = market_signal.get("spy_trend", "N/A")
    spy_p = market_signal.get("spy_price", 0.0)
    v_val = market_signal.get("vix", 0.0)
    vix_ts = market_signal.get("vix_ts", 0.0)
    sm_flow = market_signal.get("smart_money", "N/A")
    is_market_good = "ขึ้น" in spy_t and (0 < v_val < 25)

tabs_list = ["📊 วิเคราะห์รายตัว", "🔬 หาจุดเข้าซื้อ (Technical)", "🎯 เรดาร์สแกนหุ้น"]
if st.session_state["logged_in"]: 
    tabs_list.extend(["💼 บัญชีลงทุน", "🧾 ระบบภาษี", "🔮 พิทบูลพยากรณ์", "📝 แผนการเทรด", "🧪 แบคเทส 3 ประสาน"])
tabs = st.tabs(tabs_list)

# ==========================================
# หน้า 1: วิเคราะห์กราฟรายตัว
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
        m_c2.metric("📊 การเปลี่ยนแปลงจากราคาปิดวันก่อนหน้า (Daily Change)", f"{'+' if daily_diff >= 0 else ''}{daily_diff:,.2f} USD", delta=f"{daily_pct:+.2f}%")
        
        with st.expander("🏢 ข้อมูลธุรกิจ (Company Profile)", expanded=False):
            st.markdown(f"**🇹🇭 สรุปธุรกิจ:**")
            if "จำกัด" in fund.get('business_desc_th', ''): st.warning(fund.get('business_desc_th', ''))
            else: st.info(fund.get('business_desc_th', 'ไม่มีข้อมูล'))
            c_b1, c_b2, c_b3 = st.columns(3)
            c_b1.markdown(f"**🏷️ กลุ่ม:** {fund.get('industry', 'N/A')}")
            c_b2.markdown(f"**📍 ที่ตั้ง:** {fund.get('location', 'N/A')}")
            website = fund.get('website', '#')
            if website != '#': c_b3.markdown(f"**🌐 เว็บไซต์:** <a href='{website}' target='_blank'>คลิกดูเว็บไซต์</a>", unsafe_allow_html=True)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("ตลาดโลก (S&P 500)", f"{spy_p:,.2f}" if spy_p > 0 else "N/A", spy_t if spy_p > 0 else None, delta_color="normal" if "ขึ้น" in spy_t else "inverse" if "ลง" in spy_t else "off")
        vix_stat = "Risk ON" if 0 < v_val < 20 else "Neutral" if 0 < v_val < 30 else "Panic"
        m2.metric("ความกลัว (VIX)", f"{v_val:.2f}" if v_val > 0 else "N/A", vix_stat if v_val > 0 else None, delta_color="normal" if 0 < v_val < 25 else "inverse" if v_val >= 25 else "off")
        ts_label = "🟢 สงบ" if 0 < vix_ts < 1 else "🔴 ตระหนก" if vix_ts > 0 else "N/A"
        m3.metric("โครงสร้าง (VIX/VIX3M)", f"{vix_ts:.2f}" if vix_ts > 0 else "N/A", ts_label if vix_ts > 0 else None, delta_color="normal" if 0 < vix_ts < 1 else "inverse" if vix_ts >= 1 else "off")
        m4.metric("เงินใหญ่ (HYG/IEF)", "Credit Flow", sm_flow if sm_flow != "N/A" else None, delta_color="normal" if "ON" in sm_flow else "inverse" if "OFF" in sm_flow else "off")
        
        if is_market_good and is_uptrend and is_bullish_macd and rsi_val < 70:
            rec, color, msg = "STRONG BUY / HOLD", "#00E676", "ตลาดเอื้ออำนวย หุ้นเป็นขาขึ้นเต็มตัว โมเมนตัมบวก แนะนำให้สะสมหรือรันเทรนด์ต่อ"
        elif is_uptrend and rsi_val >= 70:
            rec, color, msg = "HOLD / TAKE PROFIT", "#FFD600", "หุ้นเป็นขาขึ้นแต่เข้าเขตซื้อมากเกินไป ไม่ควรไล่ราคา แนะนำรันเทรนด์แบบยก Stop Loss ตาม"
        elif not is_uptrend and is_bullish_macd and rsi_val < 35:
            rec, color, msg = "SPECULATIVE BUY", "#2962FF", "หุ้นเสียทรงขาขึ้นแต่เริ่มมีแรงซื้อกลับ เหมาะเก็งกำไรระยะสั้น (ต้องมีจุดตัดขาดทุนชัดเจน)"
        elif not is_uptrend:
            rec, color, msg = "AVOID / WAIT", "#FF5252", "ภาพรวมเป็นขาลง โมเมนตัมอ่อนแอ แนะนำให้รอดูสถานการณ์ไปก่อน"
        else:
            rec, color, msg = "NEUTRAL / SIDEWAY", "#B0BEC5", "กราฟแกว่งตัว สัญญาณขัดแย้งกัน แนะนำเทรดในกรอบสั้นๆ หรือรอจนกว่าจะชัดเจน"

        st.markdown(f'<div class="pro-box" style="border-left: 8px solid {color}; padding: 20px; border-radius: 8px; margin: 15px 0;"><h4 style="color: {color}; margin-top: 0;">🤵 ทัศนะเทรดเดอร์: {rec}</h4><p style="color: #E0E0E0; margin-bottom: 0;">{msg}</p></div>', unsafe_allow_html=True)
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
            if pe_v == "N/A" or pe_v <= 0: pe_status = "🔴 ขาดทุน/N/A"
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
            if isinstance(pe_v, (int, float)) and (pe_v <= 0) or (isinstance(fund.get('roe_val'), (int, float)) and fund.get('roe_val', 0) < 0): 
                st.error("⚠️ หุ้นเก็งกำไรความเสี่ยงสูง (ขาดทุน หรือ ROE ติดลบ) ระบบจะปรับลดงบเข้าซื้ออัตโนมัติ")
        
        with c_r:
            if levels:
                st.markdown(f"""
                <div class="pro-box" style="border-top: 3px solid #FF5252;"><div class="pro-title c-red">แนวต้าน (RESISTANCE)</div>
                <div class="pro-row"><span>ด่านแรก</span> <span>${levels['r1']:.2f}</span></div><div class="pro-row"><span>ด่านจริง</span> <span>${levels['r2']:.2f}</span></div>
                <div class="pro-row"><span>ด่านถัดไป</span> <span>${levels['r3']:.2f}</span></div><div class="pro-row"><span>เป้าหมายถัดไป</span> <span>${levels['r4']:.2f}</span></div></div>
                <div class="pro-box" style="border-top: 3px solid #00E676;"><div class="pro-title c-green">แนวรับ (SUPPORT)</div>
                <div class="pro-row"><span>แนวรับแรก</span> <span>${levels['s1']:.2f}</span></div><div class="pro-row"><span>แนวรับลึก</span> <span>${levels['s2']:.2f}</span></div>
                <div class="pro-row"><span>แนวรับถัดไป</span> <span>${levels['s3']:.2f}</span></div></div>
                """, unsafe_allow_html=True)
            
            if is_uptrend and is_bullish_macd:
                p_main, summary, not_to_do, t_flow = "ย่อ = ซื้อเพิ่ม / ถือรันเทรนด์", "🟢 'เกมลุย'", "❌ ห้ามสวนเทรนด์ (Short

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
    st.set_page_config(page_title="Strategic Hub 6.70", page_icon=browser_icon, layout="wide")
else:
    st.set_page_config(page_title="Strategic Hub 6.70", page_icon="📈", layout="wide")

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
    .val-box { background-color: #0d1b2a; border-left: 5px solid #00B4D8; padding: 15px; border-radius: 8px; margin-bottom: 15px; }
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
if "sandbox_tickers" not in st.session_state: st.session_state.sandbox_tickers = ["NVDA", "JPM", "LLY", "LMT", "WMT"]

@st.cache_resource(ttl=3600)
def init_connection():
    creds_dict = json.loads(st.secrets["google_creds_json"])
    sheet_url = st.secrets["spreadsheet_url"]
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc = gspread.authorize(credentials)
    return gc.open_by_url(sheet_url)

try: sh = init_connection()
except: st.stop()

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
    if not df.empty and "Date" in df.columns: df["Date"] = pd.to_datetime(df["Date"], format="%d/%m/%Y", errors="coerce").dt.strftime("%d/%m/%Y").replace("NaT", "")
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

def load_sandbox_data():
    req_cols = ["Date", "Portfolio_Name", "Tickers", "Weights", "Sim_Return", "Alpha", "Note"]
    try:
        ws = sh.worksheet("Sandbox_History")
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
        except: ws = sh.add_worksheet(title=worksheet_name, rows="1000", cols="15")
    try:
        ws.clear()
        clean_df = df.copy().astype(str).replace(["nan", "None", "<NA>", "NaN"], "")
        ws.update(values=[clean_df.columns.values.tolist()] + clean_df.values.tolist(), range_name='A1')
        return True
    except: return False

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
if "sandbox_history" not in st.session_state: st.session_state.sandbox_history = load_sandbox_data()

def log_visitor():
    try:
        ws = sh.worksheet("Visitor_Log")
        if "has_logged_visit" not in st.session_state:
            ws.append_row([datetime.now(tz_th).strftime("%d/%m/%Y %H:%M:%S")])
            st.session_state.has_logged_visit = True
        return len(ws.col_values(1))
    except: return "N/A"
visitor_count = log_visitor()

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
    except: return short_text + "..."

@st.cache_data(ttl=900)
def load_pro_data(ticker_symbol, tf):
    stgs = {"1D (รายวัน)": {"p": "6mo", "i": "1d"}, "1W (รายสัปดาห์)": {"p": "2y", "i": "1wk"}, "1M (รายเดือน)": {"p": "5y", "i": "1mo"}}
    p, i = stgs[tf]["p"], stgs[tf]["i"]
    
    df = pd.DataFrame()
    s = yf.Ticker(ticker_symbol)
    for attempt in range(3):
        try:
            df = s.history(period=p, interval=i)
            if df.empty: 
                df = yf.download(ticker_symbol, period=p, interval=i, progress=False)
            if not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df = df.xs(ticker_symbol, level=1, axis=1)
                df = df.dropna(subset=['Close'])
                if not df.empty: break
        except: pass
        time.sleep(1)
        
    if df.empty: return pd.DataFrame(), {}, None, None, {}
    
    fund = {
        "ps": "N/A", "pe": "N/A", "roe": "N/A", "rev_growth": "N/A", "dividend": "ไม่มีข้อมูล",
        "earnings_date": "รอประกาศ", "business_desc_th": "ข้อมูลถูกจำกัดชั่วคราว",
        "industry": "N/A", "sector": "N/A", "location": "N/A", "website": "#", "pe_val": 0, "roe_val": 0,
        "fair_price": "N/A", "valuation_status": "ไม่มีข้อมูล", "eps": 0, "bv": 0
    }
    
    info = {}
    try:
        info = s.info
    except: pass

    try:
        real_time_price = info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose')
        if real_time_price and pd.notna(real_time_price) and real_time_price > 0:
            if abs(df['Close'].iloc[-1] - real_time_price) > 0.01:
                market_time = info.get('regularMarketTime')
                if market_time:
                    latest_date = datetime.fromtimestamp(market_time, tz=timezone.utc).astimezone(tz_th).date()
                else:
                    latest_date = datetime.now(tz_th).date()
                
                last_df_date = df.index[-1].date() if hasattr(df.index[-1], 'date') else df.index[-1]
                
                if latest_date > last_df_date:
                    try:
                        new_idx = pd.to_datetime(latest_date)
                        if df.index.tz is not None:
                            new_idx = new_idx.tz_localize(df.index.tz)
                        new_row = pd.DataFrame({
                            'Open': [real_time_price], 'High': [real_time_price], 
                            'Low': [real_time_price], 'Close': [real_time_price], 
                            'Volume': [0]
                        }, index=[new_idx])
                        df = pd.concat([df, new_row])
                    except:
                        df.iloc[-1, df.columns.get_loc('Close')] = real_time_price
                else:
                    df.iloc[-1, df.columns.get_loc('Close')] = real_time_price
    except: pass

    last_price = df['Close'].iloc[-1]

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
    
    df['TR'] = np.maximum(df['High'] - df['Low'], np.maximum(abs(df['High'] - df['Close'].shift(1)), abs(df['Low'] - df['Close'].shift(1))))
    df['ATR'] = df['TR'].rolling(window=14).mean()
    atr_value = df['ATR'].iloc[-1] if not pd.isna(df['ATR'].iloc[-1]) else (df['High'].tail(14).max() - df['Low'].tail(14).min()) / 14

    v = df['Close'].pct_change().tail(14).std()
    tr = "ขึ้น 📈" if last_price > df['E50'].iloc[-1] else "ลง 📉"
    mat = {"l": last_price * (1 - v*0.5), "u": last_price * (1 + v*1.0), "tr": tr, "atr": atr_value}
    
    atr_v = atr_value * 2
    levels = {"r1": last_price + (atr_v * 0.5), "r2": last_price + (atr_v * 1.0), "r3": last_price + (atr_v * 1.5), "r4": last_price + (atr_v * 2.0), "s1": last_price - (atr_v * 0.5), "s2": last_price - (atr_v * 1.0), "s3": last_price - (atr_v * 1.5)}

    try:
        if 'longBusinessSummary' in info: fund["business_desc_th"] = translate_to_thai(info.get('longBusinessSummary', 'N/A'))
        
        div_y = info.get('dividendYield', 0)
        if div_y and float(div_y) > 1.0: 
            div_y = float(div_y) / 100.0 
            
        earnings_date = "N/A"
        if 'earningsTimestamp' in info and info['earningsTimestamp']:
            earnings_date = datetime.fromtimestamp(info['earningsTimestamp'], tz=timezone.utc).strftime("%d/%m/%Y")
            
        eps = info.get('trailingEps', 0)
        bv = info.get('bookValue', 0)
        ps_ratio = info.get('priceToSalesTrailing12Months', 0)
        
        fair_p_str = "N/A (บริษัทขาดทุน)"
        val_status = "ประเมินไม่ได้"
        
        if eps is not None and bv is not None and eps > 0 and bv > 0:
            graham_num = math.sqrt(22.5 * eps * bv)
            fair_p_str = f"${graham_num:.2f}"
            margin = ((graham_num - last_price) / graham_num) * 100 if graham_num > 0 else 0
            if last_price > graham_num * 1.3: 
                val_status = f"🔴 แพงเกินจริง (Premium {-margin:.1f}%)"
            elif last_price < graham_num * 0.8: 
                val_status = f"🟢 ถูกกว่ามูลค่าจริง (Discount {margin:.1f}%)"
            else: 
                val_status = f"🟡 ราคาเหมาะสม (Margin {margin:+.1f}%)"
        else:
            if ps_ratio is not None and ps_ratio > 0:
                if ps_ratio > 20: val_status = "🔴 แพงระดับฟองสบู่ (Extreme Bubble)"
                elif ps_ratio > 10: val_status = "🟠 ค่อนข้างแพง (Overvalued Growth)"
                elif ps_ratio < 3: val_status = "🟢 ราคาถูก (Discount)"
                else: val_status = "🟡 กลางๆ (Neutral)"

        fund.update({
            "ps": f"{float(ps_ratio or 0):.2f}", 
            "pe": f"{float(info.get('trailingPE', 0) or 0):.2f}", 
            "roe": f"{float(info.get('returnOnEquity', 0) or 0)*100:.2f}%",
            "rev_growth": f"{float(info.get('revenueGrowth', 0) or 0)*100:.2f}%",
            "dividend": f"{(float(div_y) * 100):.2f}%" if div_y else "ไม่มีปันผล",
            "earnings_date": earnings_date if earnings_date != "N/A" else "รอประกาศ",
            "industry": info.get('industry', 'N/A'), "sector": info.get('sector', 'N/A'),
            "location": info.get('country', 'N/A'), "website": info.get('website', '#'),
            "pe_val": float(info.get('trailingPE', 0) or 0), "roe_val": float(info.get('returnOnEquity', 0) or 0),
            "fair_price": fair_p_str, "valuation_status": val_status, "eps": eps, "bv": bv
        })
    except: pass 

    market_signal = {"spy_trend": "N/A", "spy_price": 0.0, "vix": 0.0, "vix_ts": 0.0, "smart_money": "N/A"}
    try:
        spy = yf.Ticker("SPY").history(period=p, interval=i)
        if not spy.empty and 'Close' in spy.columns:
            if isinstance(spy.columns, pd.MultiIndex): spy = spy.xs("SPY", level=1, axis=1)
            spy_clean = spy['Close'].dropna()
            if len(spy_clean) > 10:
                df['RS'] = (df['Close'].pct_change(10) - spy_clean.pct_change(10)) * 100
                spy_p = float(spy_clean.iloc[-1])
                if not math.isnan(spy_p) and spy_p > 0:
                    market_signal["spy_price"] = spy_p
                    market_signal["spy_trend"] = "ขึ้น 📈" if spy_p > spy_clean.ewm(span=50).mean().iloc[-1] else "ลง 📉"
    except: df['RS'] = 0
    try:
        vix = yf.Ticker("^VIX").history(period="1mo")
        if not vix.empty: 
            if isinstance(vix.columns, pd.MultiIndex): vix = vix.xs("^VIX", level=1, axis=1)
            market_signal["vix"] = float(vix['Close'].iloc[-1])
        vix3m = yf.Ticker("^VIX3M").history(period="1mo")
        if not vix3m.empty and market_signal["vix"] > 0: 
            if isinstance(vix3m.columns, pd.MultiIndex): vix3m = vix3m.xs("^VIX3M", level=1, axis=1)
            market_signal["vix_ts"] = float(market_signal["vix"] / vix3m['Close'].iloc[-1])
    except: pass
    try:
        hyg = yf.Ticker("HYG").history(period="6mo")['Close']
        ief = yf.Ticker("IEF").history(period="6mo")['Close']
        if not hyg.empty and not ief.empty:
            market_signal["smart_money"] = "Risk ON 🟢" if (hyg/ief).iloc[-1] > (hyg/ief).ewm(span=20).mean().iloc[-1] else "Risk OFF 🔴"
    except: pass
    
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
            if not df.empty and 'Close' in df.columns: prices[tickers[0]] = float(df['Close'].iloc[-1])
        elif 'Close' in df.columns:
            for t in tickers:
                if t in df['Close'].columns and pd.notna(df['Close'][t].iloc[-1]): prices[t] = float(df['Close'][t].iloc[-1])
        return prices
    except: return {}

@st.cache_data(ttl=3600)
def get_market_benchmark():
    for ticker in ["SPY", "VOO", "^GSPC"]: 
        try:
            spy = yf.Ticker(ticker).history(period="1y")
            if not spy.empty and 'Close' in spy.columns:
                spy_clean = spy['Close'].dropna()
                if len(spy_clean) > 10:
                    start_p = float(spy_clean.iloc[0])
                    end_p = float(spy_clean.iloc[-1])
                    if start_p > 0 and not math.isnan(start_p) and not math.isnan(end_p):
                        ret = ((end_p - start_p) / start_p) * 100
                        if not math.isnan(ret): return ret
        except: pass
    return 15.50 

@st.cache_data(ttl=60)
def get_live_fx():
    try: return yf.Ticker("USDTHB=X").history(period="1d")['Close'].iloc[-1]
    except: return 35.00

@st.cache_data(ttl=1800)
def run_ai_screener(tickers, tf_option):
    if not tickers: return pd.DataFrame()
    stgs = {"1D (รายวัน)": {"p": "6mo", "i": "1d"}, "1W (รายสัปดาห์)": {"p": "2y", "i": "1wk"}, "1M (รายเดือน)": {"p": "5y", "i": "1mo"}}
    p, i = stgs.get(tf_option, {"p": "6mo", "i": "1d"})["p"], stgs.get(tf_option, {"p": "6mo", "i": "1d"})["i"]
    
    results = []
    for t in tickers:
        try:
            s = yf.Ticker(t)
            hist = s.history(period=p, interval=i)
            if hist.empty: 
                hist = yf.download(t, period=p, interval=i, progress=False)
            if hist.empty or 'Close' not in hist.columns: continue
            
            if isinstance(hist.columns, pd.MultiIndex): close_series = hist['Close'][t]
            else: close_series = hist['Close']
            close_series = close_series.dropna()
            if len(close_series) < 50: continue

            info = {}
            try: info = s.info
            except: pass
            
            real_time_price = info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose')
            if real_time_price and pd.notna(real_time_price) and real_time_price > 0:
                if abs(close_series.iloc[-1] - real_time_price) > 0.01:
                    close_series.iloc[-1] = real_time_price 

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
        except Exception as e: pass
        time.sleep(1) 
    return pd.DataFrame(results)

@st.cache_data(ttl=3600)
def run_monte_carlo(ticker_symbol, days_to_predict=30, simulations=100):
    try:
        s = yf.Ticker(ticker_symbol)
        hist = s.history(period="1y", interval="1d")
        if hist.empty: 
            hist = yf.download(ticker_symbol, period="1y", interval="1d", progress=False)
        if hist.empty or 'Close' not in hist.columns: return None, 0, 0, 0, 0
        
        if isinstance(hist.columns, pd.MultiIndex):
            closes = hist['Close'][ticker_symbol]
        else:
            closes = hist['Close']
            
        closes = closes.dropna()
        if len(closes) < 30: return None, 0, 0, 0, 0
        
        daily_returns = closes.pct_change().dropna()
        mu = float(daily_returns.mean())
        sigma = float(daily_returns.std())
        last_price = float(closes.iloc[-1])
        
        if math.isnan(mu) or math.isnan(sigma) or math.isnan(last_price) or sigma == 0:
            return None, 0, 0, 0, 0
        
        simulation_df = pd.DataFrame()
        for x in range(simulations):
            count, price, price_series = 0, last_price, []
            for y in range(days_to_predict):
                if count >= days_to_predict: break
                price = price * (1 + np.random.normal(mu, sigma))
                if math.isnan(price): price = last_price
                price_series.append(price)
                count += 1
            simulation_df[x] = price_series
            
        expected_price = float(simulation_df.iloc[-1].mean())
        upper_bound = float(simulation_df.iloc[-1].quantile(0.95))
        lower_bound = float(simulation_df.iloc[-1].quantile(0.05))
        
        if math.isnan(expected_price) or math.isnan(upper_bound) or math.isnan(lower_bound):
            return None, 0, 0, 0, 0
            
        return simulation_df, expected_price, upper_bound, lower_bound, last_price
    except Exception as e: 
        return None, 0, 0, 0, 0

# ==========================================
# 🎛️ 5. UI Layout: แถบเมนูด้านซ้าย (Sidebar)
# ==========================================
with st.sidebar:
    if os.path.exists(logo_path): st.image(logo_path, use_container_width=True)
    else: st.title("🛡️ Strategic Hub 6.70")
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
    tf_unit = "วัน" if "1D" in tf_option else "สัปดาห์" if "1W" in tf_option else "เดือน"
    
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

with st.spinner(f"⏳ กำลังประมวลผลดึงข้อมูล กราฟ {tf_option} ..."):
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
    tabs_list.extend(["💼 บัญชีลงทุน", "🧾 ระบบภาษี", "🔮 พิทบูลพยากรณ์", "📝 แผนการเทรด", "🧪 แบคเทส 3 ประสาน", "🎛️ จัดพอร์ตจำลอง"])
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
        st.markdown(f"<span style='color:#B0BEC5;'>📅 ข้อมูลอัปเดตล่าสุด: {last_candle_date} | 🕒 เวลาอัปเดตระบบ: {current_time} <br>📌 (กำลังแสดงผลและวิเคราะห์อิงจาก **{tf_option}**)</span>", unsafe_allow_html=True)
        
        m_c1, m_c2 = st.columns(2)
        m_c1.metric("💵 ราคาตลาดล่าสุด (Real-Time)", f"${last_p:,.2f}")
        m_c2.metric(f"📊 การเปลี่ยนแปลงจากราคาปิด{tf_unit}ก่อนหน้า", f"{'+' if daily_diff >= 0 else ''}{daily_diff:,.2f} USD", delta=f"{daily_pct:+.2f}%")
        
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

        st.markdown(f'<div class="pro-box" style="border-left: 8px solid {color}; padding: 20px; border-radius: 8px; margin: 15px 0;"><h4 style="color: {color}; margin-top: 0;">🤵 ทัศนะเทรดเดอร์ (วิเคราะห์จากกราฟ {tf_option}): {rec}</h4><p style="color: #E0E0E0; margin-bottom: 0;">{msg}</p></div>', unsafe_allow_html=True)
        rs_val = df['RS'].iloc[-1]
        rs_t = f" | **Relative Strength:** {'🟢 ชนะตลาด' if rs_val > 0 else '🔴 อ่อนแอ'} ({rs_val:.2f}%)" if not np.isnan(rs_val) else ""
        if matrix: st.info(f"🔮 **ทิศทาง {tf_option}:** {matrix['tr']} | **เป้าหมาย (Harmonic Matrix):** {matrix['l']:,.2f} - {matrix['u']:,.2f} {rs_t}")
        
        c_l, c_r = st.columns([7, 3])
        with c_l:
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name="Price"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['E10'], line=dict(color='#00E676', width=1), name=f"EMA 10 {tf_unit}"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['E25'], line=dict(color='#BA68C8', width=1.5), name=f"EMA 25 {tf_unit}"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['E50'], line=dict(color='#FF6D00', width=2), name=f"EMA 50 {tf_unit}"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['E200'], line=dict(color='#E0E0E0', width=1, dash='dot'), name=f"EMA 200 {tf_unit}"), row=1, col=1)
            actual_cost = holdings[ticker]["total_cost"] / holdings[ticker]["shares"] if st.session_state["logged_in"] and holdings.get(ticker, {}).get("shares", 0) > 0.001 else b_p
            if actual_cost > 0: fig.add_hline(y=actual_cost, line_dash="dash", line_color="cyan", annotation_text="ต้นทุนเฉลี่ย", row=1, col=1)
            fig.add_trace(go.Bar(x=df.index, y=df['Hist'], marker_color=['#00E676' if v >= 0 else '#FF5252' for v in df['Hist']], name="MACD"), row=2, col=1)
            fig.update_layout(template="plotly_dark", height=600, margin=dict(l=0,r=0,t=0,b=0), showlegend=False, xaxis_rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)
            
            st.markdown(f'<div class="val-box"><h4>⚖️ ประเมินมูลค่าที่แท้จริง (Fair Value Assessment)</h4><p style="font-size: 0.9em; color: #B0BEC5;">ระบบคำนวณจากปัจจัยพื้นฐาน (อิงสถานะงบการเงินล่าสุด)</p><ul><li><b>มูลค่าที่คำนวณได้:</b> <span style="font-size: 1.2em; color: white;">{fund["fair_price"]}</span></li><li><b>สถานะความถูกแพง:</b> <span style="font-size: 1.2em;">{fund["valuation_status"]}</span></li></ul></div>', unsafe_allow_html=True)
            
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
                p_main, summary, not_to_do, t_flow = "ย่อ = ซื้อเพิ่ม / ถือรันเทรนด์", "🟢 'เกมลุย'", "❌ ห้ามสวนเทรนด์ (Short/Put)<br>❌ อย่ารีบขายหมู", f"หลุด {levels['s1']:.2f} (ระวัง) ➡ ยืน {levels['s1']:.2f} (ลุ้นต่อ) ➡ เบรก {levels['r2']:.2f} (ไปต่อยาว)"
            elif not is_uptrend:
                p_main, summary, not_to_do, t_flow = "เด้ง = หนี / ลดความเสี่ยง", "🔴 'เกมป้องกัน'", "❌ ห้ามไล่ซื้อสวนทาง<br>❌ ห้ามถัวเพิ่มเด็ดขาด", f"หลุด {levels['s2']:.2f} (ลงต่อลึก) ➡ ยืน {levels['r1']:.2f} ได้ (ลุ้นกลับตัว)"
            else:
                p_main, summary, not_to_do, t_flow = "รอจังหวะ / เลือกทาง", "🟡 'เกมระวัง'", "❌ ห้ามทุ่มสุดตัว<br>❌ อย่าเชื่อสัญญาณเดียว", f"หลุด {levels['s2']:.2f} (จบรอบ) ➡ แขว่งกรอบ {levels['s2']:.2f}-{levels['r1']:.2f}"
                
            st.markdown(f"""
            <div class="pro-box" style="border-top: 3px solid #FFD600;"><div class="pro-title c-yellow">แผนการเทรด (AI Update)</div><div style="margin-bottom:8px;"><b>🎯 แผนหลัก (ตอนนี้)</b><br><span class="c-gray">{p_main}</span></div></div>
            <div class="pro-box" style="border-top: 3px solid #FF5252; background-color: rgba(255, 82, 82, 0.05);"><div class="pro-title c-red">สิ่งที่ไม่ควรทำตอนนี้ ⚠️</div><div class="c-red">{not_to_do}</div></div>
            <div class="pro-box"><div class="c-gray">💡 <b>สรุปสั้นๆ:</b> {summary}<br><br><b>แผนภาพแนวโน้ม:</b> {t_flow}</div></div>
            """, unsafe_allow_html=True)
            
            sup_val = df['E50'].iloc[-1]
            if actual_cost > 0:
                pl = ((last_p - actual_cost) / actual_cost) * 100
                st.write(f"**P/L ของคุณ:** {pl:.2f}%")
            
            sl = sup_val * 0.99 if b_p == 0 and actual_cost == 0 else (actual_cost * 0.92 if actual_cost > 0 else b_p * 0.92)
            if b_p == 0 and actual_cost == 0 and sl >= last_p:
                sl = last_p * 0.95 
                
            if last_p < sl and (actual_cost > 0 or b_p > 0):
                st.error(f"🚨 **ทะลุจุด Stop Loss ไปแล้วที่ ${sl:.2f}!** แนะนำให้พิจารณา Cut Loss อย่างเคร่งครัด")
            else:
                st.error(f"🛡️ **จุดหนี (Stop Loss): ${sl:.2f}**")
                ra = t_cap * (r_pct / 100.0)
                if last_p > sl: 
                    st.success(f"🧮 **เข้าซื้อได้สูงสุด:** {math.floor(ra/(last_p-sl))} หุ้น")
    else: st.error("❌ ไม่พบข้อมูลราคาตลาด กรุณาลองเปลี่ยน Timeframe หรือกด Manage App มุมขวาล่างแล้วกด Reboot App ค่ะ")

# ==========================================
# หน้า 2: โซนเข้าซื้อเทคนิคอล
# ==========================================
with tabs[1]:
    if not df.empty:
        st.markdown(f"## 🔬 โซนเข้าซื้อ (Action Zones) : {ticker}")
        st.markdown(f"**📌 วิเคราะห์เจาะลึกอิงตามกราฟความละเอียด: {tf_option}**")
        
        last_close, ema10, ema25, ema50, ema200, rsi, macd, sig = df['Close'].iloc[-1], df['E10'].iloc[-1], df['E25'].iloc[-1], df['E50'].iloc[-1], df['E200'].iloc[-1], df['RSI'].iloc[-1], df['MACD'].iloc[-1], df['Sig'].iloc[-1]
        is_bullish_macd = macd > sig
        st.markdown(f"💡 **ราคาตลาดปัจจุบัน:** `${last_close:,.2f} USD` | **ส่วนต่างราคาล่าสุดนับจากปิด{tf_unit}วานนี้:** `{daily_diff:+,.2f} USD ({daily_pct:+.2f}%)`")
        
        if last_close > ema200: 
            trend_main = "🟢 ขาขึ้นระยะยาว (Bullish)"
            trend_desc = f"ราคาอยู่เหนือเส้น EMA 200 {tf_unit} แสดงว่าเทรนด์หลักของกราฟ {tf_option} เป็นขาขึ้น แนะนำให้หาจังหวะ **'ย่อซื้อ'** จะได้เปรียบที่สุด"
        else: 
            trend_main = "🔴 ขาลงระยะยาว (Bearish)"
            trend_desc = f"ราคาอยู่ใต้เส้น EMA 200 {tf_unit} แสดงว่าเทรนด์หลักอ่อนแอ หากจะเล่นต้องเป็นสาย **'เก็งกำไรเด้งสั้น'** เท่านั้น ห้ามถือนาน"
            
        action_signal = ""
        action_desc = ""
        action_color = ""
        
        if last_close > ema200:
            if not is_bullish_macd:
                action_signal = "⚠️ PULLBACK WARNING (ระวังการพักฐาน)"
                action_desc = "ระยะยาวเป็นขาขึ้น แต่ระยะสั้นโมเมนตัมหักหัวลงพักฐาน (MACD อ่อนแรง) ห้ามไล่ซื้อหรือรับมีดเด็ดขาด ให้รอดูสัญญาณกลับตัว"
                action_color = "#FF9800"
            elif last_close < ema25 and last_close >= (ema50 * 0.98) and rsi < 50 and is_bullish_macd:
                action_signal = "🟢 ย่อตัวลงมาในโซนซื้อ (Buy the Dip)"
                action_desc = f"ราคาย่อตัวลงมาพักฐานใกล้แนวรับสำคัญ (EMA 50 {tf_unit}) และโมเมนตัมเริ่มฟื้นตัว เป็นจังหวะดีในการแบ่งไม้สะสม"
                action_color = "#00E676"
            elif rsi >= 70:
                action_signal = "🔥 OVERBOUGHT (ระวังแรงขาย)"
                action_desc = "เข้าเขตซื้อมากเกินไป ไม่ควรไล่ราคา"
                action_color = "#FF9800"
            else:
                action_signal = "⏳ รอจังหวะชัดเจน (Wait & See)"
                action_desc = "กราฟกำลังสร้างฐานสะสมพลัง แนะนำให้ทับมือรอดูไปก่อน"
                action_color = "#B0BEC5"
        else:
            if rsi < 30 and macd > sig:
                action_signal = "⚡ เก็งกำไรเด้งสั้น (Speculative Rebound)"
                action_desc = "ราคาลงมาลึกมากจนเริ่มมีสัญญาณซื้อสวนทาง (Oversold) เหมาะสำหรับเล่นเด้งสั้นๆ แต่ต้องมีจุดตัดขาดทุนที่เคร่งครัด"
                action_color = "#2962FF"
            else:
                action_signal = "❌ ทับมือ ห้ามรับมีด (Downtrend Risk)"
                action_desc = "เทรนด์เป็นขาลงชัดเจนและยังไม่มีสัญญาณกลับตัว ห้ามเข้าไปรับมีด แนะนำให้อยู่เฉยๆ"
                action_color = "#FF5252"

        c_t1, c_t2 = st.columns(2)
        with c_t1:
            st.markdown(f'<div class="pro-box" style="border-top: 4px solid #82B1FF;"><div style="font-size: 0.9em; color: #B0BEC5;">ภาพรวมกระแสน้ำ (Primary Trend)</div><div style="font-size: 1.4em; font-weight: bold; margin: 10px 0;">{trend_main}</div><div style="color: #E0E0E0; font-size: 0.95em;">{trend_desc}</div></div>', unsafe_allow_html=True)
        with c_t2:
            st.markdown(f'<div class="pro-box" style="border-top: 4px solid {action_color}; background-color: {action_color}11;"><div style="font-size: 0.9em; color: #B0BEC5;">สถานะจุดเข้า (Entry Action)</div><div style="font-size: 1.4em; font-weight: bold; color: {action_color}; margin: 10px 0;">{action_signal}</div><div style="color: #E0E0E0; font-size: 0.95em;">{action_desc}</div></div>', unsafe_allow_html=True)
            
        st.markdown("---")
        st.markdown(f"### 👑 บทสรุปเอกฉันท์ (The Objective Consensus - อิงกราฟ {tf_option})")
        with st.spinner("⏳ ประมวลผลข้อมูล มหภาค + เทคนิค + พิทบูลพยากรณ์ อย่างเป็นกลาง..."):
            sim_df_quick, exp_p_quick, up_b_quick, low_b_quick, _ = run_monte_carlo(ticker, days_to_predict=30)
            if sim_df_quick is not None:
                upside_quick = ((exp_p_quick - last_close) / last_close) * 100
                if last_close > ema50 and is_bullish_macd and rsi < 70 and exp_p_quick > last_close and is_market_good:
                    m_col, m_sig, m_desc = "#00E676", "🌟 FULLY ALIGNED (สอดคล้องทุกมิติ: ทยอยสะสม)", f"สอดคล้อง 3 มิติ! **ตลาดโลกเป็นใจ** + **กราฟเทคนิค {tf_option}** เป็นขาขึ้นชัดเจน หนุนด้วย**สถิติพยากรณ์รายวัน**ที่ให้เป้าหมาย 30 วันทำการข้างหน้าไปที่ **${exp_p_quick:.2f}** (+{upside_quick:.2f}%) แนะนำหาจังหวะย่อซื้อที่แนวรับ Fibonacci หรือ EMA 50 {tf_unit}"
                elif last_close > ema200 and (not is_bullish_macd or rsi >= 70):
                    m_col, m_sig, m_desc = "#FF9800", "⚠️ PULLBACK WARNING (สัญญาณพักฐาน: ชะลอการลงทุน)", f"ระวัง! เทรนด์ยาวยังเป็นขาขึ้น แต่ **ภาพระยะสั้นโมเมนตัมกำลังหักหัวลง (MACD อ่อนแรง) หรือเข้าเขตซื้อมากเกินไป (Overbought)** แม้สถิติจะมองเป้าหมาย 30 วันทำการไว้ที่ **${exp_p_quick:.2f}** แต่ในทางปฏิบัติ นี่คือ 'การพักฐาน' แนะนำให้ **ทับมือ (Wait & See)** ไม่ควรไล่ราคา"
                elif last_close < ema50 and exp_p_quick < last_close:
                    m_col, m_sig, m_desc = "#FF5252", "🚨 HIGH RISK (ทิศทางขาลง: หลีกเลี่ยง)", f"อันตราย! **กราฟเทคนิค {tf_option}** เป็นขาลงชัดเจน สอดคล้องกับ**สถิติพยากรณ์รายวัน**ที่ประเมินว่าราคาจะไหลลงไปที่ **${exp_p_quick:.2f}** ({upside_quick:.2f}%) ใน 30 วันทำการข้างหน้า แนะนำให้ 'หลีกเลี่ยง' หรือหนีตายหากหลุด ${low_b_quick:.2f}"
                else:
                    m_col, m_sig, m_desc = "#FFD600", "⚖️ NEUTRAL / DIVERGENCE (สัญญาณขัดแย้ง: รอเลือกทาง)", "สัญญาณจาก 3 มิติยังขัดแย้งกัน แนะนำให้ **เทรดอย่างระมัดระวังในกรอบแคบๆ** หรือรอดูความชัดเจนจนกว่าแนวโน้มและโมเมนตัมจะไปในทิศทางเดียวกัน"

                st.markdown(f'<div style="background-color: #1E1E1E; border-left: 8px solid {m_col}; padding: 20px; border-radius: 8px; margin: 15px 0;"><h4 style="color: {m_col}; margin-top: 0;">{m_sig}</h4><p style="color: #E0E0E0; margin-bottom: 0; font-size: 1.05em;">{m_desc}</p></div>', unsafe_allow_html=True)
            else: st.warning("⚠️ ไม่สามารถดึงข้อมูลพิทบูลมาสรุปผลได้ในขณะนี้")
        st.markdown("---")

        st.markdown(f"### 🔎 กราฟเจาะลึกแบบซูมระยะประชิด (60 {tf_unit}ล่าสุด)")
        df_zoom = df.tail(60)
        fig_zoom = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.04, row_heights=[0.6, 0.2, 0.2])
        fig_zoom.add_trace(go.Candlestick(x=df_zoom.index, open=df_zoom['Open'], high=df_zoom['High'], low=df_zoom['Low'], close=df_zoom['Close'], name="Price"), row=1, col=1)
        fig_zoom.add_trace(go.Scatter(x=df_zoom.index, y=df_zoom['E10'], line=dict(color='#00E676', width=1.5), name=f"EMA 10 {tf_unit} (ระยะสั้น)"), row=1, col=1)
        fig_zoom.add_trace(go.Scatter(x=df_zoom.index, y=df_zoom['E25'], line=dict(color='#BA68C8', width=1.5), name=f"EMA 25 {tf_unit} (กลางสั้น)"), row=1, col=1)
        fig_zoom.add_trace(go.Scatter(x=df_zoom.index, y=df_zoom['E50'], line=dict(color='#FF6D00', width=2), name=f"EMA 50 {tf_unit} (แนวรับหลัก)"), row=1, col=1)
        fig_zoom.add_trace(go.Scatter(x=df_zoom.index, y=df_zoom['E200'], line=dict(color='#E0E0E0', width=1.5, dash='dot'), name=f"EMA 200 {tf_unit} (เทรนด์ใหญ่)"), row=1, col=1)
        
        if last_close < df_zoom['E25'].iloc[-1] and last_close >= (ema50 * 0.95): fig_zoom.add_hline(y=ema50, line_dash="solid", line_color="#00E676", annotation_text="โซนเฝ้าระวังเข้าซื้อ (Buy Zone)", row=1, col=1, opacity=0.5)

        st.markdown("---")
        show_fibo = st.checkbox(f"📐 เปิดใช้ระบบตีเส้น Fibonacci Retracement (60 {tf_unit}ล่าสุด)", value=True)
        if show_fibo:
            max_p, min_p = df_zoom['High'].max(), df_zoom['Low'].min()
            diff = max_p - min_p
            f_levels = [(0.0, "0.0% (High)", "#FF5252"), (0.236, "23.6%", "#FFB74D"), (0.382, "38.2%", "#FFF176"), (0.5, "50.0%", "#E0E0E0"), (0.618, "61.8% (Golden Ratio)", "#00E676"), (0.786, "78.6%", "#4DD0E1"), (1.0, "100.0% (Low)", "#FF5252")]
            for ratio, label, color in f_levels:
                fibo_y = max_p - (diff * ratio)
                fig_zoom.add_hline(y=fibo_y, line_dash="dot", line_color=color, annotation_text=f"{label} : ${fibo_y:.2f}", row=1, col=1, opacity=0.8)
                
            st.markdown(f"#### 🧠 บทสรุปวิเคราะห์ Fibonacci (อิงกราฟ {tf_option})")
            fibo_382, fibo_618, fibo_786 = max_p - (diff * 0.382), max_p - (diff * 0.618), max_p - (diff * 0.786)
            if last_close > fibo_382: f_sum = "🟢 **แนวโน้มแข็งแกร่ง (Strong Uptrend):** ราคายืนอยู่เหนือระดับ 38.2% แสดงถึงเทรนด์ขาขึ้นที่มีแรงขายออกเพียงเล็กน้อย หุ้นมีโอกาสทำจุดสูงสุดใหม่ (New High) ต่อได้"
            elif last_close > fibo_618: f_sum = f"🟡 **โซนสัดส่วนทองคำ (Golden Zone):** ราคาพักตัวลงมาที่โซนสมดุล (50% - 61.8%) นี่คือ **'จุดย่อซื้อ (Buy the Dip)'** ที่ได้เปรียบที่สุดทางคณิตศาสตร์ แนะนำให้เฝ้าระวังการกลับตัว"
            elif last_close > fibo_786: f_sum = "🟠 **พักตัวลึก (Deep Pullback):** ราคาลงมาลึกมากถึงระดับ 78.6% ควรระมัดระวัง อาจเป็นการเตือนว่าเทรนด์ขาขึ้นเริ่มหมดแรง และเตรียมเปลี่ยนเป็นแนวโน้มขาลง"
            else: f_sum = "🔴 **เปลี่ยนเป็นขาลง (Downtrend):** ราคาหลุดสัดส่วนฟิโบนาชชีทั้งหมดไปแล้ว แสดงถึงการพักตัวล้มเหลว และได้เปลี่ยนเทรนด์เป็นขาลงเต็มตัวเรียบร้อยแล้ว แนะนำให้หลีกเลี่ยง"
            st.info(f_sum)

        fig_zoom.add_trace(go.Bar(x=df_zoom.index, y=df_zoom['Hist'], marker_color=['#00E676' if v >= 0 else '#FF5252' for v in df_zoom['Hist']], name="MACD Hist"), row=2, col=1)
        fig_zoom.add_trace(go.Scatter(x=df_zoom.index, y=df_zoom['MACD'], line=dict(color='#2962FF', width=1.5), name="MACD Line"), row=2, col=1)
        fig_zoom.add_trace(go.Scatter(x=df_zoom.index, y=df_zoom['Sig'], line=dict(color='#FFD600', width=1.5), name="Signal Line"), row=2, col=1)
        fig_zoom.add_trace(go.Scatter(x=df_zoom.index, y=df_zoom['RSI'], line=dict(color='#FF9800', width=1.5), name="RSI"), row=3, col=1)
        fig_zoom.add_hline(y=70, line_dash="dot", line_color="#FF5252", row=3, col=1) 
        fig_zoom.add_hline(y=30, line_dash="dot", line_color="#00E676", row=3, col=1) 
        fig_zoom.update_yaxes(range=[0, 100], row=3, col=1)
        fig_zoom.update_layout(template="plotly_dark", height=750, margin=dict(l=0,r=0,t=40,b=0), showlegend=True, legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0))
        fig_zoom.update_xaxes(rangeslider_visible=False)
        st.plotly_chart(fig_zoom, use_container_width=True)

# ==========================================
# หน้า 3: เรดาร์สแกนหุ้น (AI Screener)
# ==========================================
with tabs[2]:
    st.markdown(f"## 🎯 เรดาร์สแกนหุ้น (AI Screener & Mini-Chart)")
    st.markdown(f"### 📋 จัดการรายชื่อหุ้นในเรดาร์ (สแกนอิงตามกราฟ: **{tf_option}**)")
    st.info("⚠️ แนะนำใส่ชื่อหุ้นทีละ 3-5 ตัว เพื่อป้องกันการโดนแบนจาก Yahoo Finance ค่ะ")
    
    c_rad1, c_rad2 = st.columns([7, 3])
    with c_rad1:
        default_pool = ["ASTS", "RKLB", "NVTS", "IREN", "RGTI", "C", "TSLA", "PLTR", "ONDS", "OKLO", "EOSE", "IONQ", "NOW", "MNDY", "ADBE", "CRWD", "AMKR", "NVDA", "MSFT", "GOOGL"]
        all_options = sorted(list(set(st.session_state.radar_tickers + default_pool)))
        selected_radar = st.multiselect("หุ้นที่กำลังเฝ้าจับตา (กด X เพื่อลบออก):", options=all_options, default=st.session_state.radar_tickers)
        if selected_radar != st.session_state.radar_tickers:
            if len(selected_radar) > 20: st.error("⚠️ ไม่สามารถเลือกเกิน 20 ตัวได้ค่ะ! ระบบจำกัดรายชื่อเพื่อเสถียรภาพสูงสุด")
            else: st.session_state.radar_tickers = selected_radar; st.rerun()
                
    with c_rad2:
        new_ticker = st.text_input("➕ เพิ่มหุ้นใหม่", placeholder="เช่น AMZN").upper().strip()
        if st.button("เพิ่มเข้าเรดาร์", use_container_width=True):
            if len(st.session_state.radar_tickers) >= 20: st.error("⚠️ เรดาร์เต็ม 20 ตัวแล้วค่ะ! กรุณากดปุ่มกากบาท (X) ลบตัวเก่าออกก่อนถึงจะเพิ่มตัวใหม่ได้นะคะ")
            elif new_ticker and new_ticker not in st.session_state.radar_tickers:
                st.session_state.radar_tickers.append(new_ticker)
                st.rerun()

    if len(st.session_state.radar_tickers) == 0:
        st.warning("⚠️ คุณยังไม่ได้เลือกหุ้นในเรดาร์เลยค่ะ กรุณากดเลือกที่ช่องด้านบนก่อนนะคะ")
    else:
        if st.button(f"🚀 สแกนและอัปเดตกราฟ (อิงข้อมูล {tf_option})", type="primary", use_container_width=True):
            with st.spinner("⏳ AI กำลังวิ่งดึงกราฟ... (รอประมาณ 1-2 วินาทีต่อ 1 หุ้น เพื่อหลบการแบนจาก Yahoo)"):
                screener_df = run_ai_screener(st.session_state.radar_tickers, tf_option)
                if not screener_df.empty:
                    def color_action(val):
                        if "STRONG BUY" in str(val): return 'background-color: rgba(0, 230, 118, 0.2); color: #00E676; font-weight: bold;'
                        elif "SPECULATE" in str(val): return 'color: #82B1FF; font-weight: bold;'
                        elif "OVERBOUGHT" in str(val): return 'background-color: rgba(255, 214, 0, 0.2); color: #FFD600; font-weight: bold;'
                        elif "WAIT" in str(val): return 'color: #FF5252;'
                        return ''
                    st.dataframe(screener_df.style.map(color_action, subset=["คำแนะนำ AI"]), use_container_width=True, height=600)
                else: st.warning("⚠️ ไม่พบข้อมูล กรุณากดปุ่ม 'ดึงข้อมูลเรียลไทม์เดี๋ยวนี้' ที่เมนูด้านซ้ายเพื่อล้างความจำ แล้วลองใหม่อีกครั้งค่ะ")

# ==========================================
# หน้า 4: บัญชีลงทุน
# ==========================================
if st.session_state["logged_in"]:
    with tabs[3]:
        st.subheader("💼 แดชบอร์ดกระแสเงินสด")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("📤 โอนออก (ลงทุน)", f"${l_stat['outward']:,.2f}")
        col2.metric("📥 โอนกลับ (ถอน)", f"${l_stat['inward']:,.2f}")
        col3.metric("📈 ต้นทุนสุทธิในพอร์ต", f"${l_stat['bought'] - l_stat['sold']:,.2f}")
        col4.metric("💰 เงินสดคงเหลือ", f"${cb:,.2f}")
        
        st.markdown("---")
        h1, h2 = st.columns([8, 2])
        h1.subheader("📝 สมุดบัญชีเงินสด (Cloud Ledger)")
        h2.download_button("📥 โหลด (Excel)", convert_df_to_csv(st.session_state.trade_ledger), f"Ledger_{datetime.now().strftime('%Y%m%d')}.csv", 'text/csv', use_container_width=True, key="dl_ledger_v670")
        
        with st.expander("📤 นำเข้าข้อมูลจากไฟล์ Excel / CSV", expanded=False):
            template_df = pd.DataFrame(columns=["Date", "Action", "Ticker", "Price", "Shares", "Amount_USD", "Running_Balance", "FX_Rate", "WHT_USD", "Ref_Doc"])
            st.download_button("📝 โหลดไฟล์ Template ว่าง (Excel/CSV)", convert_df_to_csv(template_df), "Trade_Template.csv", "text/csv", key="dl_template_v670")
            uploaded_file = st.file_uploader("ลากไฟล์มาวาง หรือ กดเพื่อเลือกไฟล์", type=['csv', 'xlsx'])
            if uploaded_file is not None:
                c_imp1, c_imp2 = st.columns(2)
                with c_imp1:
                    if st.button("➕ เพิ่มข้อมูลต่อท้าย (Append)", use_container_width=True):
                        try:
                            df_imported = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
                            if 'Date' in df_imported.columns: df_imported['Date'] = pd.to_datetime(df_imported['Date'], errors='coerce').dt.strftime("%d/%m/%Y").replace("NaT", "")
                            req_cols = ["Date", "Action", "Ticker", "Price", "Shares", "Amount_USD", "Running_Balance", "FX_Rate", "WHT_USD", "Ref_Doc"]
                            for col in req_cols:
                                if col not in df_imported.columns: df_imported[col] = ""
                            st.session_state.trade_ledger = pd.concat([st.session_state.trade_ledger, clean_df_types(df_imported[req_cols])], ignore_index=True)
                            st.success("✅ นำข้อมูลใหม่ไปต่อท้ายตารางเรียบร้อย!"); time.sleep(2); st.rerun()
                        except: st.error("❌ อ่านไฟล์ไม่สำเร็จ")
                with c_imp2:
                    if st.button("🔄 แทนที่ทั้งหมด (Overwrite)", type="primary", use_container_width=True):
                        try:
                            df_imported = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
                            if 'Date' in df_imported.columns: df_imported['Date'] = pd.to_datetime(df_imported['Date'], errors='coerce').dt.strftime("%d/%m/%Y").replace("NaT", "")
                            req_cols = ["Date", "Action", "Ticker", "Price", "Shares", "Amount_USD", "Running_Balance", "FX_Rate", "WHT_USD", "Ref_Doc"]
                            for col in req_cols:
                                if col not in df_imported.columns: df_imported[col] = ""
                            st.session_state.trade_ledger = clean_df_types(df_imported[req_cols])
                            st.success("✅ แทนที่ตารางด้วยข้อมูลจากไฟล์ใหม่เรียบร้อย!"); time.sleep(2); st.rerun()
                        except: st.error("❌ อ่านไฟล์ไม่สำเร็จ")
        
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
            if save_df_to_sheet("Ledger", st.session_state.trade_ledger): st.success("บันทึกสำเร็จ!")

        st.markdown("---")
        st.subheader("📊 ตารางสรุปพอร์ตโฟลิโอปัจจุบัน (Smart Risk Matrix)")
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
            sector_exposure = {}
            warning_list = []
            
            with st.spinner("⏳ กำลังดึงราคาล่าสุด วิเคราะห์วินัยการลงทุน และคำนวณจุดหนี..."):
                batch_prices = get_batch_live_prices(current_port_df["Ticker"].tolist())
                for _, row in current_port_df.iterrows():
                    t, avg_cost, sh, t_cost = row["Ticker"], row["Cost_Price"], row["Shares"], row["Total_Cost"]
                    curr_p = batch_prices.get(t, avg_cost)
                    val = curr_p * sh
                    profit_usd = val - t_cost
                    drawdown_pct = (profit_usd / t_cost) * 100 if t_cost > 0 else 0
                    
                    recovery_needed = 0
                    if drawdown_pct < 0:
                        recovery_needed = (abs(drawdown_pct) / (100 - abs(drawdown_pct))) * 100
                        if drawdown_pct <= -10:
                            warning_list.append(f"**{t}**: ติดลบ {drawdown_pct:.2f}% (ต้องทำกำไรคืนถึง **+{recovery_needed:.2f}%** แค่เพื่อเท่าทุน!)")

                    sl_price = avg_cost * 0.90  
                    target_entry = avg_cost * 0.80 
                    
                    sl_status = f"🚨 CUT ({sl_price:.2f})" if curr_p <= sl_price else f"🛡️ Safe ({sl_price:.2f})"
                    entry_status = f"🟢 ถัวได้ ({target_entry:.2f})" if curr_p <= target_entry else f"⏳ ห้ามถัว ({target_entry:.2f})"
                    
                    results.append({
                        "หุ้น": t, 
                        "จำนวนหุ้น": sh, 
                        "ต้นทุนเฉลี่ย": avg_cost, 
                        "ราคาปัจจุบัน": curr_p, 
                        "กำไร/ขาดทุน ($)": profit_usd, 
                        "กำไร/ขาดทุน (฿)": profit_usd * live_fx, 
                        "% เปลี่ยนแปลง": drawdown_pct, 
                        "ต้องทำกำไรคืนทุน": f"+{recovery_needed:.1f}%" if recovery_needed > 0 else "-",
                        "มูลค่ารวม": val,
                        "จุดวินัย (SL -10%)": sl_status,
                        "จุดถัว (DCA -20%)": entry_status
                    })
                    
                    total_v += val
                    
                    try:
                        t_sec = yf.Ticker(t).info.get('sector', 'Unknown')
                    except: t_sec = 'Unknown'
                    sector_exposure[t_sec] = sector_exposure.get(t_sec, 0) + val
            
            port_pct_ret = ((total_v - total_invested) / total_invested * 100) if total_invested > 0 else 0
            
            p1, p2, p3, p4 = st.columns(4)
            p1.metric("มูลค่าหุ้นรวม ($)", f"${total_v:,.2f}")
            p2.metric("ต้นทุนทั้งหมด ($)", f"${total_invested:,.2f}")
            p3.metric("กำไร/ขาดทุนรวม ($)", f"${total_v - total_invested:,.2f}", f"{port_pct_ret:.2f}%")
            p4.metric("กำไร/ขาดทุนรวม (฿)", f"฿{(total_v - total_invested) * live_fx:,.2f}")
            
            st.markdown("---")
            st.markdown("### 🏛️ การวิเคราะห์พอร์ตระดับสถาบัน (Institutional Analytics)")
            i_col1, i_col2 = st.columns(2)
            
            with i_col1:
                st.markdown("**1. วัดผลตอบแทนเทียบตลาด (Alpha / Beta)**")
                spy_ret = get_market_benchmark()
                if math.isnan(spy_ret): spy_ret = 0.0
                alpha_diff = port_pct_ret - spy_ret
                
                st.metric("S&P 500 (1Y Return)", f"{spy_ret:.2f}%")
                if alpha_diff >= 0:
                    st.success(f"🌟 **Alpha ของคุณ: +{alpha_diff:.2f}%** (คุณกำลังเอาชนะตลาดโลกได้!)")
                else:
                    st.warning(f"📉 **Alpha ของคุณ: {alpha_diff:.2f}%** (ผลตอบแทนตามหลังตลาดหลัก แนะนำให้คัดกรองหุ้นใหม่)")
                    
            with i_col2:
                st.markdown("**2. ความเสี่ยงกระจุกตัว (Sector Exposure)**")
                sec_df = pd.DataFrame(list(sector_exposure.items()), columns=['Sector', 'Value'])
                fig_sec = go.Figure(data=[go.Pie(labels=sec_df['Sector'], values=sec_df['Value'], hole=.5)])
                fig_sec.update_layout(template="plotly_dark", height=250, margin=dict(t=10, b=10, l=0, r=0))
                st.plotly_chart(fig_sec, use_container_width=True)

            with st.expander("💡 ไอเดียหุ้นชั้นนำระดับโลกกระจายตาม Sector (Institutional Recommended Watchlist)", expanded=False):
                st.markdown("""
                คำแนะนำจากผู้จัดการกองทุน: เพื่อลดความเสี่ยงจากการกระจุกตัว แนะนำกระจายเงินไปยังหุ้น Blue-Chip คุณภาพสูง 5 Sector หลักต่อไปนี้:
                """)
                rec_sectors_data = {
                    "Technology & AI": [("NVDA", "Nvidia", "ผู้นำ ชิป AI โลก"), ("MSFT", "Microsoft", "ซอฟต์แวร์ & Cloud AI"), ("AAPL", "Apple", "Device & Ecosystem"), ("GOOGL", "Alphabet", "Search & AI Engine"), ("AVGO", "Broadcom", "Networking Chip")],
                    "Financial Services": [("JPM", "JPMorgan", "ธนาคารอันดับ 1 ของโลก"), ("BRK-B", "Berkshire", "กองทุนปู่บัฟเฟตต์"), ("V", "Visa", "เครือข่ายชำระเงินโลก"), ("MA", "Mastercard", "ระบบการชำระเงินดิจิทัล"), ("BAC", "Bank of America", "ธนาคารพาณิชย์หลัก")],
                    "Healthcare & Biotech": [("LLY", "Eli Lilly", "ยาลดน้ำหนัก/เบาหวาน"), ("NVO", "Novo Nordisk", "ยาลดน้ำหนักเมกะเทรนด์"), ("UNH", "UnitedHealth", "ประกันสุขภาพอันดับ 1"), ("JNJ", "Johnson & Johnson", "เวชภัณฑ์ระดับโลก"), ("ABBV", "AbbVie", "ไบโอเทคและยาชีวภาพ")],
                    "Industrials & Defense": [("GE", "GE Aerospace", "เครื่องยนต์การบินพาณิชย์"), ("CAT", "Caterpillar", "เครื่องจักรหนักก่อสร้าง"), ("LMT", "Lockheed Martin", "ยุทโธปกรณ์ป้องกันประเทศ"), ("RTX", "RTX Corp", "ระบบการบินและป้องกันประเทศ"), ("HON", "Honeywell", "เทคโนโลยีอุตสาหกรรม")],
                    "Consumer & Energy": [("AMZN", "Amazon", "E-Commerce & AWS Cloud"), ("COST", "Costco", "ค้าปลีกทนทานเงินเฟ้อ"), ("WMT", "Walmart", "ยักษ์ใหญ่ค้าปลีกโลก"), ("XOM", "ExxonMobil", "พลังงานและน้ำมันยักษ์ใหญ่"), ("CVX", "Chevron", "พลังงานครบวงจรปันผลสูง")]
                }
                
                s_tab1, s_tab2, s_tab3, s_tab4, s_tab5 = st.tabs(list(rec_sectors_data.keys()))
                all_s_tabs = [s_tab1, s_tab2, s_tab3, s_tab4, s_tab5]
                for idx, (s_name, s_stocks) in enumerate(rec_sectors_data.items()):
                    with all_s_tabs[idx]:
                        s_df = pd.DataFrame(s_stocks, columns=["Ticker", "ชื่อบริษัท", "จุดเด่นเชิงกลยุทธ์"])
                        st.table(s_df)

            if warning_list:
                st.markdown("---")
                st.error("#### ⚠️ คำเตือนจากระบบวินัยการลงทุน (Sunk Cost Reality Check)")
                st.write("หุ้นต่อไปนี้ทะลุจุด Stop Loss 10% ไปแล้ว หากปล่อยไว้ การทวงทุนคืนจะยากขึ้นทวีคูณแบบก้าวกระโดด:")
                for warn in warning_list:
                    st.write(f"- {warn}")

            st.markdown("---")
            res_df = pd.DataFrame(results)
            chart_col1, chart_col2 = st.columns(2)
            with chart_col1:
                fig_pie = go.Figure(data=[go.Pie(labels=res_df['หุ้น'], values=res_df['มูลค่ารวม'], hole=.4)])
                fig_pie.update_layout(title="สัดส่วนหุ้นในพอร์ต (Stock Allocation)", template="plotly_dark", height=350, margin=dict(t=50, b=0, l=0, r=0))
                st.plotly_chart(fig_pie, use_container_width=True)
            with chart_col2:
                fig_bar = go.Figure(data=[go.Bar(x=res_df['หุ้น'], y=res_df['กำไร/ขาดทุน ($)'], marker_color=['#00E676' if val >= 0 else '#FF5252' for val in res_df['กำไร/ขาดทุน ($)']])])
                fig_bar.update_layout(title="กำไร/ขาดทุนรายตัว", template="plotly_dark", height=350, margin=dict(t=50, b=0, l=0, r=0))
                st.plotly_chart(fig_bar, use_container_width=True)
                
            def style_portfolio(val): 
                if isinstance(val, str) and "🚨" in val: return 'background-color: rgba(255, 82, 82, 0.2); color: #FF5252; font-weight: bold;'
                if isinstance(val, str) and "🟢" in val: return 'color: #00E676; font-weight: bold;'
                if isinstance(val, str) and "⏳" in val: return 'color: #FFD600;'
                if isinstance(val, str) and "+" in val and "%" in val: return 'color: #FF9800; font-weight: bold;'
                if isinstance(val, (int, float)): return f'color: {"#FF5252" if val < 0 else "#00E676"}; font-weight: bold;'
                return ''
                
            st.dataframe(res_df.style.map(style_portfolio, subset=["กำไร/ขาดทุน ($)", "กำไร/ขาดทุน (฿)", "% เปลี่ยนแปลง", "ต้องทำกำไรคืนทุน", "จุดวินัย (SL -10%)", "จุดถัว (DCA -20%)"]).format({
                "จำนวนหุ้น": "{:,.4f}", "ต้นทุนเฉลี่ย": "${:,.4f}", "ราคาปัจจุบัน": "${:,.4f}", 
                "กำไร/ขาดทุน ($)": "${:,.2f}", "กำไร/ขาดทุน (฿)": "฿{:,.2f}", "% เปลี่ยนแปลง": "{:,.2f}%", 
                "มูลค่ารวม": "${:,.2f}"}), use_container_width=True)
            st.download_button("📥 โหลดพอร์ต (Excel)", convert_df_to_csv(res_df), f"Portfolio_{datetime.now().strftime('%Y%m%d')}.csv", 'text/csv', key="dl_port_v670")
        else: st.info("ว่างเปล่า (ยังไม่มีหุ้นในพอร์ต)")

# ==========================================
# หน้า 5: ระบบภาษี
# ==========================================
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
            if r['Action'] == "นำเงินออกนอกประเทศ (Outward)": capital_pool += r['Out_THB']; taxable_gains_thb.append(0.0)
            elif r['Action'] == "นำเงินเข้าประเทศไทย (Inward)":
                capital_pool -= r['In_THB']
                taxable_gains_thb.append(abs(capital_pool) if capital_pool < 0 else 0.0)
                if capital_pool < 0: capital_pool = 0.0
            elif r['Action'] == "รับเงินปันผล (Dividend)": taxable_gains_thb.append(r['In_THB'])
            else: taxable_gains_thb.append(0.0)
            running_bals.append(capital_pool)

        tax_v['Taxable_Gain_THB'], tax_v['Balance_THB'] = taxable_gains_thb, running_bals
        t2.download_button("📥 โหลดภาษี (Excel)", convert_df_to_csv(tax_v), f"Tax_{datetime.now().strftime('%Y%m%d')}.csv", 'text/csv', use_container_width=True, key="dl_tax_v670")
        
        ed_t = st.data_editor(tax_v, use_container_width=True, num_rows="fixed", column_order=["Date", "Action", "Out_USD", "In_USD", "FX_Rate", "Out_THB", "In_THB", "Balance_THB", "Taxable_Gain_THB"])
        if not ed_t[["FX_Rate", "WHT_USD"]].equals(tax_v[["FX_Rate", "WHT_USD"]]):
            st.session_state.trade_ledger.loc[tax_idx, "FX_Rate"] = clean_df_types(ed_t)["FX_Rate"].values
            st.session_state.trade_ledger.loc[tax_idx, "WHT_USD"] = clean_df_types(ed_t)["WHT_USD"].values
            st.rerun()
        if st.button("💾 บันทึกภาษีลง Cloud", type="primary", use_container_width=True): 
            if save_df_to_sheet("Ledger", st.session_state.trade_ledger): st.success("บันทึกสำเร็จ!")

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
# หน้า 6: พิทบูลพยากรณ์
# ==========================================
    with tabs[5]:
        st.markdown(f"## 🔮 พิทบูลพยากรณ์ (AI Monte Carlo Simulation) : {ticker}")
        st.info(f"⚠️ **หมายเหตุทางสถิติ:** เพื่อความแม่นยำสูงสุด ระบบจำลองมอนติคาร์โลจะใช้ฐานข้อมูลความผันผวนแบบ **1D (รายวัน)** เสมอ โดยดึงข้อมูล 1 ปีเต็มในอดีต มาสุ่มสร้างเส้นทางจำลอง 100 รูปแบบในอนาคต")
        sim_days = st.slider("เลือกจำนวนวันพยากรณ์ล่วงหน้า (วันทำการ):", 5, 90, 30)
        
        if st.button("🎲 เริ่มการประมวลผลสุ่มจำลองมอนติคาร์โล", type="primary", use_container_width=True):
            with st.spinner("พิทบูลกำลังเคี้ยวข้อมูลและคำนวณความน่าจะเป็น 100 เส้นทาง..."):
                sim_df, exp_p, up_b, low_b, last_price = run_monte_carlo(ticker, days_to_predict=sim_days)
                if sim_df is not None and not math.isnan(exp_p) and exp_p > 0:
                    c1, c2, c3 = st.columns(3)
                    c1.metric("📉 กรณีเลวร้ายที่สุด (Lower 5%)", f"${low_b:.2f}")
                    c2.metric("🎯 ราคาคาดหวังตามสถิติ (Expected)", f"${exp_p:.2f}")
                    c3.metric("📈 กรณีมองโลกแง่ดีที่สุด (Upper 95%)", f"${up_b:.2f}")
                    
                    fig_sim = go.Figure()
                    for col in sim_df.columns:
                        fig_sim.add_trace(go.Scatter(x=sim_df.index, y=sim_df[col], mode='lines', line=dict(width=1, color='rgba(130, 177, 255, 0.1)'), showlegend=False))
                    fig_sim.add_trace(go.Scatter(x=[0, sim_days-1], y=[last_price, exp_p], mode='lines+markers', name='Expected Path', line=dict(color='#00E676', width=3, dash='dash')))
                    fig_sim.add_hline(y=up_b, line_dash="dot", line_color="#FFD600", annotation_text="Upper Bound")
                    fig_sim.add_hline(y=low_b, line_dash="dot", line_color="#FF5252", annotation_text="Lower Bound")
                    fig_sim.update_layout(title=f"โครงข่ายวิเคราะห์ทิศทางราคาอนาคตของ {ticker}", template="plotly_dark", height=400, xaxis_title="วันในอนาคต", yaxis_title="ราคา (USD)")
                    st.plotly_chart(fig_sim, use_container_width=True)
                    
                    st.markdown("---")
                    st.markdown("#### 🐶 สรุปคำทำนายพิทบูล (Pitbull Analysis)")
                    upside = ((exp_p - last_price) / last_price) * 100
                    if exp_p > last_price:
                        p_msg = f"🟢 **แนวโน้มเชิงบวก (Bullish):** ในอีก {sim_days} วันทำการข้างหน้า พิทบูลมองว่าราคามีโอกาสปรับตัวขึ้นไปที่ **${exp_p:.2f}** (บวก {upside:+.2f}%) หากตลาดเป็นใจอาจทะลุไปถึงกรอบบนที่ **${up_b:.2f}** แนะนำให้ **ถือรันเทรนด์ (Hold)** หรือ **หาจังหวะย่อซื้อ** โดยใช้เส้นกรอบล่าง (${low_b:.2f}) เป็นจุดตัดขาดทุน (Stop Loss)"
                        st.success(p_msg)
                    else:
                        p_msg = f"🔴 **แนวโน้มอ่อนแอ (Bearish/Sideway):** ในอีก {sim_days} วันทำการข้างหน้า ราคามีเกณฑ์แกว่งตัวออกข้างหรือปรับฐานลงไปที่ **${exp_p:.2f}** (ติดลบ {upside:+.2f}%) ระวังความเสี่ยงหากราคาหลุดลึกไปถึง **${low_b:.2f}** แนะนำให้ **ชะลอการลงทุน (Wait & See)** หรือลดสัดส่วนพอร์ต"
                        st.warning(p_msg)
                else: 
                    st.error("⚠️ ไม่สามารถประมวลผลจำลองมอนติคาร์โลได้ เนื่องจากข้อมูลดิบของหุ้นตัวนี้ไม่สมบูรณ์ กรุณาลองใหม่อีกครั้ง")

# ==========================================
# หน้า 7: แผนการเทรด
# ==========================================
    with tabs[6]:
        st.markdown(f"## 📝 แผนการเทรด (Trading Plan) : {ticker}")
        curr_p = df['Close'].iloc[-1] if not df.empty else 10.0
        ema_50_val = df['E50'].iloc[-1] if not df.empty else 9.0
        default_sl = ema_50_val if ema_50_val < curr_p else curr_p * 0.95
            
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
            plan_sl = st.number_input("🛑 ระบุจุดตั้งตัดขาดทุน Stop Loss ($)", value=float(default_sl))
            plan_tp = st.number_input("🏆 ระบุจุดตั้งเป้าทำกำไร Take Profit ($)", value=float(plan_entry + ((plan_entry - plan_sl) * 2) if plan_entry > plan_sl else curr_p * 1.1))

        st.markdown("---")
        st.markdown("#### 🧠 ระบบคำนวณไม้เทรดขั้นสูง (Advanced Position Sizing)")
        if matrix and "atr" in matrix:
            atr_v = matrix["atr"]
            safe_sl = plan_entry - (atr_v * 2)
            st.info(f"🔮 **ความผันผวน (ATR):** ${atr_v:.2f} / วัน | ระบบสถาบันแนะนำให้ตั้ง Stop Loss ที่ **${safe_sl:.2f}** (ห่างจากจุดเข้าซื้อ 2 เท่าของความแกว่งปกติ เพื่อหลบการสะบัดหลอกของตลาด)")
        
        st.markdown("#### 📊 สรุปแผนการเทรด (Trade Summary)")

        if plan_entry > plan_sl:
            risk_per_share = plan_entry - plan_sl
            reward_per_share = plan_tp - plan_entry
            
            max_shares = math.floor(risk_budget / risk_per_share) if risk_per_share > 0 else 0
            position_value = max_shares * plan_entry
            rr_ratio = reward_per_share / risk_per_share if risk_per_share > 0 else 0
            expected_profit = max_shares * reward_per_share

            if rr_ratio >= 2.0: rr_status, rr_color = "🟢 ดีเยี่ยม (Very Good)", "normal"
            elif rr_ratio >= 1.5: rr_status, rr_color = "🟡 พอใช้ได้ (Acceptable)", "off"
            else: rr_status, rr_color = "🔴 ไม่คุ้มเสี่ยง (Poor)", "inverse"

            c_sum1, c_sum2, c_sum3, c_sum4 = st.columns(4)
            c_sum1.metric("🛒 โควตาหุ้นที่ควรซื้อ (Risk Parity)", f"{max_shares:,} หุ้น")
            c_sum2.metric("💳 รวมมูลค่าเงินที่ต้องใช้", f"${position_value:,.2f}")
            c_sum3.metric("⚖️ อัตราส่วน Risk/Reward", f"1 : {rr_ratio:.2f}", rr_status, delta_color=rr_color)
            c_sum4.metric("💰 คาดหวังกำไรสุทธิ", f"${expected_profit:,.2f}")

            if position_value > plan_cap:
                st.warning(f"⚠️ **คำเตือน:** เงินลงทุนที่ต้องใช้ (${position_value:,.2f}) มากกว่าเงินทุนที่คุณมี (${plan_cap:,.2f}) แนะนำให้ปรับลด % ความเสี่ยงลงค่ะ")
            
            st.markdown("#### 💾 บันทึกแผน (Save Plan)")
            c_save1, c_save2 = st.columns([7, 3])
            with c_save1: plan_note = st.text_input("📝 หมายเหตุ (ตัวอย่าง: รอราคาย่อมาแตะ EMA50 ค่อยกดซื้อ)")
            with c_save2:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("💾 บันทึกแผนนี้เก็บไว้ดูภายหลัง", type="primary", use_container_width=True):
                    new_plan = pd.DataFrame([{"Date": current_date, "Ticker": ticker, "Entry": plan_entry, "Stop_Loss": plan_sl, "Take_Profit": plan_tp, "Risk_Budget": risk_budget, "Max_Shares": max_shares, "Note": plan_note}])
                    st.session_state.trading_plans = pd.concat([st.session_state.trading_plans, new_plan], ignore_index=True)
                    save_df_to_sheet("Trading_Plans", st.session_state.trading_plans)
                    st.success("✅ บันทึกแผนสำเร็จ! ดูที่ตารางด้านล่างได้เลยค่ะ")
                    time.sleep(0.5)
                    st.rerun()

            st.markdown("---")
            st.markdown("### 📚 ประวัติแผนการเทรดของฉัน (Saved Plans)")
            display_df = st.session_state.trading_plans.copy()
            if not display_df.empty:
                display_df.insert(0, "Select_Delete", False)
                ed_plans = st.data_editor(display_df, num_rows="dynamic", use_container_width=True,
                    column_config={
                        "Select_Delete": st.column_config.CheckboxColumn("🗑️ เลือกเพื่อลบ", default=False),
                        "Date": "วันที่บันทึก", "Ticker": "ชื่อหุ้น", "Entry": st.column_config.NumberColumn("ราคาเข้าซื้อ ($)", format="%.2f"),
                        "Stop_Loss": st.column_config.NumberColumn("จุดตัดขาดทุน ($)", format="%.2f"), "Take_Profit": st.column_config.NumberColumn("เป้าทำกำไร ($)", format="%.2f"),
                        "Risk_Budget": st.column_config.NumberColumn("งบความเสี่ยง ($)", format="%.2f"), "Max_Shares": st.column_config.NumberColumn("โควตาที่ซื้อได้ (หุ้น)", format="%d"),
                        "Note": "หมายเหตุ"
                    })
                
                if ed_plans["Select_Delete"].any():
                    st.warning("⚠️ คุณได้ติ๊กเลือกแผนที่ต้องการลบแล้ว กดปุ่มสีแดงด้านล่างเพื่อยืนยันการลบถาวรค่ะ")
                    if st.button("🗑️ ยืนยันการลบแผนที่เลือก", type="primary", use_container_width=True):
                        st.session_state.trading_plans = ed_plans[~ed_plans["Select_Delete"]].drop(columns=["Select_Delete"])
                        save_df_to_sheet("Trading_Plans", st.session_state.trading_plans)
                        st.success("✅ ลบข้อมูลสำเร็จ!")
                        time.sleep(1)
                        st.rerun()
                else:
                    updated_df = ed_plans.drop(columns=["Select_Delete"])
                    if not updated_df.equals(st.session_state.trading_plans):
                        st.session_state.trading_plans = updated_df.copy()
                        save_df_to_sheet("Trading_Plans", st.session_state.trading_plans)
                        st.rerun()
            else: st.info("ยังไม่มีประวัติแผนการเทรดค่ะ")
        else: st.error("⚠️ การคำนวณผิดพลาด: จุดตัดขาดทุน ต้องตั้งให้น้อยกว่า ราคาเข้าซื้อ เสมอนะคะ")

# ==========================================
# หน้า 8: ระบบแบคเทสกลยุทธ์ 3 ประสาน
# ==========================================
    with tabs[7]:
        st.markdown(f"## 🧪 ระบบทดสอบกลยุทธ์ย้อนหลัง 3 ประสาน (EMA + MACD + RSI)")
        st.info("⚠️ **หมายเหตุทางสถิติ:** ระบบแบคเทสจะใช้ข้อมูลกราฟ 3 ปีในอดีตแบบ **1D (รายวัน)** เสมอ เพื่อค้นหาความแม่นยำในการเข้า-ออกออเดอร์รายวันค่ะ")
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
                    c_bt2.metric("📈 ผลตอบแทนสะสมโมเดล (3 ปี)", f"{total_ret:+.2f}%", delta=f"{total_ret:+.2f}%")
                    c_bt3.metric("📋 จำนวนไม้ที่สแกนเจอตามกฎ", f"{len(trades_df)} ไม้")
                    
                    st.markdown("### 📋 ตารางบันทึกรายงานผลคำสั่งซื้อขายในอดีต")
                    display_bt = trades_df.rename(columns={
                        "entry_date": "วันที่เข้าซื้อ", "entry_price": "ราคาซื้อ ($)",
                        "exit_date": "วันที่ขายปิดไม้", "exit_price": "ราคาขาย ($)",
                        "p_l_pct": "กำไร/ขาดทุน (%)", "exit_reason": "สัญญาณที่ระบบสั่งขาย"
                    })
                    
                    def color_bt_profit(val):
                        try: return 'color: #00E676; font-weight: bold;' if float(val) > 0 else 'color: #FF5252; font-weight: bold;'
                        except: return ''
                            
                    formatted_df = display_bt[["วันที่เข้าซื้อ", "ราคาซื้อ ($)", "วันที่ขายปิดไม้", "ราคาขาย ($)", "กำไร/ขาดทุน (%)", "สัญญาณที่ระบบสั่งขาย"]]
                    st.dataframe(formatted_df.style.map(color_bt_profit, subset=["กำไร/ขาดทุน (%)"]).format({
                        "ราคาซื้อ ($)": "{:.2f}", "ราคาขาย ($)": "{:.2f}", "กำไร/ขาดทุน (%)": "{:.2f}%"
                    }), use_container_width=True)
                else: 
                    st.error("⚠️ ไม่พบจังหวะสัญญาณที่เข้าเกณฑ์กฎ 3 ประสานในช่วง 3 ปีที่ผ่านมาสำหรับหุ้นตัวนี้ค่ะ")

# ==========================================
# หน้า 9: จัดพอร์ตจำลอง (V6.70 The Stabilized Edition)
# ==========================================
    with tabs[8]:
        st.markdown("## 🎛️ ระบบจำลองและจัดพอร์ตด้วยตัวเอง (AI Portfolio Sandbox)")
        st.markdown("พื้นที่ทดลองสำหรับนักลงทุน เพื่อออกแบบพอร์ตโฟลิโอใหม่ และรับคำวิเคราะห์จาก **AI Portfolio Manager** ก่อนลงสนามจริง")
        
        history_tickers = []
        if not st.session_state.sandbox_history.empty:
            for t_str in st.session_state.sandbox_history["Tickers"].dropna():
                history_tickers.extend([t.strip() for t in str(t_str).split(",") if t.strip()])
        ledger_tickers = st.session_state.trade_ledger["Ticker"].dropna().unique().tolist() if not st.session_state.trade_ledger.empty else []
        plan_tickers = st.session_state.trading_plans["Ticker"].dropna().unique().tolist() if not st.session_state.trading_plans.empty else []
        
        default_sandbox_pool = ["NVDA", "MSFT", "AAPL", "JPM", "BRK-B", "LLY", "UNH", "GE", "LMT", "AMZN", "WMT", "TSM", "AMD", "META", "GOOGL"]
        all_sandbox_options = sorted(list(set(st.session_state.sandbox_tickers + default_sandbox_pool + st.session_state.radar_tickers + history_tickers + ledger_tickers + plan_tickers)))
        all_sandbox_options = [x for x in all_sandbox_options if x] 
        
        c_box1, c_box2 = st.columns([7, 3])
        with c_box1:
            selected_sim = st.multiselect("📌 1. เลือกหุ้นเข้าพอร์ตจำลอง:", options=all_sandbox_options, default=st.session_state.sandbox_tickers[:5] if st.session_state.sandbox_tickers else ["NVDA", "JPM", "LLY"])
        with c_box2:
            custom_ticker_add = st.text_input("➕ พิมพ์เพิ่มหุ้นใหม่ที่คุณค้นหาเอง:", placeholder="เช่น META, TSM").upper().strip()
            if st.button("เพิ่มเข้าตัวเลือกจำลอง", use_container_width=True):
                if custom_ticker_add and custom_ticker_add not in st.session_state.sandbox_tickers:
                    st.session_state.sandbox_tickers.append(custom_ticker_add)
                    st.success(f"✅ เพิ่ม {custom_ticker_add} เข้าไปในรายการแล้วค่ะ!")
                    time.sleep(0.5)
                    st.rerun()

        if len(selected_sim) > 0:
            st.markdown("#### ⚖️ 2. กำหนดสัดส่วนน้ำหนักเงินลงทุน (%)")
            cols = st.columns(min(len(selected_sim), 5))
            sim_weights = {}
            total_weight = 0
            
            for i, t in enumerate(selected_sim):
                with cols[i % 5]:
                    w = st.number_input(f"{t} (%)", min_value=0, max_value=100, value=int(100/len(selected_sim)), key=f"w_sim_{t}")
                    sim_weights[t] = w
                    total_weight += w
            
            if total_weight != 100:
                st.warning(f"⚠️ คำเตือน: สัดส่วนรวมของคุณคือ **{total_weight}%** (แนะนำปรับให้พอดี 100% เพื่อความแม่นยำ)")
            
            if st.button("📊 เริ่มวิเคราะห์ความเสี่ยงพอร์ตจำลอง (AI Audit)", type="primary", use_container_width=True):
                with st.spinner("🧠 AI กำลังวิ่งดึงงบการเงินและประวัติราคาย้อนหลังของหุ้นทุกตัว..."):
                    try:
                        hist_data = yf.download(selected_sim, period="1y", interval="1d", progress=False)
                        
                        if 'Close' in hist_data:
                            closes = hist_data['Close']
                        else:
                            closes = hist_data
                            
                        sim_returns = {}
                        sim_sectors = {}
                        
                        for t in selected_sim:
                            try:
                                if isinstance(closes, pd.DataFrame) and t in closes.columns:
                                    s_series = closes[t].dropna()
                                else:
                                    s_series = closes.dropna()
                                    
                                if len(s_series) > 10:
                                    start_p = float(s_series.iloc[0])
                                    end_p = float(s_series.iloc[-1])
                                    sim_returns[t] = ((end_p - start_p) / start_p) * 100
                                else: sim_returns[t] = 0.0
                            except: sim_returns[t] = 0.0
                                
                            try:
                                sec = yf.Ticker(t).info.get('sector', 'Unknown/Other')
                                sim_sectors[t] = sec if sec else 'Unknown/Other'
                            except:
                                sim_sectors[t] = 'Unknown/Other'
                        
                        total_sim_return = sum([sim_returns[t] * (sim_weights[t]/100) for t in selected_sim])
                        spy_ret = get_market_benchmark()
                        if math.isnan(spy_ret): spy_ret = 0.0
                        
                        sector_weights = {}
                        for t in selected_sim:
                            sec = sim_sectors[t]
                            sector_weights[sec] = sector_weights.get(sec, 0) + sim_weights[t]

                        st.markdown("---")
                        c_sim1, c_sim2 = st.columns(2)
                        with c_sim1:
                            st.markdown("### 📈 ผลลัพธ์ของพอร์ตจำลอง")
                            st.metric("ผลตอบแทนพอร์ตจำลอง (1Y Return)", f"{total_sim_return:.2f}%", f"{total_sim_return - spy_ret:+.2f}% vs S&P 500")
                            
                            sim_df_show = pd.DataFrame({
                                "หุ้น": list(sim_returns.keys()),
                                "สัดส่วน (%)": [f"{sim_weights[t]}%" for t in selected_sim],
                                "ผลตอบแทนย้อนหลัง (1Y)": [f"{sim_returns[t]:+.2f}%" for t in selected_sim],
                                "กลุ่มอุตสาหกรรม": [sim_sectors[t] for t in selected_sim]
                            })
                            st.dataframe(sim_df_show, hide_index=True, use_container_width=True)
                            
                        with c_sim2:
                            st.markdown("### 🌐 สัดส่วนกลุ่มอุตสาหกรรม (Sector Balance)")
                            sec_df = pd.DataFrame(list(sector_weights.items()), columns=['Sector', 'Weight'])
                            fig_sim_sec = go.Figure(data=[go.Pie(labels=sec_df['Sector'], values=sec_df['Weight'], hole=.5)])
                            fig_sim_sec.update_layout(template="plotly_dark", height=280, margin=dict(t=10, b=10, l=0, r=0))
                            st.plotly_chart(fig_sim_sec, use_container_width=True)

                        st.markdown("---")
                        st.markdown("### 🤖 บทวิเคราะห์และประเมินระดับมืออาชีพ (AI Portfolio Manager)")
                        max_w_sector = max(sector_weights, key=sector_weights.get)
                        
                        if sector_weights[max_w_sector] >= 45:
                            st.error(f"🚨 **เสี่ยงกระจุกตัวสูง:** พอร์ตนี้เทน้ำหนักไปที่กลุ่ม **{max_w_sector} ({sector_weights[max_w_sector]:.1f}%)** มากเกินไป หากกลุ่มนี้ปรับฐาน พอร์ตจะลบหนัก แนะนำให้กระจายไปกลุ่ม Defensive เพิ่ม")
                        elif sector_weights[max_w_sector] >= 30:
                            st.warning(f"⚠️ **การกระจายความเสี่ยงปานกลาง:** กลุ่ม **{max_w_sector} ({sector_weights[max_w_sector]:.1f}%)** มีสัดส่วนนำพอร์ต ถือว่ายอมรับได้สำหรับสายเน้นเติบโต (Growth)")
                        else:
                            st.success(f"🟢 **กระจายความเสี่ยงยอดเยี่ยม:** พอร์ตมีความสมดุล ไม่มีอุตสาหกรรมไหนครองสัดส่วนเกิน 30% ถือเป็นโครงสร้างพอร์ตระดับสถาบัน")
                            
                        if total_sim_return > (spy_ret + 5):
                            st.success(f"🌟 **Alpha แข็งแกร่งมาก:** พอร์ตจำลองนี้ทำผลงานชนะตลาด S&P 500 ถึง **{total_sim_return - spy_ret:+.2f}%** หุ้นที่คุณเลือกมามีศักยภาพสูงอย่างยิ่ง")
                        elif total_sim_return >= spy_ret:
                            st.info(f"🟡 **เกาะติดตลาด:** พอร์ตจำลองนี้ทำผลงานเกาะกลุ่มเดียวกับตลาด S&P 500 ({total_sim_return - spy_ret:+.2f}%) ให้ความผันผวนที่ไม่สูงจนเกินไป")
                        else:
                            st.error(f"📉 **ผลตอบแทนต่ำกว่าตลาด:** พอร์ตจำลองนี้แพ้ตลาด S&P 500 อยู่ **{total_sim_return - spy_ret:.2f}%** แนะนำให้ตัดหุ้นที่ผลงานติดลบหนักออก แล้วแทนที่ด้วยหุ้นชั้นนำกลุ่มอื่น")

                        st.markdown("---")
                        st.markdown("#### 💾 บันทึกโมเดลพอร์ตจำลองนี้ (Save Sandbox Model)")
                        c_save_sim1, c_save_sim2 = st.columns([7, 3])
                        with c_save_sim1: 
                            sim_name = st.text_input("📝 ตั้งชื่อพอร์ตจำลอง (เช่น: พอร์ตเน้นปันผล, พอร์ตเกษียณเสี่ยงต่ำ)", placeholder="พิมพ์ชื่อพอร์ตที่นี่...")
                        with c_save_sim2:
                            st.markdown("<br>", unsafe_allow_html=True)
                            if st.button("💾 บันทึกประวัติพอร์ตนี้", type="primary", use_container_width=True):
                                ticker_str = ",".join(selected_sim)
                                weight_str = ",".join([str(sim_weights[t]) for t in selected_sim])
                                new_sim = pd.DataFrame([{
                                    "Date": current_date,
                                    "Portfolio_Name": sim_name if sim_name else "Unnamed Portfolio",
                                    "Tickers": ticker_str,
                                    "Weights": weight_str,
                                    "Sim_Return": f"{total_sim_return:.2f}%",
                                    "Alpha": f"{total_sim_return - spy_ret:+.2f}%",
                                    "Note": ""
                                }])
                                st.session_state.sandbox_history = pd.concat([st.session_state.sandbox_history, new_sim], ignore_index=True)
                                save_df_to_sheet("Sandbox_History", st.session_state.sandbox_history)
                                st.success("✅ บันทึกพอร์ตจำลองสำเร็จ! ดูประวัติได้ที่ตารางด้านล่างครับ")
                                time.sleep(0.5)
                                st.rerun()
                                
                    except Exception as e:
                        st.error("เกิดข้อผิดพลาดชั่วคราวในการดึงข้อมูลหุ้นจำลอง กรุณากดปุ่ม 'ดึงข้อมูลเรียลไทม์เดี๋ยวนี้' ที่เมนูซ้ายมือเพื่อล้างความจำ แล้วลองอีกครั้งค่ะ")
        else:
            st.info("👈 กรุณาเลือกหุ้น หรือพิมพ์เพิ่มชื่อหุ้นที่คุณค้นหาเองในช่องขวามือ เพื่อเริ่มต้นจำลองพอร์ตได้เลยครับ")

        st.markdown("---")
        st.markdown("### 📚 ประวัติพอร์ตจำลองของฉัน (Saved Portfolios)")
        display_sim_df = st.session_state.sandbox_history.copy()
        if not display_sim_df.empty:
            display_sim_df.insert(0, "Select_Delete", False)
            ed_sim = st.data_editor(display_sim_df, num_rows="dynamic", use_container_width=True,
                column_config={
                    "Select_Delete": st.column_config.CheckboxColumn("🗑️ ลบทิ้ง", default=False),
                    "Date": "วันที่ประเมิน",
                    "Portfolio_Name": "ชื่อโมเดลพอร์ต",
                    "Tickers": "รายชื่อหุ้น",
                    "Weights": "สัดส่วน (%)",
                    "Sim_Return": "ผลตอบแทนคาดหวัง",
                    "Alpha": "ชนะตลาด (Alpha)",
                    "Note": "จดบันทึกย่อ"
                })
            
            if ed_sim["Select_Delete"].any():
                st.warning("⚠️ คุณได้ติ๊กเลือกพอร์ตจำลองที่ต้องการลบแล้ว กดปุ่มยืนยันด้านล่างครับ")
                if st.button("🗑️ ยืนยันการลบ", type="primary"):
                    st.session_state.sandbox_history = ed_sim[~ed_sim["Select_Delete"]].drop(columns=["Select_Delete"])
                    save_df_to_sheet("Sandbox_History", st.session_state.sandbox_history)
                    st.success("✅ ลบประวัติสำเร็จ!")
                    time.sleep(1)
                    st.rerun()
            else:
                updated_sim_df = ed_sim.drop(columns=["Select_Delete"])
                if not updated_sim_df.equals(st.session_state.sandbox_history):
                    st.session_state.sandbox_history = updated_sim_df.copy()
                    save_df_to_sheet("Sandbox_History", st.session_state.sandbox_history)
                    st.rerun()
        else:
            st.info("ยังไม่มีประวัติการจัดพอร์ตจำลองครับ เมื่อวิเคราะห์เสร็จแล้วให้กดบันทึกเพื่อดูประวัติตรงนี้ได้เลย")

import json
import time
import os
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
# 🎨 1. การตั้งค่าแบรนด์และหน้าเพจ (Custom Branding)
# ==========================================
logo_path = "strategic_hub_logo.png"

if os.path.exists(logo_path):
    browser_icon = Image.open(logo_path)
    st.set_page_config(page_title="Strategic Hub 4.14", page_icon=browser_icon, layout="wide")
else:
    st.set_page_config(page_title="Strategic Hub 4.14", page_icon="📈", layout="wide")

st.markdown("""
    <style>
    .stButton>button { border-radius: 12px; font-weight: bold; transition: all 0.3s ease; border: 1px solid #4CAF50; }
    .stButton>button:hover { transform: translateY(-2px); box-shadow: 0 6px 15px rgba(76, 175, 80, 0.4); border-color: #4CAF50; }
    .stButton>button[data-baseweb="button"] { border-radius: 12px; }
    .summary-box { padding: 20px; border-radius: 10px; margin-bottom: 20px; border-left: 5px solid; }
    div[data-testid="stMetricValue"] { padding-bottom: 0px; }
    .stSpinner > div > div { border-top-color: #deff9a !important; }
    [data-testid="stSidebar"] { background-color: #0e1117; }
    </style>
""", unsafe_allow_html=True)

tz_th = timezone(timedelta(hours=7))
current_date = datetime.now(tz_th).strftime("%d/%m/%Y")
current_time = datetime.now(tz_th).strftime("%H:%M:%S")

# ==========================================
# 2. 🔐 การเชื่อมต่อฐานข้อมูล
# ==========================================
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
        if col in df_clean.columns:
            df_clean[col] = pd.to_numeric(df_clean[col], errors='coerce').fillna(0.0)
    str_cols = ["Date", "Action", "Ticker", "Ref_Doc"]
    for col in str_cols:
        if col in df_clean.columns:
            df_clean[col] = df_clean[col].fillna("").astype(str).replace(["None", "nan", "<NA>", "NaN"], "")
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
    global sh
    try:
        ws = sh.worksheet(worksheet_name)
    except:
        sh = init_connection()
        ws = sh.worksheet(worksheet_name)
    try:
        ws.clear()
        clean_df = clean_df_types(df)
        data_list = [clean_df.columns.values.tolist()] + clean_df.values.tolist()
        ws.update(values=data_list, range_name='A1')
        return True
    except Exception as e:
        st.error(f"❌ เกิดข้อผิดพลาดขณะเขียนข้อมูลลง Cloud: {e}")
        return False

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
        return len(ws.col_values(1))
    except Exception as e:
        return "N/A"

visitor_count = log_visitor()

# ==========================================
# 3. 📊 ลอจิกการบัญชี (Professional Standard)
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
        ticker = str(row.get("Ticker", "")).strip().upper()
        p = float(row.get("Price", 0.0))
        s = float(row.get("Shares", 0.0))
        manual_amount = float(row.get("Amount_USD", 0.0))
        trade_value = p * s
        a = manual_amount if manual_amount > 0 and action not in ["ซื้อหุ้น (Buy)", "ขายหุ้น (Sell)"] else trade_value
        if action == "นำเงินออกนอกประเทศ (Outward)": cb += a; stat["outward"] += a
        elif action == "นำเงินเข้าประเทศไทย (Inward)": cb -= a; stat["inward"] += a
        elif action == "รับเงินปันผล (Dividend)": cb += a; stat["dividend"] += a
        elif action == "ซื้อหุ้น (Buy)" and ticker:
            cb -= trade_value; stat["bought"] += trade_value
            if ticker not in hld: hld[ticker] = {"shares": 0.0, "total_cost": 0.0}
            hld[ticker]["shares"] += s; hld[ticker]["total_cost"] += trade_value
        elif action == "ขายหุ้น (Sell)" and ticker:
            cb += trade_value; stat["sold"] += trade_value
            if ticker in hld and hld[ticker]["shares"] > 0:
                avg_cost = hld[ticker]["total_cost"] / hld[ticker]["shares"]
                cogs = avg_cost * s
                realized_pl = trade_value - cogs
                stat["realized_profit"] += realized_pl
                hld[ticker]["shares"] -= s; hld[ticker]["total_cost"] -= cogs
                old_ref = str(row.get("Ref_Doc", "")).replace("nan", "")
                if "P/L:" not in old_ref: df.at[idx, "Ref_Doc"] = f"P/L: ${realized_pl:.2f} | {old_ref}"
        r_bals.append(cb)
    df["Running_Balance"] = r_bals
    return df, cb, stat, r_bals, hld

@st.cache_data
def convert_df_to_csv(df):
    return df.to_csv(index=False).encode('utf-8-sig')

# ==========================================
# 4. 🌐 ดึงข้อมูลการเงิน & ระบบแปลภาษาไทย
# ==========================================
@st.cache_data(ttl=86400)
def translate_to_thai(text):
    if not text or text == 'N/A': return "ไม่มีข้อมูล"
    try:
        short_text = text[:350]
        if '.' in short_text:
            short_text = short_text.rsplit('.', 1)[0] + '.'
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=th&dt=t&q={urllib.parse.quote(short_text)}"
        res = requests.get(url, timeout=5)
        th_text = "".join([s[0] for s in res.json()[0]])
        return th_text
    except:
        return short_text + "..."

@st.cache_data(ttl=60)
def load_pro_data(ticker_symbol, tf):
    stgs = {"1D (รายวัน)": {"p": "6mo", "i": "1d"}, "1W (รายสัปดาห์)": {"p": "2y", "i": "1wk"}, "1M (รายเดือน)": {"p": "5y", "i": "1mo"}}
    p, i = stgs[tf]["p"], stgs[tf]["i"]
    try:
        s = yf.Ticker(ticker_symbol)
        df = s.history(period=p, interval=i).dropna(subset=['Close'])
        if df.empty: return pd.DataFrame(), {}, None, None
        
        info = s.info
        en_summary = info.get('longBusinessSummary', 'N/A')
        th_summary = translate_to_thai(en_summary)
        industry = info.get('industry', 'N/A')
        sector = info.get('sector', 'N/A')
        city = info.get('city', '')
        country = info.get('country', '')
        website = info.get('website', '#')
        
        market_signal = {"spy_trend": "N/A", "spy_price": 0.0, "vix": 0.0, "vix_ts": 0.0, "smart_money": "N/A"}
        try:
            spy = yf.Ticker("^GSPC").history(period=p, interval=i)
            if not spy.empty:
                df['RS'] = (df['Close'].pct_change(10) - spy['Close'].pct_change(10)) * 100
                spy_p = spy['Close'].iloc[-1]
                spy_ema50 = spy['Close'].ewm(span=50).mean().iloc[-1]
                market_signal["spy_price"] = float(spy_p)
                market_signal["spy_trend"] = "ขึ้น 📈" if spy_p > spy_ema50 else "ลง 📉"
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
        
        ps_v = float(info.get('priceToSalesTrailing12Months', 0) or 0)
        pe_v = float(info.get('trailingPE', 0) or 0)
        roe_v = float(info.get('returnOnEquity', 0) or 0)
        rev_v = float(info.get('revenueGrowth', 0) or 0)

        fund = {
            "ps_val": ps_v, "pe_val": pe_v, "roe_val": roe_v, "rev_val": rev_v,
            "ps": f"{ps_v:.2f}", 
            "pe": f"{pe_v:.2f}", 
            "roe": f"{roe_v*100:.2f}%",
            "rev_growth": f"{rev_v*100:.2f}%",
            "business_desc_th": th_summary,
            "industry": industry,
            "sector": sector,
            "location": f"{city}, {country}" if city else country,
            "website": website
        }
        
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
    if os.path.exists(logo_path):
        st.image(logo_path, use_container_width=True)
    else:
        st.title("🛡️ Strategic Hub")
    if st.button("🔄 ดึงข้อมูลเรียลไทม์เดี๋ยวนี้", use_container_width=True):
        st.cache_data.clear(); st.rerun()
    st.info(f"👁️ ยอดผู้เข้าชม: {visitor_count} ครั้ง")
    st.markdown("---")
    ticker = st.text_input("🔎 ชื่อหุ้น / ดัชนี", value="NVTS").upper()
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
            if pwd == st.secrets.get("app_password", "123456"): st.session_state["logged_in"] = True; st.rerun()
            else: st.error("❌ รหัสผิด")
    else:
        st.success("✅ โหมดเจ้าของพอร์ต")
        if st.button("🚪 ออกจากระบบ", use_container_width=True): st.session_state["logged_in"] = False; st.rerun()

holdings = {}
if st.session_state["logged_in"]:
    sorted_df, cb, l_stat, r_bals, holdings = calculate_stats(st.session_state.trade_ledger)
    st.session_state.trade_ledger = sorted_df

with st.spinner(f"⏳ กำลังประมวลผลข้อมูล..."):
    df, fund, matrix, market_signal = load_pro_data(ticker, tf_option)

tabs = ["📊 วิเคราะห์กราฟ (Analysis)", "💼 บัญชี (Cloud Sync)", "🧾 ภาษีสรรพากร"] if st.session_state["logged_in"] else ["📊 วิเคราะห์กราฟ (Analysis)"]
tab_list = st.tabs(tabs)

# ==========================================
# หน้า 1: วิเคราะห์กราฟ (กู้คืนส่วนวิเคราะห์เทรดเดอร์)
# ==========================================
with tab_list[0]:
    if not df.empty:
        st.markdown(f"## 📈 วิเคราะห์หุ้น: {ticker}")
        st.markdown(f"#### 📅 ข้อมูล ณ วันที่: <span style='color:#4CAF50'>{current_date}</span> | 🕒 อัปเดตล่าสุด: <span style='color:#4CAF50'>{current_time}</span>", unsafe_allow_html=True)
        
        # 1. ข้อมูลธุรกิจภาษาไทย
        with st.expander("🏢 ข้อมูลธุรกิจ (Company Profile)", expanded=True):
            st.markdown(f"**🇹🇭 สรุปธุรกิจ (ฉบับย่อ):**")
            st.info(f"{fund.get('business_desc_th', 'ไม่มีข้อมูล')}")
            c_b1, c_b2, c_b3 = st.columns(3)
            c_b1.markdown(f"**🏷️ อุตสาหกรรม:**<br><span style='color:#00E676;'>{fund.get('industry', 'N/A')}</span>", unsafe_allow_html=True)
            c_b2.markdown(f"**📍 ที่ตั้ง:**<br><span style='color:#00E676;'>{fund.get('location', 'N/A')}</span>", unsafe_allow_html=True)
            website = fund.get('website', '#')
            if website != '#': c_b3.markdown(f"**🌐 เว็บไซต์:**<br><a href='{website}' target='_blank' style='color:#82B1FF;'>คลิกดูเว็บไซต์บริษัท</a>", unsafe_allow_html=True)
            else: c_b3.markdown(f"**🌐 เว็บไซต์:**<br><span style='color:#82B1FF;'>ไม่มีข้อมูล</span>", unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("### 🌐 Market Signal (เรดาร์สแกนภาพรวมตลาด)")
        
        # 2. ตัวแปรสำหรับคำนวณและแสดงผล
        spy_t = market_signal.get("spy_trend", "N/A") if market_signal else "N/A"
        spy_p = market_signal.get("spy_price", 0.0) if market_signal else 0.0
        v_val = market_signal.get("vix", 0.0) if market_signal else 0.0
        vix_ts = market_signal.get("vix_ts", 0.0) if market_signal else 0.0
        sm_flow = market_signal.get("smart_money", "N/A") if market_signal else "N/A"

        last_p = df['Close'].iloc[-1]
        prev_p = df['Close'].iloc[-2] if len(df) > 1 else last_p
        rsi_val = df['RSI'].iloc[-1]
        is_uptrend = last_p > df['E50'].iloc[-1]
        is_bullish_macd = df['MACD'].iloc[-1] > df['Sig'].iloc[-1]
        is_market_good = "ขึ้น" in spy_t and (0 < v_val < 25)

        # 3. กล่อง Market Signal
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("ตลาดโลก (S&P 500)", f"{spy_p:,.2f}" if spy_p > 0 else "N/A", spy_t if spy_p > 0 else None, delta_color="normal" if "ขึ้น" in spy_t else "inverse" if "ลง" in spy_t else "off")
        vix_stat = "Risk ON" if 0 < v_val < 20 else "Neutral" if 0 < v_val < 30 else "Panic"
        m2.metric("ความกลัว (VIX)", f"{v_val:.2f}" if v_val > 0 else "N/A", vix_stat if v_val > 0 else None, delta_color="normal" if 0 < v_val < 25 else "inverse" if v_val >= 25 else "off")
        ts_label = "🟢 สงบ" if 0 < vix_ts < 1 else "🔴 ตระหนก" if vix_ts > 0 else "N/A"
        m3.metric("โครงสร้าง (VIX/VIX3M)", f"{vix_ts:.2f}" if vix_ts > 0 else "N/A", ts_label if vix_ts > 0 else None, delta_color="normal" if 0 < vix_ts < 1 else "inverse" if vix_ts >= 1 else "off")
        m4.metric("เงินใหญ่ (HYG/IEF)", "Credit Flow", sm_flow if sm_flow != "N/A" else None, delta_color="normal" if "ON" in sm_flow else "inverse" if "OFF" in sm_flow else "off")

        # 4. กล่อง ทัศนะจากเทรดเดอร์มือหนึ่ง (ที่กู้คืนมา)
        if is_market_good and is_uptrend and is_bullish_macd and rsi_val < 70:
            rec, color = "STRONG BUY / HOLD", "#00E676"
            msg = f"**'จังหวะน้ำขึ้นต้องรีบตัก'** - ตลาดโลกเอื้ออำนวย และ {ticker} กำลังอยู่ในรอบขาขึ้นเต็มตัว กราฟมีโมเมนตัมเชิงบวกชัดเจน แนะนำให้ทยอยสะสม (Buy on Dip) หรือถือรันเทรนด์ต่อเพื่อทำกำไรคำโตครับ"
        elif is_uptrend and rsi_val >= 70:
            rec, color = "HOLD / TAKE PROFIT", "#FFD600"
            msg = f"**'ระวังความร้อนแรง'** - หุ้นยังเป็นขาขึ้นแข็งแกร่ง แต่เข้าเขต Overbought มืออาชีพจะไม่ไล่ราคาตรงนี้ แนะนำให้ถือรันเทรนด์โดยยกจุดตัดขาดทุนตามขึ้นมา หรือแบ่งขายทำกำไรบางส่วนครับ"
        elif not is_uptrend and is_bullish_macd and rsi_val < 35:
            rec, color = "SPECULATIVE BUY", "#2962FF"
            msg = f"**'ลุ้นรีบาวด์ในโซนล่าง'** - หุ้นยังอยู่ในเทรนด์ขาลง แต่เริ่มมีสัญญาณแรงซื้อกลับ เหมาะสำหรับสายซิ่งที่ต้องการเก็งกำไรระยะสั้น แต่ต้องตั้งจุด Stop loss ให้รัดกุมครับ"
        elif not is_uptrend:
            rec, color = "AVOID / WAIT", "#FF5252"
            msg = f"**'รักษาเงินต้นคือหัวใจ'** - ภาพรวมเสียทรงขาขึ้นและหลุดเส้นค่าเฉลี่ยสำคัญ โมเมนตัมดูอ่อนแอ แนะนำให้ทับมือรอดูสถานการณ์ (Wait & See) ไปก่อนครับ"
        else:
            rec, color = "NEUTRAL / SIDEWAY", "#B0BEC5"
            msg = f"**'ตลาดรอเลือกทาง'** - กราฟกำลังแกว่งตัวออกข้าง (Sideway) สัญญาณขัดแย้งกัน แนะนำให้เทรดสั้นๆ ในกรอบ (แนวรับ-แนวต้าน) หรือรอดูจนกว่าราคาจะเลือกทิศทางครับ"

        st.markdown(f"""
        <div style="background-color: #1E1E1E; border: 1px solid #333; border-left: 8px solid {color}; padding: 25px; border-radius: 12px; margin-top: 20px; margin-bottom: 20px; box-shadow: 0 4px 15px rgba(0,0,0,0.2);">
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

        # 5. กู้คืน Harmonic Matrix
        rs_val = df['RS'].iloc[-1]
        rs_t = f" | **Relative Strength:** {'🟢 ชนะตลาด' if rs_val > 0 else '🔴 อ่อนแอกว่าตลาด'} ({rs_val:.2f}%)" if not np.isnan(rs_val) else ""
        if matrix: st.info(f"🔮 **ทิศทาง {tf_option}:** {matrix['tr']} | **เป้าหมาย (Harmonic Matrix):** {matrix['l']:,.2f} - {matrix['u']:,.2f} {rs_t}")
        
        is_speculative = (fund.get('pe_val', 0) <= 0) or (fund.get('roe_val', 0) < 0)

        c_l, c_r = st.columns([7, 3])
        with c_l:
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name="Price"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['E50'], line=dict(color='#FF6D00', width=2), name="EMA 50"), row=1, col=1)
            
            actual_cost = b_p
            if st.session_state["logged_in"] and holdings.get(ticker, {}).get("shares", 0) > 0.001:
                actual_cost = holdings[ticker]["total_cost"] / holdings[ticker]["shares"]
            if actual_cost > 0: fig.add_hline(y=actual_cost, line_dash="dash", line_color="cyan", annotation_text="ต้นทุนเฉลี่ย", row=1, col=1)
            
            fig.add_trace(go.Bar(x=df.index, y=df['Hist'], marker_color=['#00E676' if v >= 0 else '#FF5252' for v in df['Hist']], name="MACD"), row=2, col=1)
            fig.update_layout(template="plotly_dark", height=600, margin=dict(l=0,r=0,t=0,b=0), showlegend=False)
            fig.update_xaxes(rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)
            
            st.subheader("📊 ข้อมูลพื้นฐาน")
            f1, f2, f3, f4 = st.columns(4)
            f1.metric("P/S Ratio", fund.get('ps','N/A'))
            f2.metric("P/E Ratio", fund.get('pe','N/A'))
            f3.metric("ROE", fund.get('roe','N/A'))
            f4.metric("Rev Growth (YoY)", fund.get('rev_growth','N/A'))
            
            if is_speculative:
                st.markdown("""
                <div style="background-color: rgba(255, 82, 82, 0.1); border-left: 5px solid #FF5252; padding: 10px; border-radius: 5px; margin-top: 10px;">
                    <span style="color: #FF5252;">⚠️ <b>Warning (High Speculation):</b> หุ้นตัวนี้ยังขาดทุน (P/E=0) หรือ ROE ติดลบ จัดเป็นหุ้นเก็งกำไรความเสี่ยงสูง ระบบจะปรับลดเพดานเข้าซื้อลงครึ่งหนึ่งอัตโนมัติ</span>
                </div>
                """, unsafe_allow_html=True)
        
        with c_r:
            p_diff = last_p - prev_p
            p_pct = (p_diff / prev_p) * 100 if prev_p > 0 else 0
            st.metric("ราคาปัจจุบัน", f"${last_p:,.2f}", f"{p_diff:,.2f} ({p_pct:,.2f}%)")
            st.markdown(f"<div style='margin-top: -15px; margin-bottom: 20px; font-size: 0.9em; color: #a0aab2;'>📅 {current_date} &nbsp; 🕒 {current_time} น.</div>", unsafe_allow_html=True)
            
            if actual_cost > 0:
                pl = ((last_p - actual_cost) / actual_cost) * 100
                st.write(f"**กำไร/ขาดทุนอ้างอิง:** {pl:.2f}%")
                sl = df['E50'].iloc[-1] * 0.99 if b_p == 0 else actual_cost * 0.92
                st.error(f"🛡

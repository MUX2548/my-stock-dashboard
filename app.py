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
    st.set_page_config(page_title="Strategic Hub 4.13", page_icon=browser_icon, layout="wide")
else:
    st.set_page_config(page_title="Strategic Hub 4.13", page_icon="📈", layout="wide")

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
@st.cache_data(ttl=86400) # จำคำแปลไว้ 1 วันเต็มๆ จะได้โหลดเร็ว
def translate_to_thai(text):
    if not text or text == 'N/A': return "ไม่มีข้อมูล"
    try:
        # ตัดประโยคให้สั้นลง เอาแค่ประมาณ 350 ตัวอักษร เพื่อให้อ่านง่าย
        short_text = text[:350]
        if '.' in short_text:
            short_text = short_text.rsplit('.', 1)[0] + '.'
        
        # ส่งไปแปลที่ Google Translate
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=th&dt=t&q={urllib.parse.quote(short_text)}"
        res = requests.get(url, timeout=5)
        th_text = "".join([s[0] for s in res.json()[0]])
        return th_text
    except:
        return short_text + "..." # ถ้าแปลไม่สำเร็จ ให้แสดงอังกฤษสั้นๆ แทน

@st.cache_data(ttl=60)
def load_pro_data(ticker_symbol, tf):
    stgs = {"1D (รายวัน)": {"p": "6mo", "i": "1d"}, "1W (รายสัปดาห์)": {"p": "2y", "i": "1wk"}, "1M (รายเดือน)": {"p": "5y", "i": "1mo"}}
    p, i = stgs[tf]["p"], stgs[tf]["i"]
    try:
        s = yf.Ticker(ticker_symbol)
        df = s.history(period=p, interval=i).dropna(subset=['Close'])
        if df.empty: return pd.DataFrame(), {}, None, None
        
        # 🏢 ดึงข้อมูลบริษัท และแปลภาษาไทย
        info = s.info
        en_summary = info.get('longBusinessSummary', 'N/A')
        th_summary = translate_to_thai(en_summary) # เรียกใช้ตัวแปลภาษา
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

        df['E20'] = df['Close'].ewm(span=20).mean()
        df['E50'] = df['Close'].ewm(span=50).mean()
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14).mean()
        df['RSI'] = 100 - (100 / (1 + gain/loss))
        df['MACD'] = df['Close'].ewm(span=12).mean() - df['Close'].ewm(span=26).mean()
        df['Sig'] = df['MACD'].ewm(span=9).mean()
        df['Hist'] = df['MACD'] - df['Sig']
        if len(df) > 1:
            y, x = df['Close'].values, np.arange(len(df['Close'].values))
            slope, intercept = np.polyfit(x, y, 1)
            df['Trendline'] = slope * x + intercept
        else: df['Trendline'] = np.nan
        
        fund = {
            "ps": f"{info.get('priceToSalesTrailing12Months', 0) or 0:.2f}", 
            "pe": f"{info.get('trailingPE', 0) or 0:.2f}", 
            "roe": f"{(info.get('returnOnEquity', 0) or 0)*100:.2f}%",
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

with st.spinner(f"⏳ กำลังประมวลผลข้อมูล... (ระบบแปลภาษาอาจใช้เวลา 1-2 วินาที)"):
    df, fund, matrix, market_signal = load_pro_data(ticker, tf_option)

tabs = ["📊 วิเคราะห์กราฟ (Analysis)", "💼 บัญชี (Cloud Sync)", "🧾 ภาษีสรรพากร"] if st.session_state["logged_in"] else ["📊 วิเคราะห์กราฟ (Analysis)"]
tab_list = st.tabs(tabs)

# ==========================================
# หน้า 1: วิเคราะห์กราฟ (UI ข้อมูลธุรกิจใหม่)
# ==========================================
with tab_list[0]:
    if not df.empty:
        st.markdown(f"## 📈 วิเคราะห์หุ้น: {ticker}")
        st.markdown(f"#### 📅 ข้อมูล ณ วันที่: <span style='color:#4CAF50'>{current_date}</span> | 🕒 อัปเดตล่าสุด: <span style='color:#4CAF50'>{current_time}</span>", unsafe_allow_html=True)
        
        # 🏢 UI ข้อมูลธุรกิจ (รูปแบบใหม่ อ่านง่าย ไม่เป็นบล็อก)
        with st.expander("🏢 ข้อมูลธุรกิจ (Company Profile)", expanded=True):
            st.markdown(f"**🇹🇭 สรุปธุรกิจ (ฉบับย่อ):**")
            st.info(f"{fund.get('business_desc_th', 'ไม่มีข้อมูล')}")
            
            c_b1, c_b2, c_b3 = st.columns(3)
            c_b1.markdown(f"**🏷️ อุตสาหกรรม:**<br><span style='color:#00E676;'>{fund.get('industry', 'N/A')}</span>", unsafe_allow_html=True)
            c_b2.markdown(f"**📍 ที่ตั้ง:**<br><span style='color:#00E676;'>{fund.get('location', 'N/A')}</span>", unsafe_allow_html=True)
            
            website = fund.get('website', '#')
            if website != '#':
                c_b3.markdown(f"**🌐 เว็บไซต์:**<br><a href='{website}' target='_blank' style='color:#82B1FF;'>คลิกดูเว็บไซต์บริษัท</a>", unsafe_allow_html=True)
            else:
                c_b3.markdown(f"**🌐 เว็บไซต์:**<br><span style='color:#82B1FF;'>ไม่มีข้อมูล</span>", unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("### 🌐 Market Signal")
        m1, m2, m3 = st.columns(3)
        m1.metric("ตลาดโลก (S&P 500)", f"{market_signal['spy_price']:,.2f}", market_signal['spy_trend'])
        m2.metric("ความกลัว (VIX)", f"{market_signal['vix']:.2f}", "Risk ON" if market_signal['vix'] < 25 else "Panic")
        with m3:
            st.markdown("**AI Action Plan:**")
            if "ขึ้น" in market_signal['spy_trend'] and market_signal['vix'] < 25: st.success("🚀 ตลาดเป็นใจ ทยอยสะสม")
            else: st.warning("⚠️ ตลาดผันผวน เน้นตั้งรับ")

        c_l, c_r = st.columns([7, 3])
        with c_l:
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name="Price"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['E50'], line=dict(color='#FF6D00', width=2), name="EMA 50"), row=1, col=1)
            fig.add_trace(go.Bar(x=df.index, y=df['Hist'], marker_color=['#00E676' if v >= 0 else '#FF5252' for v in df['Hist']], name="MACD"), row=2, col=1)
            fig.update_layout(template="plotly_dark", height=600, margin=dict(l=0,r=0,t=0,b=0), showlegend=False)
            fig.update_xaxes(rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)
            
            st.subheader("📊 ข้อมูลพื้นฐาน")
            f1, f2, f3 = st.columns(3)
            f1.metric("P/S Ratio", fund['ps']); f2.metric("P/E Ratio", fund['pe']); f3.metric("ROE", fund['roe'])
        
        with c_r:
            last_p = df['Close'].iloc[-1]
            prev_p = df['Close'].iloc[-2] if len(df) > 1 else last_p
            p_diff = last_p - prev_p
            p_pct = (p_diff / prev_p) * 100 if prev_p > 0 else 0
            st.metric("ราคาปัจจุบัน", f"${last_p:,.2f}", f"{p_diff:,.2f} ({p_pct:,.2f}%)")
            
            actual_cost = b_p
            if st.session_state["logged_in"] and holdings.get(ticker, {}).get("shares", 0) > 0.001:
                actual_cost = holdings[ticker]["total_cost"] / holdings[ticker]["shares"]
            
            if actual_cost > 0:
                pl = ((last_p - actual_cost) / actual_cost) * 100
                st.write(f"**กำไร/ขาดทุนของคุณ:** {pl:.2f}%")
                sl = actual_cost * 0.92
                st.error(f"🛡️ **จุดหนี (Stop Loss): ${sl:.2f}**")
            
            st.markdown("---")
            st.subheader("🤖 สรุปทางเทคนิค")
            st.write(f"**เทรนด์:** {'🟢 ขาขึ้น' if last_p > df['E50'].iloc[-1] else '🔴 ขาลง'}")
            st.write(f"**แรงซื้อ:** {'🟢 ได้เปรียบ' if df['MACD'].iloc[-1] > df['Sig'].iloc[-1] else '🔴 อ่อนแอ'}")
            st.write(f"**RSI:** {df['RSI'].iloc[-1]:.2f}")
    else:
        st.warning(f"❌ ไม่พบข้อมูลหุ้น '{ticker}'")

# ==========================================
# หน้า 2: บัญชีและพอร์ตโฟลิโอ
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
        
        st.info("💡 **Tips จากนักบัญชี:** ตอนซื้อ/ขายหุ้น กรอกแค่ 'ราคา' และ 'จำนวนหุ้น' ระบบจะคำนวณจำนวนเงินและอัปเดตยอดยกมาให้อัตโนมัติครับ")
        ed_l = st.data_editor(st.session_state.trade_ledger, num_rows="dynamic", use_container_width=True,
            column_config={
                "Date": "วันที่ (DD/MM/YYYY)",
                "Action": st.column_config.SelectboxColumn("ประเภท", options=["นำเงินออกนอกประเทศ (Outward)", "นำเงินเข้าประเทศไทย (Inward)", "ซื้อหุ้น (Buy)", "ขายหุ้น (Sell)", "รับเงินปันผล (Dividend)"], required=True),
                "Ticker": "ชื่อหุ้น",
                "Price": st.column_config.NumberColumn("ราคา ($)", format="%.4f", step=0.0001),
                "Shares": st.column_config.NumberColumn("จำนวนหุ้น", format="%.4f", step=0.0001),
                "Amount_USD": st.column_config.NumberColumn("จำนวนเงินสุทธิ ($)", format="%.2f", step=0.01),
                "Running_Balance": st.column_config.NumberColumn("ยอดเงินสดคงเหลือ ($)", disabled=True, format="%.2f"), 
                "FX_Rate": st.column_config.NumberColumn("เรทเงิน", format="%.4f", step=0.0001), 
                "WHT_USD": st.column_config.NumberColumn("ภาษีหักฯ ($)", format="%.2f", step=0.01), 
                "Ref_Doc": st.column_config.TextColumn("หมายเหตุ (กำไร/ขาดทุน)")
            })
        if not ed_l.equals(st.session_state.trade_ledger):
            ed_l = clean_df_types(ed_l)
            sorted_ed_l, _, _, n_rb, _ = calculate_stats(ed_l)
            st.session_state.trade_ledger = sorted_ed_l; st.rerun()
        if st.button("💾 บันทึกข้อมูลบัญชีขึ้น Cloud", type="primary", use_container_width=True):
            if save_df_to_sheet("Ledger", st.session_state.trade_ledger):
                st.success("บันทึกสำเร็จ! โครงสร้างบัญชีถูกต้องตามมาตรฐาน 100%")
                time.sleep(1)
                st.rerun()

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

# ==========================================
# หน้า 3: ภาษีสรรพากร (Tax Accountant Logic)
# ==========================================
    with tab_list[2]:
        t1, t2 = st.columns([8, 2])
        t1.subheader("🧾 ระบบประเมินภาษีสรรพากร ภ.ง.ด. 90")
        
        st.info("💡 **หลักการภาษีใหม่:** การนำเงินกลับไทย (Inward) จะถูกหักจาก 'เงินต้นสะสม' ก่อน หากหักเงินต้นหมดแล้ว ยอดที่นำกลับหลังจากนั้นจึงจะถือเป็น 'กำไรที่ต้องเสียภาษี' (ส่วนเงินปันผลถือเป็นรายได้ที่ต้องเสียภาษี 100%)")
        
        tax_idx = st.session_state.trade_ledger['Action'].isin(["นำเงินออกนอกประเทศ (Outward)", "นำเงินเข้าประเทศไทย (Inward)", "รับเงินปันผล (Dividend)"])
        tax_v = st.session_state.trade_ledger[tax_idx].copy()
        
        tax_v["Out_USD"] = np.where(tax_v["Action"] == "นำเงินออกนอกประเทศ (Outward)", tax_v["Amount_USD"], 0.0)
        tax_v["In_USD"] = np.where(tax_v["Action"].isin(["นำเงินเข้าประเทศไทย (Inward)", "รับเงินปันผล (Dividend)"]), tax_v["Amount_USD"], 0.0)
        tax_v["FX_Rate"] = pd.to_numeric(tax_v["FX_Rate"], errors='coerce').fillna(0.0)
        tax_v["WHT_USD"] = pd.to_numeric(tax_v["WHT_USD"], errors='coerce').fillna(0.0)
        tax_v["Out_THB"] = tax_v["Out_USD"] * tax_v["FX_Rate"]
        tax_v["In_THB"] = tax_v["In_USD"] * tax_v["FX_Rate"]
        
        capital_pool = 0.0
        taxable_gains_thb = []
        running_bals = []

        for i, r in tax_v.iterrows():
            action = r['Action']
            out_thb = r['Out_THB']
            in_thb = r['In_THB']

            if action == "นำเงินออกนอกประเทศ (Outward)":
                capital_pool += out_thb
                taxable_gains_thb.append(0.0)
            elif action == "นำเงินเข้าประเทศไทย (Inward)":
                capital_pool -= in_thb
                if capital_pool < 0:
                    taxable_gains_thb.append(abs(capital_pool))
                    capital_pool = 0.0
                else:
                    taxable_gains_thb.append(0.0)
            elif action == "รับเงินปันผล (Dividend)":
                taxable_gains_thb.append(in_thb)
            else:
                taxable_gains_thb.append(0.0)

            running_bals.append(capital_pool)

        tax_v['Taxable_Gain_THB'] = taxable_gains_thb
        tax_v['Balance_THB'] = running_bals

        csv_tax = convert_df_to_csv(tax_v)
        t2.download_button(label="📥 โหลดตารางภาษี (Excel)", data=csv_tax, file_name=f"Tax_Report_{datetime.now().strftime('%Y%m%d')}.csv", mime='text/csv', use_container_width=True)
        
        ed_t = st.data_editor(tax_v, use_container_width=True, num_rows="fixed",
            column_order=["Date", "Out_USD", "In_USD", "FX_Rate", "Out_THB", "In_THB", "Balance_THB", "Taxable_Gain_THB", "WHT_USD"],
            column_config={
                "Date": st.column_config.Column("วันที่", disabled=True), 
                "Out_USD": st.column_config.NumberColumn("โอนออก ($)", disabled=True), 
                "In_USD": st.column_config.NumberColumn("นำเข้า/ปันผล ($)", disabled=True), 
                "FX_Rate": st.column_config.NumberColumn("เรทเงิน (บาท/$)", format="%.4f", step=0.0001), 
                "Out_THB": st.column_config.NumberColumn("โอนออก (฿)", disabled=True), 
                "In_THB": st.column_config.NumberColumn("นำเข้า (฿)", disabled=True), 
                "Balance_THB": st.column_config.NumberColumn("สระเงินต้นคงเหลือ (฿)", disabled=True),
                "Taxable_Gain_THB": st.column_config.NumberColumn("ส่วนกำไรที่ต้องเสียภาษี (฿)", disabled=True),
                "WHT_USD": st.column_config.NumberColumn("ภาษีหัก ตปท. ($)", format="%.2f", step=0.01)
            })
            
        if not ed_t[["FX_Rate", "WHT_USD"]].equals(tax_v[["FX_Rate", "WHT_USD"]]):
            ed_t = clean_df_types(ed_t)
            st.session_state.trade_ledger.loc[tax_idx, "FX_Rate"] = ed_t["FX_Rate"].values
            st.session_state.trade_ledger.loc[tax_idx, "WHT_USD"] = ed_t["WHT_USD"].values
            st.rerun()
            
        if st.button("💾 บันทึกเรทเงินและภาษีลง Cloud", type="primary", use_container_width=True): 
            if save_df_to_sheet("Ledger", st.session_state.trade_ledger):
                st.success("บันทึกสำเร็จ!")
                time.sleep(1)
                st.rerun()

        st.markdown("---")
        c1, c2, c3 = st.columns(3)
        with c1: 
            tax_year_str = st.selectbox("📅 เลือกปีภาษีสำหรับคำนวณ", ["2567 (2024)", "2568 (2025)", "2569 (2026)"])
            selected_year = tax_year_str.split("(")[1][:4] 
        with c2: is_resident = st.radio("อาศัยอยู่ในไทยเกิน 180 วันในปีนั้น?", ["เกิน 180 วัน", "ไม่ถึง 180 วัน"])
        with c3: other_income = st.number_input("รายได้ประจำปีอื่นๆ (บาท)", min_value=0.0, value=500000.0, step=50000.0)

        tax_v_current_year = tax_v[tax_v['Date'].str.endswith(selected_year)].copy()
        
        sum_out_thb_yr = tax_v_current_year["Out_THB"].sum()
        sum_in_thb_yr = tax_v_current_year["In_THB"].sum()
        net_tax_gain_yr = tax_v_current_year["Taxable_Gain_THB"].sum()
        sum_wht_thb_yr = (tax_v_current_year["WHT_USD"] * tax_v_current_year["FX_Rate"]).sum()

        st.markdown(f"#### 📊 สรุปยอดเงินของปีภาษี {selected_year} เท่านั้น")
        cf1, cf2, cf3 = st.columns(3)
        cf1.metric("📤 ยอดโอนออกปีนี้", f"฿{sum_out_thb_yr:,.2f}")
        cf2.metric("📥 ยอดนำกลับ/ปันผลปีนี้", f"฿{sum_in_thb_yr:,.2f}")
        cf3.metric("🚨 กำไรที่ต้องเสียภาษีปีนี้", f"฿{net_tax_gain_yr:,.2f}", "คำนวณหลังหักเงินต้นสะสมแล้ว", delta_color="inverse")

        st.markdown("---")
        with st.expander("📝 บันทึกค่าลดหย่อนส่วนบุคคล (ตามเกณฑ์สรรพากร)", expanded=True):
            col_d1, col_d2 = st.columns(2)
            spouse_deduction = col_d1.checkbox("มีคู่สมรส (ไม่มีรายได้)")
            children_count = col_d2.number_input("จำนวนบุตร (คนละ 30,000)", min_value=0, step=1)
            c_inv1, c_inv2, c_inv3 = st.columns(3)
            life_ins = c_inv1.number_input("เบี้ยประกันชีวิต (Max 100k)", min_value=0.0, step=5000.0)
            health_ins = c_inv2.number_input("เบี้ยประกันสุขภาพ (Max 25k)", min_value=0.0, step=5000.0)
            pvd = c_inv3.number_input("กองทุน PVD / กบข.", min_value=0.0, step=5000.0)
            ssf = c_inv1.number_input("ซื้อ SSF", min_value=0.0, step=5000.0)
            rmf = c_inv2.number_input("ซื้อ RMF", min_value=0.0, step=5000.0)
            donate = c_inv3.number_input("เงินบริจาค", min_value=0.0, step=1000.0)
            
        total_deductions = min(other_income * 0.5, 100000.0) + 60000.0 + (60000.0 if spouse_deduction else 0.0) + (children_count * 30000.0) + min(life_ins + min(health_ins, 25000.0), 100000.0) + min(ssf + rmf + pvd, 500000.0) + donate
        
        if st.button(f"📊 ประเมินภาษีสุทธิ ภ.ง.ด. 90 ประจำปี {selected_year}", type="primary", use_container_width=True):
            if "ไม่ถึง" in is_resident: 
                st.success("🎉 ได้รับยกเว้นภาษีต่างประเทศ (เนื่องจากอาศัยในไทยไม่ถึง 180 วันในปีภาษีนั้น)")
            elif net_tax_gain_yr <= 0: 
                st.success(f"🎉 ในปี {selected_year} คุณยังไม่มีส่วนกำไรที่ถูกดึงกลับเข้าประเทศ (ดึงกลับเฉพาะเงินต้น) จึงไม่ต้องนำมาคำนวณรวมเพื่อเสียภาษีครับ")
            else:
                net_inc = max(0, (other_income + net_tax_gain_yr) - total_deductions)
                net_inc_without = max(0, other_income - total_deductions)
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
                final_tax = max(0, tax_raw - sum_wht_thb_yr)
                
                st.subheader(f"ผลการประเมิน ภ.ง.ด. 90 (ประจำปี {selected_year})")
                r1, r2 = st.columns(2)
                r1.metric("ภาษีที่เกิดจากพอร์ต ตปท.", f"฿{tax_raw:,.2f}")
                r2.metric(f"🚨 ภาษีที่ต้องจ่ายเพิ่มจริง (หักเครดิต ตปท. ฿{sum_wht_thb_yr:,.2f} แล้ว)", f"฿{final_tax:,.2f}")

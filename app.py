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
# 1. ตั้งค่าหน้าเพจ & ตกแต่ง UI/UX (Original Style)
# ==========================================
st.set_page_config(page_title="Strategic Portfolio Ecosystem 4.10", page_icon="📈", layout="wide")

st.markdown("""
    <style>
    .stButton>button { border-radius: 12px; font-weight: bold; transition: all 0.3s ease; border: 1px solid #4CAF50; }
    .stButton>button:hover { transform: translateY(-2px); box-shadow: 0 6px 15px rgba(76, 175, 80, 0.4); border-color: #4CAF50; }
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
    except:
        df = pd.DataFrame(columns=["Date", "Action", "Ticker", "Price", "Shares", "Amount_USD", "Running_Balance", "FX_Rate", "WHT_USD", "Ref_Doc"])
    
    df = clean_df_types(df)
    if not df.empty and "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], format="%d/%m/%Y", errors="coerce").dt.strftime("%d/%m/%Y").replace("NaT", "")
    return df

def save_df_to_sheet(worksheet_name, df):
    try:
        ws = sh.worksheet(worksheet_name)
        ws.clear()
        clean_df = clean_df_types(df)
        data_list = [clean_df.columns.values.tolist()] + clean_df.values.tolist()
        ws.update(values=data_list, range_name='A1')
        return True
    except Exception as e:
        st.error(f"❌ บันทึกไม่สำเร็จ: {e}")
        return False

# ==========================================
# 3. 🧮 ลอจิกการคำนวณ (Professional Sorting)
# ==========================================
def calculate_stats(df_input):
    df = clean_df_types(df_input)
    if not df.empty and "Date" in df.columns:
        df["Date_DT"] = pd.to_datetime(df["Date"], format="%d/%m/%Y", errors='coerce')
        df = df.sort_values(by="Date_DT").drop(columns=["Date_DT"]).reset_index(drop=True)

    cb = 0.0
    stat = {"outward": 0.0, "inward": 0.0, "bought": 0.0, "sold": 0.0, "dividend": 0.0, "realized_profit": 0.0}
    r_bals, hld = [], {}
    
    for _, row in df.iterrows():
        action, ticker = str(row["Action"]), str(row["Ticker"]).upper()
        p, s, a = row["Price"], row["Shares"], row["Amount_USD"]
        
        if action == "นำเงินออกนอกประเทศ (Outward)": cb += a; stat["outward"] += a
        elif action == "นำเงินเข้าประเทศไทย (Inward)": cb -= a; stat["inward"] += a
        elif action == "รับเงินปันผล (Dividend)": cb += a; stat["dividend"] += a
        elif action == "กำไรจากการขายหุ้น (Profit)": cb += a
        elif action == "ซื้อหุ้น (Buy)" and ticker:
            cb -= (p*s); stat["bought"] += (p*s)
            if ticker not in hld: hld[ticker] = {"shares": 0.0, "total_cost": 0.0}
            hld[ticker]["shares"] += s; hld[ticker]["total_cost"] += (p*s)
        elif action == "ขายหุ้น (Sell)" and ticker:
            cb += (p*s); stat["sold"] += (p*s)
            if ticker in hld and hld[ticker]["shares"] > 0:
                avg = hld[ticker]["total_cost"] / hld[ticker]["shares"]
                stat["realized_profit"] += (p*s) - (avg * s)
                hld[ticker]["shares"] -= s; hld[ticker]["total_cost"] -= (avg * s)
        r_bals.append(cb)
    df["Running_Balance"] = r_bals
    return df, cb, stat, hld

# ==========================================
# 4. 🌐 Data Services (Batch Processing)
# ==========================================
@st.cache_data(ttl=60)
def load_pro_data(ticker_symbol, tf):
    stgs = {"1D (รายวัน)": {"p": "6mo", "i": "1d"}, "1W (รายสัปดาห์)": {"p": "2y", "i": "1wk"}, "1M (รายเดือน)": {"p": "5y", "i": "1mo"}}
    p, i = stgs[tf]["p"], stgs[tf]["i"]
    try:
        s = yf.Ticker(ticker_symbol)
        df = s.history(period=p, interval=i).dropna(subset=['Close'])
        if df.empty: return pd.DataFrame(), {}, None, None
        
        spy = yf.Ticker("^GSPC").history(period=p, interval=i)
        spy_trend, spy_p, vix_v = "N/A", 0.0, 20.0
        if not spy.empty:
            df['RS'] = (df['Close'].pct_change(10) - spy['Close'].pct_change(10)) * 100
            spy_p = spy['Close'].iloc[-1]
            spy_trend = "ขึ้น 📈" if spy_p > spy['Close'].ewm(span=50).mean().iloc[-1] else "ลง 📉"
        try: vix_v = yf.Ticker("^VIX").history(period="1d")['Close'].iloc[-1]
        except: pass

        df['E20'], df['E50'] = df['Close'].ewm(span=20).mean(), df['Close'].ewm(span=50).mean()
        df['RSI'] = 100 - (100 / (1 + (df['Close'].diff().where(df['Close'].diff() > 0, 0).ewm(alpha=1/14).mean() / -df['Close'].diff().where(df['Close'].diff() < 0, 0).ewm(alpha=1/14).mean())))
        df['MACD'] = df['Close'].ewm(span=12).mean() - df['Close'].ewm(span=26).mean()
        df['Sig'] = df['MACD'].ewm(span=9).mean()
        df['Hist'] = df['MACD'] - df['Sig']
        df['Vol_SMA'] = df['Volume'].rolling(window=20).mean()
        
        if len(df) > 1:
            y = df['Close'].values
            x = np.arange(len(y))
            slope, intercept = np.polyfit(x, y, 1)
            df['Trendline'] = slope * x + intercept

        last = df['Close'].iloc[-1]
        v = df['Close'].pct_change().tail(14).std()
        mat = {"l": last * (1 - v*0.5), "u": last * (1 + v*1.0), "tr": "ขึ้น 📈" if last > df['E50'].iloc[-1] else "ลง 📉"}
        
        return df, s.info, mat, {"spy_trend": spy_trend, "spy_price": spy_p, "vix": vix_v}
    except: return pd.DataFrame(), {}, None, None

@st.cache_data(ttl=60)
def get_batch_prices(tickers):
    if not tickers: return {}
    try:
        data = yf.download(tickers, period="1d", group_by='ticker', progress=False)
        return {t: data[t]['Close'].iloc[-1] if len(tickers)>1 else data['Close'].iloc[-1] for t in tickers}
    except: return {}

@st.cache_data(ttl=60)
def get_live_fx():
    try: return yf.Ticker("USDTHB=X").history(period="1d")['Close'].iloc[-1]
    except: return 35.0

# ==========================================
# 5. UI Logic
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
    
    st.markdown("---")
    st.subheader("🧮 เครื่องมือคำนวณ (Public)")
    t_cap = st.number_input("เงินทุนรวม (USD)", value=10000.0)
    r_pct = st.slider("ความเสี่ยงต่อไม้ (%)", 1.0, 5.0, 2.0)
    b_p = st.number_input("ราคาต้นทุนที่ซื้อ (USD)", min_value=0.0, step=0.1)

    if not st.session_state["logged_in"]:
        pwd = st.text_input("🔑 รหัสผ่าน", type="password")
        if st.button("🔓 Login", use_container_width=True):
            if pwd == st.secrets.get("app_password", "123456"):
                st.session_state["logged_in"] = True; st.rerun()
    else:
        st.success("✅ โหมดเจ้าของพอร์ต")
        if st.button("🚪 Logout", use_container_width=True):
            st.session_state["logged_in"] = False; st.rerun()

# --- Load Chart Data ---
with st.spinner(f"⏳ ดึงข้อมูล {ticker}..."):
    df_chart, fund_info, matrix, market = load_pro_data(ticker, tf_option)

tabs = ["📊 วิเคราะห์กราฟ", "💼 บัญชีและพอร์ต", "🧾 ภาษีสรรพากร"] if st.session_state["logged_in"] else ["📊 วิเคราะห์กราฟ"]
tab_list = st.tabs(tabs)

# --- TAB 1: Analysis ---
with tab_list[0]:
    if not df_chart.empty:
        last_p = df_chart['Close'].iloc[-1]
        st.markdown(f"## 📈 หุ้น: {ticker} | ราคาล่าสุด: ${last_p:,.2f}")
        
        if market:
            m1, m2, m3 = st.columns(3)
            m1.metric("S&P 500", f"{market['spy_price']:,.2f}", market['spy_trend'])
            v_val = market['vix']
            m2.metric("VIX Index", f"{v_val:.2f}", "Risk-OFF" if v_val > 25 else "Risk-ON")
            with m3:
                if market['vix'] < 25 and "ขึ้น" in market['spy_trend']: st.success("✅ ตลาดปลอดภัย")
                else: st.warning("⚠️ ระวังความผันผวน")

        # กราฟหลัก
        fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.45, 0.15, 0.2, 0.2])
        fig.add_trace(go.Candlestick(x=df_chart.index, open=df_chart['Open'], high=df_chart['High'], low=df_chart['Low'], close=df_chart['Close'], name="Price"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['E50'], line=dict(color='#FF6D00'), name="EMA 50"), row=1, col=1)
        fig.add_trace(go.Bar(x=df_chart.index, y=df_chart['Volume'], name="Vol"), row=2, col=1)
        fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['RSI'], line=dict(color='#BA68C8'), name="RSI"), row=3, col=1)
        fig.add_trace(go.Bar(x=df_chart.index, y=df_chart['Hist'], name="MACD"), row=4, col=1)
        fig.update_layout(template="plotly_dark", height=800, xaxis_rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True)

        # สรุปสัญญาณ
        st.subheader("🤖 AI Technical Summary")
        c1, c2, c3 = st.columns(3)
        c1.write(f"**เทรนด์ (EMA 50):** {'🟢 ขาขึ้น' if last_p > df_chart['E50'].iloc[-1] else '🔴 ขาลง'}")
        c2.write(f"**แรงซื้อ (RSI):** {df_chart['RSI'].iloc[-1]:.2f}")
        c3.write(f"**เป้าหมาย:** {matrix['l']:,.2f} - {matrix['u']:,.2f}")
    else: st.warning("กรุณาระบุชื่อหุ้นให้ถูกต้อง")

# --- TAB 2 & 3: Port & Tax ---
if st.session_state["logged_in"]:
    sorted_ledger, cb, l_stat, holdings = calculate_stats(st.session_state.trade_ledger)
    st.session_state.trade_ledger = sorted_ledger

    with tab_list[1]:
        st.subheader("💼 แดชบอร์ดกระแสเงินสด")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("📤 โอนออกสะสม", f"${l_stat['outward']:,.2f}")
        c2.metric("📥 นำกลับสะสม", f"${l_stat['inward']:,.2f}")
        c3.metric("📈 ต้นทุนหุ้นในมือ", f"${l_stat['bought'] - l_stat['sold']:,.2f}")
        c4.metric("💰 เงินสดคงเหลือ", f"${cb:,.2f}")

        with st.form("ledger_edit"):
            ed_l = st.data_editor(st.session_state.trade_ledger, num_rows="dynamic", use_container_width=True)
            if st.form_submit_button("💾 บันทึกข้อมูลขึ้น Cloud"):
                new_df, _, _, _ = calculate_stats(ed_l)
                if save_df_to_sheet("Ledger", new_df):
                    st.session_state.trade_ledger = new_df; st.success("บันทึกแล้ว!"); time.sleep(1); st.rerun()

        st.markdown("---")
        st.subheader("📊 พอร์ตโฟลิโอ Real-time")
        fx = get_live_fx()
        active = [t for t, d in holdings.items() if d["shares"] > 0.001]
        if active:
            prices = get_batch_prices(active)
            res = []
            for t in active:
                sh, cost = holdings[t]["shares"], holdings[t]["total_cost"]
                cp = prices.get(t, cost/sh)
                val = cp * sh
                pl = val - cost
                res.append({"หุ้น": t, "จำนวน": sh, "ต้นทุนเฉลี่ย": cost/sh, "ราคาปัจจุบัน": cp, "กำไร/ขาดทุน $": pl, "กำไร/ขาดทุน ฿": pl*fx, "%": (pl/cost)*100 if cost>0 else 0, "มูลค่ารวม": val})
            
            res_df = pd.DataFrame(res)
            st.dataframe(res_df.style.map(lambda x: f'color: {"#FF5252" if x < 0 else "#00E676"};', subset=["กำไร/ขาดทุน $", "%"]).format("{:,.2f}"), use_container_width=True)
            
            with st.expander("⚖️ จำลองปรับสัดส่วนพอร์ต (Rebalancing)"):
                rebal = res_df[["หุ้น", "มูลค่ารวม"]].copy()
                rebal["เป้าหมาย %"] = 0.0
                ed_re = st.data_editor(rebal, use_container_width=True)
                if ed_re["เป้าหมาย %"].sum() > 0:
                    total_v = res_df["มูลค่ารวม"].sum()
                    ed_re["ต้องปรับ $"] = (total_v * (ed_re["เป้าหมาย %"]/100)) - ed_re["มูลค่ารวม"]
                    st.dataframe(ed_re[["หุ้น", "ต้องปรับ $"]].style.format("{:,.2f}"))

    with tab_list[2]:
        st.subheader("🧾 ระบบประเมินภาษีสรรพากร ภ.ง.ด. 90")
        tax_idx = st.session_state.trade_ledger['Action'].isin(["นำเงินออกนอกประเทศ (Outward)", "นำเงินเข้าประเทศไทย (Inward)", "รับเงินปันผล (Dividend)"])
        tax_v = st.session_state.trade_ledger[tax_idx].copy()
        
        tax_v["Out_USD"] = np.where(tax_v["Action"]=="นำเงินออกนอกประเทศ (Outward)", tax_v["Amount_USD"], 0)
        tax_v["In_USD"] = np.where(tax_v["Action"].isin(["นำเงินเข้าประเทศไทย (Inward)", "รับเงินปันผล (Dividend)"]), tax_v["Amount_USD"], 0)
        tax_v["Out_THB"] = tax_v["Out_USD"] * tax_v["FX_Rate"]
        tax_v["In_THB"] = tax_v["In_USD"] * tax_v["FX_Rate"]
        
        # แสดงตารางภาษี
        ed_t = st.data_editor(tax_v, use_container_width=True)
        if st.button("💾 บันทึกเรทเงิน/ภาษีลง Cloud"):
            st.session_state.trade_ledger.loc[tax_idx, ["FX_Rate", "WHT_USD", "Ref_Doc"]] = ed_t[["FX_Rate", "WHT_USD", "Ref_Doc"]].values
            save_df_to_sheet("Ledger", st.session_state.trade_ledger); st.rerun()

        sum_out, sum_in = tax_v["Out_THB"].sum(), tax_v["In_THB"].sum()
        net_gain = max(0, sum_in - sum_out)
        
        st.markdown("---")
        cf1, cf2, cf3 = st.columns(3)
        cf1.metric("โอนออกรวม", f"฿{sum_out:,.2f}")
        cf2.metric("นำกลับรวม", f"฿{sum_in:,.2f}")
        cf3.metric("🚨 ส่วนเกินทุน (กำไร)", f"฿{net_gain:,.2f}", delta_color="inverse")

        st.markdown("---")
        c1, c2, c3 = st.columns(3)
        with c1: tax_y = st.selectbox("ปีภาษี", ["2567", "2568"])
        with c2: resident = st.radio("อยู่ในไทยเกิน 180 วัน?", ["ใช่", "ไม่ใช่"])
        with c3: other_inc = st.number_input("รายได้ประจำอื่นๆ (บาท)", value=500000.0)

        with st.expander("📝 บันทึกค่าลดหย่อน (ssf/rmf/ประกัน/บุตร)"):
            col1, col2 = st.columns(2)
            spouse = col1.checkbox("คู่สมรสไม่มีรายได้")
            kids = col2.number_input("จำนวนบุตร", value=0)
            life = st.number_input("ประกันชีวิต/สุขภาพ", value=0.0)
            invest = st.number_input("SSF + RMF + PVD", value=0.0)
            donate = st.number_input("เงินบริจาค", value=0.0)

        if st.button("📊 คำนวณภาษีสุทธิ", type="primary", use_container_width=True):
            if resident == "ไม่ใช่": st.success("🎉 ยกเว้นภาษี")
            elif net_gain <= 0: st.success("🎉 ยังไม่มีกำไรส่วนเกินเงินต้น")
            else:
                # คำนวณลดหย่อน
                deduct = 60000 + (60000 if spouse else 0) + (kids*30000) + min(life, 100000) + min(invest, 500000) + donate + 100000 # 100k คือค่าใช้จ่าย 50%
                net_total = max(0, (other_inc + net_gain) - deduct)
                net_no_port = max(0, other_inc - deduct)
                
                def calc_tax(n):
                    if n > 5000000: return (n-5000000)*0.35 + 1265000
                    if n > 2000000: return (n-2000000)*0.30 + 365000
                    if n > 1000000: return (n-1000000)*0.25 + 115000
                    if n > 750000: return (n-750000)*0.20 + 65000
                    if n > 500000: return (n-500000)*0.15 + 27500
                    if n > 300000: return (n-300000)*0.10 + 7500
                    if n > 150000: return (n-150000)*0.05
                    return 0
                
                tax_bill = calc_tax(net_total) - calc_tax(net_no_port)
                st.subheader(f"ภาษีที่ต้องจ่ายเพิ่มจากพอร์ต: ฿{tax_bill:,.2f}")

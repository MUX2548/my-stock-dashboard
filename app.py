import json
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

# 1. ตั้งค่าหน้าเพจ
st.set_page_config(page_title="Strategic Portfolio Ecosystem 3.0", layout="wide")

# ==========================================
# 🔐 การเชื่อมต่อฐานข้อมูล (เข้าถึงเฉพาะแผ่นงานที่ระบุ)
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

def load_ledger_data():
    try:
        ws = sh.worksheet("Ledger") # 👈 ล็อคเป้าหมายเฉพาะชีต Ledger
        records = ws.get_all_records()
        if not records:
            return pd.DataFrame(columns=["Date", "Action", "Ticker", "Price", "Shares", "Amount_USD", "Running_Balance", "FX_Rate", "WHT_USD", "Ref_Doc"])
        df = pd.DataFrame(records)
        df.replace(["", "None", "nan", None], np.nan, inplace=True)
        df.dropna(how="all", inplace=True)
        df.fillna("", inplace=True)
    except:
        df = pd.DataFrame()

    req_cols = ["Date", "Action", "Ticker", "Price", "Shares", "Amount_USD", "Running_Balance", "FX_Rate", "WHT_USD", "Ref_Doc"]
    for col in req_cols:
        if col not in df.columns: df[col] = ""

    for col in ["Price", "Shares", "Amount_USD", "Running_Balance", "FX_Rate", "WHT_USD"]:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
    
    if not df.empty and "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], format="%d/%m/%Y", errors="coerce").dt.strftime("%d/%m/%Y").replace("NaT", "")
    
    return df[req_cols]

def save_df_to_sheet(worksheet_name, df):
    ws = sh.worksheet(worksheet_name)
    ws.clear() # 👈 ล้างข้อมูลเฉพาะชีตที่ระบุเท่านั้น! ชีตอื่นไม่เกี่ยว
    clean_df = df.copy().fillna("")
    data_list = [clean_df.columns.values.tolist()] + clean_df.values.tolist()
    ws.update(values=data_list, range_name='A1')

if "trade_ledger" not in st.session_state:
    st.session_state.trade_ledger = load_ledger_data()

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

tz_th = timezone(timedelta(hours=7))
current_date = datetime.now(tz_th).strftime("%d/%m/%Y")
current_time = datetime.now(tz_th).strftime("%H:%M")

def calculate_stats(df_input):
    df = df_input.copy()
    cb = 0.0
    stat = {"outward": 0.0, "inward": 0.0, "bought": 0.0, "sold": 0.0, "dividend": 0.0, "realized_profit": 0.0}
    r_bals, hld = [], {}
    
    for idx, row in df.iterrows():
        action = str(row.get("Action", "")).strip()
        ticker = str(row.get("Ticker", "")).strip().upper()
        
        def safe_n(val):
            if pd.isna(val) or val is None or str(val).strip() in ["", "None", "nan"]: return 0.0
            try: return float(val)
            except: return 0.0

        p, s, a = safe_n(row.get("Price")), safe_n(row.get("Shares")), safe_n(row.get("Amount_USD"))
        val = p * s
        if action == "นำเงินออกนอกประเทศ (Outward)": cb += a; stat["outward"] += a
        elif action == "นำเงินเข้าประเทศไทย (Inward)": cb -= a; stat["inward"] += a
        elif action == "รับเงินปันผล (Dividend)": cb += a; stat["dividend"] += a
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
    return cb, stat, r_bals, hld

# ==========================================
# 🌟 Sidebar (Public Tools)
# ==========================================
with st.sidebar:
    st.title("🛡️ Strategic Hub")
    ticker = st.text_input("🔎 ชื่อหุ้น / ดัชนี", value="NVTS").upper()
    tf_option = st.radio("เลือกความละเอียด:", ["1D (รายวัน)", "1W (รายสัปดาห์)", "1M (รายเดือน)"], index=0)
    
    st.markdown("---")
    st.subheader("🧮 เครื่องมือคำนวณ (Public)")
    t_cap = st.number_input("เงินทุนรวม (USD)", value=10000.0)
    r_pct = st.slider("ความเสี่ยงต่อไม้ (%)", 1.0, 5.0, 2.0)
    b_p = st.number_input("ราคาต้นทุนที่ซื้อ (USD)", min_value=0.0, step=0.1)
    
    st.markdown("---")
    if not st.session_state["logged_in"]:
        pwd = st.text_input("🔑 รหัสผ่าน (สำหรับเจ้าของ)", type="password")
        if st.button("เข้าสู่ระบบ", use_container_width=True):
            if pwd == st.secrets.get("app_password", "123456"):
                st.session_state["logged_in"] = True
                st.rerun()
    else:
        st.success("✅ โหมดเจ้าของพอร์ต")
        if st.button("🚪 ออกจากระบบ", use_container_width=True):
            st.session_state["logged_in"] = False
            st.rerun()

# --- ดึงข้อมูลวิเคราะห์ ---
@st.cache_data(ttl=300)
def load_pro_data(ticker_symbol, tf):
    stgs = {"1D (รายวัน)": {"p": "6mo", "i": "1d"}, "1W (รายสัปดาห์)": {"p": "2y", "i": "1wk"}, "1M (รายเดือน)": {"p": "5y", "i": "1mo"}}
    p, i = stgs[tf]["p"], stgs[tf]["i"]
    try:
        s = yf.Ticker(ticker_symbol)
        df = s.history(period=p, interval=i)
        if df.empty: return None, {}, None
        df = df.dropna(subset=['Close'])
        spy = yf.Ticker("^GSPC").history(period=p, interval=i)['Close']
        df['RS'] = (df['Close'].pct_change(10) - spy.pct_change(10)) * 100
        df['E20'] = df['Close'].ewm(span=20).mean()
        df['E50'] = df['Close'].ewm(span=50).mean()
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14).mean()
        df['RSI'] = 100 - (100 / (1 + gain/loss))
        df['MACD'] = df['Close'].ewm(span=12).mean() - df['Close'].ewm(span=26).mean()
        df['Sig'] = df['MACD'].ewm(span=9).mean()
        df['Hist'] = df['MACD'] - df['Sig']
        
        info = s.info
        fund = {"ps": f"{info.get('priceToSalesTrailing12Months', 0):.2f}", "pe": f"{info.get('trailingPE', 0):.2f}", "roe": f"{info.get('returnOnEquity', 0)*100:.2f}%"}
        
        last = df['Close'].iloc[-1]
        v = df['Close'].pct_change().tail(14).std()
        tr = "ขึ้น 📈" if last > df['E50'].iloc[-1] else "ลง 📉"
        mat = {"l": last * (1 - v*1.0) if tr == "ลง 📉" else last * (1 - v*0.5), "u": last * (1 - v*0.5) if tr == "ลง 📉" else last * (1 + v*1.0), "tr": tr}
        return df, fund, mat
    except: return None, {}, None

df, fund, matrix = load_pro_data(ticker, tf_option)

# --- Tabs ---
tabs = ["📊 วิเคราะห์กราฟ (Analysis)", "💼 บัญชี (Cloud Sync)", "🧾 ภาษีสรรพากร"] if st.session_state["logged_in"] else ["📊 วิเคราะห์กราฟ (Analysis)"]
tab_list = st.tabs(tabs)

# ==========================================
# หน้า 1: วิเคราะห์กราฟ
# ==========================================
with tab_list[0]:
    st.markdown(f"## 📈 วิเคราะห์หุ้น: {ticker}")
    if df is not None:
        last_p = df['Close'].iloc[-1]
        rs = df['RS'].iloc[-1]
        rs_t = f" | **RS:** {'🟢 ชนะตลาด' if rs > 0 else '🔴 อ่อนแอ'} ({rs:.2f}%)" if not np.isnan(rs) else ""
        if matrix: st.info(f"🔮 **ทิศทาง {tf_option}:** {matrix['tr']} | **เป้าหมาย:** {matrix['l']:,.2f} - {matrix['u']:,.2f} (Harmonic Matrix){rs_t}")
        
        c_l, c_r = st.columns([7, 3])
        with c_l:
            fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.45, 0.15, 0.2, 0.2])
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close']), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['E20'], line=dict(color='#00E676')), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['E50'], line=dict(color='#FF6D00')), row=1, col=1)
            if b_p > 0: fig.add_hline(y=b_p, line_dash="dash", line_color="cyan", row=1, col=1)
            v_c = ['#00E676' if df['Close'].iloc[i] > df['Open'].iloc[i] else '#FF5252' for i in range(len(df))]
            fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=v_c), row=2, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], line=dict(color='#BA68C8')), row=3, col=1)
            fig.add_trace(go.Bar(x=df.index, y=df['Hist'], marker_color=['#00E676' if v >= 0 else '#FF5252' for v in df['Hist']]), row=4, col=1)
            fig.update_layout(template="plotly_dark", height=800, margin=dict(l=0,r=0,t=0,b=0), showlegend=False)
            fig.update_xaxes(rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)
            st.subheader("📊 ข้อมูลพื้นฐาน")
            f1, f2, f3 = st.columns(3); f1.metric("P/S", fund['ps']); f2.metric("P/E", fund['pe']); f3.metric("ROE", fund['roe'])
        with c_r:
            st.metric("ราคาปัจจุบัน", f"${last_p:,.2f}", f"{last_p - (df['Close'].iloc[-2] if len(df)>1 else last_p):.2f}")
            if b_p > 0:
                pl = ((last_p - b_p) / b_p) * 100
                st.write(f"**กำไร/ขาดทุนของคุณ:** {pl:.2f}%")
                sl = df['E50'].iloc[-1] * 0.99 if b_p == 0 else b_p * 0.92
                st.error(f"🛡️ **จุดหนี (Stop Loss): ${sl:.2f}**")
                ra = t_cap * (r_pct / 100); rps = last_p - sl
                if rps > 0: st.success(f"🧮 **ซื้อได้สูงสุด:** {ra/rps:.2f} หุ้น")
            st.markdown("---")
            st.subheader("🤖 สรุปสัญญาณ")
            tr_s = "🟢 ขาขึ้น" if last_p > df['E50'].iloc[-1] else "🔴 ขาลง"
            mc_s = "🟢 แรงซื้อ" if df['MACD'].iloc[-1] > df['Sig'].iloc[-1] else "🔴 แรงขาย"
            st.write(f"**เทรนด์:** {tr_s} | **MACD:** {mc_s}")
            st.write(f"**ต้าน:** {df['High'].tail(20).max():.2f} | **รับ:** {df['E50'].iloc[-1]:.2f}")

if st.session_state["logged_in"]:
    cb, l_stat, r_bals, holdings = calculate_stats(st.session_state.trade_ledger)
    st.session_state.trade_ledger["Running_Balance"] = r_bals

    with tab_list[1]:
        st.subheader("💼 แดชบอร์ดกระแสเงินสด")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("📤 นำเงินออกสะสม", f"${l_stat['outward']:,.2f}")
        col2.metric("📉 ซื้อหุ้นไปแล้ว", f"${l_stat['bought']:,.2f}", delta_color="inverse")
        col3.metric("📈 ขายหุ้นได้เงินมา", f"${l_stat['sold']:,.2f}")
        col4.metric("💰 เงินสดคงเหลือ", f"${cb:,.2f}")
        
        st.markdown("---")
        ed_l = st.data_editor(st.session_state.trade_ledger, num_rows="dynamic", use_container_width=True,
            column_config={"Action": st.column_config.SelectboxColumn("ประเภท", options=["นำเงินออกนอกประเทศ (Outward)", "นำเงินเข้าประเทศไทย (Inward)", "ซื้อหุ้น (Buy)", "ขายหุ้น (Sell)", "รับเงินปันผล (Dividend)"]),
                           "Running_Balance": st.column_config.Column("ยอดยกมา ($)", disabled=True), "FX_Rate": None, "WHT_USD": None, "Ref_Doc": None})
        if not ed_l.equals(st.session_state.trade_ledger):
            ed_l.replace([None, "None", "nan"], "", inplace=True)
            _, _, n_rb, _ = calculate_stats(ed_l)
            ed_l["Running_Balance"] = n_rb
            st.session_state.trade_ledger = ed_l; st.rerun()
        if st.button("💾 บันทึกข้อมูลพอร์ตลง Cloud"):
            save_df_to_sheet("Ledger", st.session_state.trade_ledger); st.success("บันทึกแล้ว!")

    with tab_list[2]:
        st.subheader("🧾 ระบบประเมินภาษีสรรพากร ภ.ง.ด. 90")
        tax_idx = st.session_state.trade_ledger['Action'].isin(["นำเงินออกนอกประเทศ (Outward)", "นำเงินเข้าประเทศไทย (Inward)", "รับเงินปันผล (Dividend)"])
        tax_v = st.session_state.trade_ledger[tax_idx].copy()
        
        tax_v["Out_USD"] = tax_v.apply(lambda r: float(r.get("Amount_USD", 0)) if r.get("Action") == "นำเงินออกนอกประเทศ (Outward)" else 0.0, axis=1)
        tax_v["In_USD"] = tax_v.apply(lambda r: float(r.get("Amount_USD", 0)) if r.get("Action") in ["นำเงินเข้าประเทศไทย (Inward)", "รับเงินปันผล (Dividend)"] else 0.0, axis=1)
        tax_v["Out_THB"] = tax_v["Out_USD"] * tax_v["FX_Rate"].apply(lambda x: float(x) if x!="" else 0.0)
        tax_v["In_THB"] = tax_v["In_USD"] * tax_v["FX_Rate"].apply(lambda x: float(x) if x!="" else 0.0)
        
        # ตัดสต๊อกเงินต้นคงเหลือ (฿)
        t_bals, c_t_bal = [], 0.0
        for i, r in tax_v.iterrows():
            c_t_bal += (r["Out_THB"] - r["In_THB"]); t_bals.append(c_t_bal)
        tax_v["Balance_THB"] = t_bals

        ed_t = st.data_editor(tax_v, use_container_width=True, num_rows="fixed",
            column_order=["Date", "Out_USD", "In_USD", "FX_Rate", "Out_THB", "In_THB", "Balance_THB", "WHT_USD", "Ref_Doc"],
            column_config={"Out_USD": st.column_config.NumberColumn("โอนออก ($)", disabled=True), "In_USD": st.column_config.NumberColumn("นำเข้า ($)", disabled=True),
                           "Out_THB": st.column_config.NumberColumn("โอนออก (฿)", disabled=True), "In_THB": st.column_config.NumberColumn("นำเข้า (฿)", disabled=True),
                           "Balance_THB": st.column_config.NumberColumn("เงินต้นคงเหลือ (฿)", disabled=True)})
        
        if not ed_t[["FX_Rate", "WHT_USD", "Ref_Doc"]].equals(tax_v[["FX_Rate", "WHT_USD", "Ref_Doc"]]):
            st.session_state.trade_ledger.loc[tax_idx, ["FX_Rate", "WHT_USD", "Ref_Doc"]] = ed_t[["FX_Rate", "WHT_USD", "Ref_Doc"]].values
            st.rerun()

        if st.button("💾 บันทึกอัตราแลกเปลี่ยน"):
            save_df_to_sheet("Ledger", st.session_state.trade_ledger); st.success("บันทึกแล้ว!")

        # แดชบอร์ดภาษี (฿) - แก้ไขให้ลิงก์กับตารางด้านบน
        sum_out_thb = tax_v["Out_THB"].sum()
        sum_in_thb = tax_v["In_THB"].sum()
        sum_wht_thb = (tax_v["WHT_USD"] * tax_v["FX_Rate"].apply(lambda x: float(x) if x!="" else 0.0)).sum()
        net_tax_gain = max(0, sum_in_thb - sum_out_thb)

        cf1, cf2, cf3 = st.columns(3)
        cf1.metric("📤 รวมโอนออก (เงินต้น)", f"฿{sum_out_thb:,.2f}")
        cf2.metric("📥 รวมนำเข้าไทย", f"฿{sum_in_thb:,.2f}")
        cf3.metric("🚨 กำไรสุทธิที่ต้องประเมิน", f"฿{net_tax_gain:,.2f}", "หักล้างเงินต้นแล้ว", delta_color="inverse")

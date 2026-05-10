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
# 🔐 การเชื่อมต่อฐานข้อมูล (Google Sheets)
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

# ฟังก์ชันดึงข้อมูลจากสมุดบัญชี (ป้องกัน None)
def load_ledger_data():
    try:
        ws = sh.worksheet("Ledger")
        records = ws.get_all_records()
        if not records:
            return pd.DataFrame(columns=["Date", "Action", "Ticker", "Price", "Shares", "Amount_USD", "Running_Balance", "FX_Rate", "WHT_USD", "Ref_Doc"])
        df = pd.DataFrame(records)
        df.replace("", np.nan, inplace=True)
        df.dropna(how="all", inplace=True)
        df.fillna("", inplace=True)
    except:
        df = pd.DataFrame()

    required_cols = ["Date", "Action", "Ticker", "Price", "Shares", "Amount_USD", "Running_Balance", "FX_Rate", "WHT_USD", "Ref_Doc"]
    for col in required_cols:
        if col not in df.columns: df[col] = ""

    # บังคับรูปแบบคอลัมน์
    for col in ["Price", "Shares", "Amount_USD", "Running_Balance", "FX_Rate", "WHT_USD"]:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
    for col in ["Action", "Ticker", "Ref_Doc"]:
        df[col] = df[col].astype(str).replace("None", "").replace("nan", "")
    if not df.empty and "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], format="%d/%m/%Y", errors="coerce").dt.strftime("%d/%m/%Y").replace("NaT", "")
    
    return df[required_cols]

# ฟังก์ชันบันทึกข้อมูล
def save_df_to_sheet(worksheet_name, df):
    ws = sh.worksheet(worksheet_name)
    ws.clear()
    clean_df = df.copy()
    clean_df = clean_df.fillna("")
    data_list = [clean_df.columns.values.tolist()] + clean_df.values.tolist()
    ws.update(values=data_list, range_name='A1')

# โหลดข้อมูลเริ่มต้น
if "trade_ledger" not in st.session_state:
    st.session_state.trade_ledger = load_ledger_data()

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

tz_th = timezone(timedelta(hours=7))
current_date = datetime.now(tz_th).strftime("%d/%m/%Y")
current_time = datetime.now(tz_th).strftime("%H:%M")

# --- แถบเมนูด้านซ้าย (Sidebar) ---
with st.sidebar:
    st.title("🛡️ Strategic Hub")
    ticker = st.text_input("🔎 ชื่อหุ้น / ดัชนี", value="NVTS").upper()
    st.markdown("---")
    tf_option = st.radio("เลือกความละเอียด:", ["1D (รายวัน)", "1W (รายสัปดาห์)", "1M (รายเดือน)"], index=0)
    st.markdown("---")
    
    if not st.session_state["logged_in"]:
        st.subheader("🔒 สำหรับเจ้าของพอร์ต")
        pwd = st.text_input("🔑 รหัสผ่าน", type="password")
        if st.button("เข้าสู่ระบบ", use_container_width=True):
            if pwd == st.secrets.get("app_password", "123456"):
                st.session_state["logged_in"] = True
                st.rerun()
            else: st.error("❌ รหัสผ่านไม่ถูกต้อง")
        buy_price = 0.0
    else:
        st.subheader("💰 สถานะหุ้นตัวนี้")
        buy_price = st.number_input("ราคาต้นทุน (USD)", min_value=0.0, value=0.0, step=0.1)
        if st.button("🚪 ออกจากระบบ", use_container_width=True):
            st.session_state["logged_in"] = False
            st.rerun()

# --- ฟังก์ชันดึงข้อมูลหุ้น ---
@st.cache_data(ttl=300)
def load_pro_data(ticker_symbol, tf):
    settings = {"1D (รายวัน)": {"period": "6mo", "interval": "1d"}, "1W (รายสัปดาห์)": {"period": "2y", "interval": "1wk"}, "1M (รายเดือน)": {"period": "5y", "interval": "1mo"}}
    p, i = settings[tf]["period"], settings[tf]["interval"]
    try:
        stock = yf.Ticker(ticker_symbol)
        df = stock.history(period=p, interval=i)
        if df.empty: return pd.DataFrame()
        df['EMA_20'] = df['Close'].ewm(span=20, adjust=False).mean()
        df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()
        return df
    except: return pd.DataFrame()

df = load_pro_data(ticker, tf_option)

# ==========================================
# 🌟 เครื่องยนต์คำนวณบัญชี (ตัดสต๊อก Real-time)
# ==========================================
def recalculate_ledger(df_input):
    df = df_input.copy()
    for col in ["Price", "Shares", "Amount_USD", "FX_Rate", "WHT_USD"]:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
    
    cb = 0.0
    stat = {"outward": 0.0, "inward": 0.0, "bought": 0.0, "sold": 0.0, "dividend": 0.0, "realized_profit": 0.0}
    hld = {}

    for idx, row in df.iterrows():
        action = str(row.get("Action", "")).strip()
        ticker = str(row.get("Ticker", "")).strip().replace("None", "")
        price = float(row.get("Price", 0.0))
        shares = float(row.get("Shares", 0.0))
        amt = float(row.get("Amount_USD", 0.0))

        trade_val = price * shares

        if action == "นำเงินออกนอกประเทศ (Outward)":
            cb += amt
            stat["outward"] += amt
        elif action == "นำเงินเข้าประเทศไทย (Inward)":
            cb -= amt
            stat["inward"] += amt
        elif action == "รับเงินปันผล (Dividend)": 
            cb += amt
            stat["dividend"] += amt
        elif action == "ซื้อหุ้น (Buy)" and ticker:
            cb -= trade_val
            stat["bought"] += trade_val
            if ticker not in hld: hld[ticker] = {"shares": 0.0, "total_cost": 0.0}
            hld[ticker]["shares"] += shares
            hld[ticker]["total_cost"] += trade_val
        elif action == "ขายหุ้น (Sell)" and ticker:
            cb += trade_val
            stat["sold"] += trade_val
            if ticker in hld and hld[ticker]["shares"] > 0:
                avg_cost = hld[ticker]["total_cost"] / hld[ticker]["shares"]
                profit = trade_val - (avg_cost * shares)
                stat["realized_profit"] += profit
                hld[ticker]["shares"] -= shares
                hld[ticker]["total_cost"] -= (avg_cost * shares)
        
        # บันทึกยอดยกมาลงใน DataFrame ทันที
        df.at[idx, "Running_Balance"] = cb
        df.at[idx, "Ticker"] = ticker # แก้ None ให้เป็นค่าว่าง

    return df, cb, stat, hld

# ทำการคำนวณตารางล่าสุด
st.session_state.trade_ledger, cash_balance, ledger_stat, holdings = recalculate_ledger(st.session_state.trade_ledger)

# ==========================================
# 🌟 ระบบแท็บ
# ==========================================
if st.session_state["logged_in"]:
    tab_dash, tab_port, tab_tax = st.tabs(["📊 วิเคราะห์กราฟ", "💼 บัญชี (สมุดหลัก)", "🧾 ภาษี (ลิงก์อัตโนมัติ)"])
else:
    tab_dash, = st.tabs(["📊 วิเคราะห์กราฟ"])

with tab_dash:
    st.markdown(f"## 📈 วิเคราะห์หุ้น: {ticker}")
    if not df.empty:
        fig = go.Figure(data=[go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'])])
        fig.add_trace(go.Scatter(x=df.index, y=df['EMA_20'], line=dict(color='#00E676', width=2), name="EMA 20"))
        fig.add_trace(go.Scatter(x=df.index, y=df['EMA_50'], line=dict(color='#FF6D00', width=2), name="EMA 50"))
        fig.update_layout(template="plotly_dark", height=500)
        st.plotly_chart(fig, use_container_width=True)

if st.session_state["logged_in"]:
    
    with tab_port:
        st.subheader("💼 แดชบอร์ดสรุปกระแสเงินสด (Cash Flow & Inventory)")
        
        # 🌟 แผง Dashboard แบบตัดสต๊อก
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("📤 นำเงินออกสะสม", f"${ledger_stat['outward']:,.2f}")
        col2.metric("📉 ใช้ซื้อหุ้นไปแล้ว", f"${ledger_stat['bought']:,.2f}", "หักจากเงินสด", delta_color="inverse")
        col3.metric("📈 ขายหุ้นได้เงินมา", f"${ledger_stat['sold']:,.2f}", "บวกกลับเข้าเงินสด")
        col4.metric("💰 เงินสดคงเหลือ (ซื้อได้อีก)", f"${cash_balance:,.2f}")

        st.markdown("---")
        st.subheader("📝 สมุดบัญชี Cloud Ledger (แก้ไข/เพิ่ม/ลบ แถวได้เลย)")
        st.caption("💡 ทริค: หากต้องการ 'ลบแถว' ให้คลิกที่ช่องสี่เหลี่ยมหน้าแถวนั้น แล้วกดปุ่ม Delete บนคีย์บอร์ดค่ะ")
        
        edited_ledger = st.data_editor(
            st.session_state.trade_ledger, 
            num_rows="dynamic", # อนุญาตให้เพิ่ม/ลบแถวได้
            use_container_width=True,
            column_config={
                "Date": "วันที่ (DD/MM/YYYY)",
                "Action": st.column_config.SelectboxColumn("ประเภทรายการ", options=["นำเงินออกนอกประเทศ (Outward)", "นำเงินเข้าประเทศไทย (Inward)", "ซื้อหุ้น (Buy)", "ขายหุ้น (Sell)", "รับเงินปันผล (Dividend)"]),
                "Ticker": "ชื่อหุ้น",
                "Price": "ราคา ($)",
                "Shares": "จำนวนหุ้น",
                "Amount_USD": "จำนวนเงิน ($)",
                "Running_Balance": st.column_config.Column("ยอดยกมา ($)", disabled=True),
                "FX_Rate": None, "WHT_USD": None, "Ref_Doc": None
            }
        )
        
        # ถ้าระบบตรวจพบว่ามีการแก้/เพิ่ม/ลบ ข้อมูล ให้คำนวณใหม่และรีโหลดหน้าจอ
        if not edited_ledger.equals(st.session_state.trade_ledger):
            st.session_state.trade_ledger = edited_ledger
            st.rerun()

        if st.button("💾 บันทึกการเปลี่ยนแปลงทั้งหมดลง Google Sheets", type="primary", use_container_width=True):
            with st.spinner("กำลังอัปเดตข้อมูลบนคลาวด์..."):
                try:
                    save_df_to_sheet("Ledger", st.session_state.trade_ledger)
                    st.success("🎉 บันทึกสำเร็จแล้ว! ข้อมูลปลอดภัย 100%")
                except Exception as e:
                    st.error(f"เกิดข้อผิดพลาด: {e}")

    with tab_tax:
        st.subheader("🧾 ระบบประเมินภาษีสรรพากร (ลิงก์ข้อมูลอัตโนมัติ)")
        
        tax_actions = ["นำเงินออกนอกประเทศ (Outward)", "นำเงินเข้าประเทศไทย (Inward)", "รับเงินปันผล (Dividend)"]
        tax_view = st.session_state.trade_ledger[st.session_state.trade_ledger['Action'].isin(tax_actions)].copy()

        edited_tax_view = st.data_editor(
            tax_view,
            num_rows="fixed",
            use_container_width=True,
            column_config={
                "Date": st.column_config.Column("วันที่โอน", disabled=True),
                "Action": st.column_config.Column("ประเภทรายการ", disabled=True),
                "Amount_USD": st.column_config.Column("ยอดเงินโอน (USD)", disabled=True),
                "FX_Rate": "อัตราแลกเปลี่ยน",
                "WHT_USD": "ภาษีที่ถูกหัก ตปท. (WHT)",
                "Ref_Doc": "ชื่อไฟล์อ้างอิงแนบ",
                "Ticker": None, "Price": None, "Shares": None, "Running_Balance": None
            }
        )

        if not edited_tax_view.equals(tax_view):
            st.session_state.trade_ledger.update(edited_tax_view)
            st.rerun()
        
        if st.button("💾 บันทึกข้อมูลภาษีลง Google Sheets", type="primary", use_container_width=True):
            with st.spinner("กำลังอัปเดตข้อมูลภาษีลงฐานข้อมูล..."):
                try:
                    save_df_to_sheet("Ledger", st.session_state.trade_ledger)
                    st.success("🎉 บันทึกสำเร็จแล้ว!")
                except Exception as e: st.error(f"เกิดข้อผิดพลาด: {e}")

        total_out_thb, total_in_thb, foreign_tax_credit_thb = 0.0, 0.0, 0.0
        for _, row in tax_view.iterrows():
            usd = float(row.get("Amount_USD", 0) if str(row.get("Amount_USD")) != "" else 0)
            wht = float(row.get("WHT_USD", 0) if str(row.get("WHT_USD")) != "" else 0)
            fx = float(row.get("FX_Rate", 0) if str(row.get("FX_Rate")) != "" else 0)
            
            amt_thb = usd * fx
            wht_thb = wht * fx
            
            direction = str(row.get("Action", ""))
            if direction == "นำเงินออกนอกประเทศ (Outward)": total_out_thb += amt_thb
            elif direction == "นำเงินเข้าประเทศไทย (Inward)": 
                total_in_thb += amt_thb
                foreign_tax_credit_thb += wht_thb 
            elif direction == "รับเงินปันผล (Dividend)":
                foreign_tax_credit_thb += wht_thb
                
        net_taxable_gain = max(0, total_in_thb - total_out_thb)
        
        st.markdown("---")
        cf1, cf2, cf3 = st.columns(3)
        cf1.metric("📤 ยอดรวมโอนออก (เงินต้น)", f"฿{total_out_thb:,.2f}")
        cf2.metric("📥 ยอดรวมโอนเข้าไทย", f"฿{total_in_thb:,.2f}")
        cf3.metric("🚨 กำไรสุทธิที่ประเมินภาษี", f"฿{net_taxable_gain:,.2f}", "หักล้างเงินต้นแล้ว", delta_color="inverse")

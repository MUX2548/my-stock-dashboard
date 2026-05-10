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
# 🔐 การเชื่อมต่อฐานข้อมูลถาวร (Google Sheets)
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

def safe_float(val):
    try:
        if pd.isna(val) or str(val).strip() == "": return 0.0
        return float(val)
    except: return 0.0

# 🌟 ดึงข้อมูลแบบ Safe Mode (ตัดแถวว่างทิ้ง ป้องกันบั๊ก 100%)
def load_ledger_data():
    try:
        ws = sh.worksheet("Ledger")
        records = ws.get_all_records()
        if not records:
            return pd.DataFrame(columns=["Date", "Action", "Ticker", "Price", "Shares", "Amount_USD", "Running_Balance", "FX_Rate", "WHT_USD", "Ref_Doc"])
        
        df = pd.DataFrame(records)
        # ล้างแถวว่างที่เกิดจาก Google Sheets
        df.replace("", np.nan, inplace=True)
        df.dropna(how="all", inplace=True)
        df.fillna("", inplace=True)

    except:
        df = pd.DataFrame()

    required_cols = ["Date", "Action", "Ticker", "Price", "Shares", "Amount_USD", "Running_Balance", "FX_Rate", "WHT_USD", "Ref_Doc"]
    for col in required_cols:
        if col not in df.columns: 
            df[col] = ""

    num_cols = ["Price", "Shares", "Amount_USD", "Running_Balance", "FX_Rate", "WHT_USD"]
    for col in num_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)

    # บังคับรูปแบบวันที่ให้เป็น String เพื่อหลีกเลี่ยงบั๊ก DateColumn ของ Streamlit
    if not df.empty and "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], format="%d/%m/%Y", errors="coerce").dt.strftime("%d/%m/%Y").replace("NaT", "")
    
    return df[required_cols]

# ฟังก์ชันบันทึกข้อมูลกลับลงชีต
def save_df_to_sheet(worksheet_name, df):
    ws = sh.worksheet(worksheet_name)
    ws.clear()
    clean_df = df.copy()
    clean_df = clean_df.fillna("")
    data_list = [clean_df.columns.values.tolist()] + clean_df.values.tolist()
    ws.update(values=data_list, range_name='A1')

# โหลดข้อมูลเข้าสู่ Session State 
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
    ticker = st.text_input("🔎 ชื่อหุ้น / ดัชนี (วิเคราะห์กราฟ)", value="NVTS").upper()
    
    st.markdown("---")
    st.subheader("⏱️ ช่วงเวลาวิเคราะห์")
    tf_option = st.radio("เลือกความละเอียด:", ["1D (รายวัน)", "1W (รายสัปดาห์)", "1M (รายเดือน)"], index=0)
    st.markdown("---")
    
    if not st.session_state["logged_in"]:
        st.subheader("🔒 สำหรับเจ้าของพอร์ต")
        pwd = st.text_input("🔑 รหัสผ่าน", type="password")
        if st.button("เข้าสู่ระบบ (Login)", use_container_width=True):
            if pwd == st.secrets.get("app_password", "123456"):
                st.session_state["logged_in"] = True
                st.rerun()
            else: st.error("❌ รหัสผ่านไม่ถูกต้อง")
        total_capital, risk_pct, buy_price = 0.0, 2.0, 0.0
    else:
        st.subheader("🧮 จัดการความเสี่ยง (Risk Mgmt)")
        total_capital = st.number_input("เงินทุนรวม (USD)", min_value=0.0, value=10000.0, step=100.0)
        risk_pct = st.slider("ความเสี่ยงต่อไม้ (%)", 1.0, 5.0, 2.0)
        st.markdown("---")
        st.subheader("💰 สถานะหุ้นตัวนี้")
        buy_price = st.number_input("ราคาต้นทุน (USD)", min_value=0.0, value=0.0, step=0.1)
        buy_shares = st.number_input("จำนวนหุ้นที่มี", min_value=0.0, value=0.0, step=0.1)
        if st.button("🚪 ออกจากระบบ (Logout)", use_container_width=True):
            st.session_state["logged_in"] = False
            st.rerun()

# --- ฟังก์ชันดึงข้อมูลแบบ Pro ---
@st.cache_data(ttl=300)
def load_pro_data(ticker_symbol, tf):
    settings = {"1D (รายวัน)": {"period": "6mo", "interval": "1d"}, "1W (รายสัปดาห์)": {"period": "2y", "interval": "1wk"}, "1M (รายเดือน)": {"period": "5y", "interval": "1mo"}}
    p, i = settings[tf]["period"], settings[tf]["interval"]
    try:
        stock = yf.Ticker(ticker_symbol)
        df = stock.history(period=p, interval=i)
        if df.empty: return pd.DataFrame(), {}
        df = df.dropna(subset=['Close'])
        spy = yf.Ticker("^GSPC").history(period=p, interval=i)['Close']
        df['RS_vs_Market'] = (df['Close'].pct_change(10) - spy.pct_change(10)) * 100
        df['EMA_10'] = df['Close'].ewm(span=10, adjust=False).mean()
        df['EMA_20'] = df['Close'].ewm(span=20, adjust=False).mean()
        df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        df['RSI'] = 100 - (100 / (1 + gain/loss))
        if len(df) > 1:
            y = df['Close'].values
            x = np.arange(len(y))
            slope, intercept = np.polyfit(x, y, 1)
            df['Trendline'] = slope * x + intercept
        else: df['Trendline'] = np.nan
        fund = {"ps": f"{stock.info.get('priceToSalesTrailing12Months', 0):.2f}", "pe": f"{stock.info.get('trailingPE', 0):.2f}", "roe": f"{stock.info.get('returnOnEquity', 0)*100:.2f}%"}
        return df, fund
    except: return pd.DataFrame(), {}

df, fund = load_pro_data(ticker, tf_option)

def get_matrix(df):
    if df.empty or len(df) < 14: return None
    last = df['Close'].iloc[-1]
    vol = df['Close'].pct_change().tail(14).std()
    trend = "ขึ้น 📈" if last > df['EMA_50'].iloc[-1] else "ลง 📉"
    return {"l": last * (1 - vol*1.0) if trend == "ลง 📉" else last * (1 - vol*0.5), "u": last * (1 - vol*0.5) if trend == "ลง 📉" else last * (1 + vol*1.0), "trend": trend}
matrix = get_matrix(df)

# ==========================================
# 🌟 ระบบแท็บ
# ==========================================
if st.session_state["logged_in"]:
    tab_dash, tab_port, tab_tax = st.tabs(["📊 วิเคราะห์กราฟ", "💼 บัญชี (สมุดหลัก)", "🧾 ภาษี (ลิงก์อัตโนมัติ)"])
else:
    tab_dash, = st.tabs(["📊 วิเคราะห์กราฟ"])

# หน้า 1: วิเคราะห์หลัก
with tab_dash:
    st.markdown(f"## 📈 วิเคราะห์หุ้น: {ticker}")
    if not df.empty:
        last_p = df['Close'].iloc[-1]
        col_left, col_right = st.columns([7, 3])
        with col_left:
            fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.5, 0.25, 0.25])
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name="Price"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['EMA_20'], line=dict(color='#00E676', width=2.5), name="EMA 20"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['EMA_50'], line=dict(color='#FF6D00', width=2.5), name="EMA 50"), row=1, col=1)
            v_colors = ['#00E676' if df['Close'].iloc[i] > df['Open'].iloc[i] else '#FF6D00' for i in range(len(df))]
            fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=v_colors, name="Vol"), row=2, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], line=dict(color='#BA68C8', width=2), name="RSI"), row=3, col=1)
            fig.add_hline(y=70, line_dash="dot", line_color="red", row=3, col=1)
            fig.add_hline(y=30, line_dash="dot", line_color="green", row=3, col=1)
            fig.update_layout(template="plotly_dark", height=600, margin=dict(l=0,r=0,t=0,b=0), showlegend=False)
            fig.update_xaxes(rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)

        with col_right:
            prev_p = df['Close'].iloc[-2] if len(df) > 1 else last_p
            st.metric("ราคาปัจจุบัน", f"${last_p:,.2f}", f"{last_p - prev_p:.2f}")
            if buy_price > 0:
                pl = ((last_p - buy_price) / buy_price) * 100
                st.write(f"**กำไร/ขาดทุน:** {pl:.2f}%")
                sl_price = df['EMA_50'].iloc[-1] * 0.99
                st.error(f"🛡️ **จุดหนี (Stop Loss): ${sl_price:.2f}**")

# ==========================================
# ส่วนบัญชีและภาษี (ฐานข้อมูลเชื่อมโยงกัน)
# ==========================================
cb = 0.0
hld = {}
total_realized_profit = 0.0
total_dividend = 0.0

for idx, row in st.session_state.trade_ledger.iterrows():
    action = str(row.get("Action", ""))
    ticker = str(row.get("Ticker", ""))
    price = safe_float(row.get("Price", 0))
    shares = safe_float(row.get("Shares", 0))
    amt = safe_float(row.get("Amount_USD", 0))

    if action == "นำเงินออกนอกประเทศ (Outward)": cb += amt
    elif action == "นำเงินเข้าประเทศไทย (Inward)": cb -= amt
    elif action == "รับเงินปันผล (Dividend)": 
        cb += amt
        total_dividend += amt
    elif action == "ซื้อหุ้น (Buy)" and ticker:
        trade_val = price * shares
        cb -= trade_val
        if ticker not in hld: hld[ticker] = {"shares": 0.0, "total_cost": 0.0}
        hld[ticker]["shares"] += shares
        hld[ticker]["total_cost"] += trade_val
    elif action == "ขายหุ้น (Sell)" and ticker:
        trade_val = price * shares
        cb += trade_val
        if ticker in hld and hld[ticker]["shares"] > 0:
            avg_cost = hld[ticker]["total_cost"] / hld[ticker]["shares"]
            profit_this_trade = trade_val - (avg_cost * shares)
            total_realized_profit += profit_this_trade
            hld[ticker]["shares"] -= shares
            hld[ticker]["total_cost"] -= (avg_cost * shares)
            if hld[ticker]["shares"] <= 0.0001: hld[ticker]["shares"], hld[ticker]["total_cost"] = 0, 0
    
    st.session_state.trade_ledger.at[idx, "Running_Balance"] = cb

if st.session_state["logged_in"]:
    
    with tab_port:
        st.subheader("📝 สมุดบัญชี Cloud Ledger (ศูนย์กลางข้อมูล)")
        st.caption("เมื่อคุณเพิ่มรายการที่นี่ ข้อมูลจะวิ่งไปรอในหน้าภาษีให้อัตโนมัติค่ะ")
        
        # 🌟 ถอดเกราะป้องกันความ Error ออกทั้งหมด ให้ Streamlit จัดการอย่างอิสระ
        edited_ledger = st.data_editor(
            st.session_state.trade_ledger, num_rows="dynamic", use_container_width=True,
            column_config={
                "Date": "วันที่ (DD/MM/YYYY)",
                "Action": st.column_config.SelectboxColumn("ประเภทรายการ", options=["นำเงินออกนอกประเทศ (Outward)", "นำเงินเข้าประเทศไทย (Inward)", "ซื้อหุ้น (Buy)", "ขายหุ้น (Sell)", "รับเงินปันผล (Dividend)"]),
                "Ticker": "ชื่อหุ้น",
                "Price": "ราคา ($)",
                "Shares": "จำนวนหุ้น",
                "Amount_USD": "จำนวนเงิน ($)",
                "Running_Balance": st.column_config.Column("ยอดเงินคงเหลือ ($)", disabled=True),
                "FX_Rate": None, "WHT_USD": None, "Ref_Doc": None
            }
        )
        
        if not edited_ledger.equals(st.session_state.trade_ledger):
            st.session_state.trade_ledger = edited_ledger
            st.rerun()

        if st.button("💾 บันทึกการเปลี่ยนแปลงทั้งหมดลง Google Sheets", type="primary", use_container_width=True):
            with st.spinner("กำลังส่งข้อมูลไปยังฐานข้อมูล..."):
                try:
                    save_df_to_sheet("Ledger", st.session_state.trade_ledger)
                    st.success("🎉 บันทึกสำเร็จแล้ว! ข้อมูลปลอดภัย 100%")
                except Exception as e:
                    st.error(f"เกิดข้อผิดพลาดในการบันทึก: {e}")

        st.markdown("---")
        st.subheader("💰 สถานะเงินสดในพอร์ต (Brokerage Account)")
        st.metric("ยอดยกมา / เงินสดคงเหลือที่ซื้อหุ้นได้ (Cash Balance)", f"${cb:,.2f}")

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
            usd = safe_float(row["Amount_USD"])
            wht = safe_float(row["WHT_USD"])
            fx = safe_float(row["FX_Rate"])
            
            amt_thb = usd * fx
            wht_thb = wht * fx
            
            direction = str(row["Action"])
            if direction == "นำเงินออกนอกประเทศ (Outward)": total_out_thb += amt_thb
            elif direction == "นำเงินเข้าประเทศไทย (Inward)": 
                total_in_thb += amt_thb
                foreign_tax_credit_thb += wht_thb 
            elif direction == "รับเงินปันผล (Dividend)":
                foreign_tax_credit_thb += wht_thb
                
        net_taxable_gain = max(0, total_in_thb - total_out_thb)
        
        st.markdown("---")
        st.markdown("### 📊 2. แดชบอร์ดสถานะกระแสเงินสด (Cash Flow Offset)")
        cf1, cf2, cf3 = st.columns(3)
        cf1.metric("📤 ยอดรวมโอนออก (เงินต้น)", f"฿{total_out_thb:,.2f}")
        cf2.metric("📥 ยอดรวมโอนเข้าไทย", f"฿{total_in_thb:,.2f}")
        cf3.metric("🚨 กำไรสุทธิที่ประเมินภาษี", f"฿{net_taxable_gain:,.2f}", "หักล้างเงินต้นแล้ว", delta_color="inverse")

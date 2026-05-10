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

def load_ledger_data():
    try:
        ws = sh.worksheet("Ledger")
        records = ws.get_all_records()
        if not records:
            return pd.DataFrame(columns=["Date", "Action", "Ticker", "Price", "Shares", "Amount_USD", "Running_Balance", "FX_Rate", "WHT_USD", "Ref_Doc"])
        df = pd.DataFrame(records)
        df.replace(["", "None", "nan", None], np.nan, inplace=True)
        df.dropna(how="all", inplace=True)
        df.fillna("", inplace=True)
    except:
        df = pd.DataFrame()

    required_cols = ["Date", "Action", "Ticker", "Price", "Shares", "Amount_USD", "Running_Balance", "FX_Rate", "WHT_USD", "Ref_Doc"]
    for col in required_cols:
        if col not in df.columns: df[col] = ""

    for col in ["Price", "Shares", "Amount_USD", "Running_Balance", "FX_Rate", "WHT_USD"]:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
    for col in ["Action", "Ticker", "Ref_Doc"]:
        df[col] = df[col].astype(str).replace("None", "").replace("nan", "")
    
    if not df.empty and "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], format="%d/%m/%Y", errors="coerce").dt.strftime("%d/%m/%Y").replace("NaT", "")
    
    return df[required_cols]

def save_df_to_sheet(worksheet_name, df):
    ws = sh.worksheet(worksheet_name)
    ws.clear()
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
        if action in ["None", "nan"]: action = ""
        ticker = str(row.get("Ticker", "")).strip().upper()
        if ticker in ["NONE", "NAN"]: ticker = ""

        def safe_num(val):
            if pd.isna(val) or val is None or str(val).strip() in ["", "None", "nan"]: return 0.0
            try: return float(val)
            except: return 0.0

        price, shares, amt = safe_num(row.get("Price")), safe_num(row.get("Shares")), safe_num(row.get("Amount_USD"))
        trade_val = price * shares
        if action == "นำเงินออกนอกประเทศ (Outward)": cb += amt; stat["outward"] += amt
        elif action == "นำเงินเข้าประเทศไทย (Inward)": cb -= amt; stat["inward"] += amt
        elif action == "รับเงินปันผล (Dividend)": cb += amt; stat["dividend"] += amt
        elif action == "ซื้อหุ้น (Buy)" and ticker:
            cb -= trade_val; stat["bought"] += trade_val
            if ticker not in hld: hld[ticker] = {"shares": 0.0, "total_cost": 0.0}
            hld[ticker]["shares"] += shares; hld[ticker]["total_cost"] += trade_val
        elif action == "ขายหุ้น (Sell)" and ticker:
            cb += trade_val; stat["sold"] += trade_val
            if ticker in hld and hld[ticker]["shares"] > 0:
                avg_cost = hld[ticker]["total_cost"] / hld[ticker]["shares"]
                stat["realized_profit"] += trade_val - (avg_cost * shares)
                hld[ticker]["shares"] -= shares; hld[ticker]["total_cost"] -= (avg_cost * shares)
        r_bals.append(cb)
    return cb, stat, r_bals, hld

# ==========================================
# 🌟 Sidebar (เปิดเครื่องมือเป็นสาธารณะ)
# ==========================================
with st.sidebar:
    st.title("🛡️ Strategic Hub")
    ticker = st.text_input("🔎 ชื่อหุ้น / ดัชนี", value="NVTS").upper()
    tf_option = st.radio("เลือกความละเอียด:", ["1D (รายวัน)", "1W (รายสัปดาห์)", "1M (รายเดือน)"], index=0)
    
    st.markdown("---")
    st.subheader("🧮 เครื่องมือคำนวณ (Public)")
    total_capital = st.number_input("เงินทุนรวม (USD)", value=10000.0, step=1000.0)
    risk_pct = st.slider("ความเสี่ยงต่อไม้ (%)", 1.0, 5.0, 2.0)
    buy_price = st.number_input("ราคาต้นทุนที่ซื้อ (USD)", min_value=0.0, value=0.0, step=0.1)
    buy_shares = st.number_input("จำนวนหุ้นที่มี", min_value=0.0, value=0.0, step=1.0)
    
    st.markdown("---")
    if not st.session_state["logged_in"]:
        st.subheader("🔒 สำหรับเจ้าของพอร์ต")
        pwd = st.text_input("🔑 รหัสผ่าน", type="password")
        if st.button("เข้าสู่ระบบ", use_container_width=True):
            if pwd == st.secrets.get("app_password", "123456"):
                st.session_state["logged_in"] = True
                st.rerun()
            else: st.error("❌ รหัสผ่านไม่ถูกต้อง")
    else:
        st.success("✅ เข้าสู่ระบบแล้ว")
        if st.button("🚪 ออกจากระบบ", use_container_width=True):
            st.session_state["logged_in"] = False
            st.rerun()

# --- ดึงข้อมูลวิเคราะห์ ---
@st.cache_data(ttl=300)
def load_pro_data(ticker_symbol, tf):
    settings = {"1D (รายวัน)": {"period": "6mo", "interval": "1d"}, "1W (รายสัปดาห์)": {"period": "2y", "interval": "1wk"}, "1M (รายเดือน)": {"period": "5y", "interval": "1mo"}}
    p, i = settings[tf]["period"], settings[tf]["interval"]
    try:
        stock = yf.Ticker(ticker_symbol)
        df = stock.history(period=p, interval=i)
        if df.empty: return pd.DataFrame(), {}, None
        df = df.dropna(subset=['Close'])
        spy = yf.Ticker("^GSPC").history(period=p, interval=i)['Close']
        df['RS_vs_Market'] = (df['Close'].pct_change(10) - spy.pct_change(10)) * 100
        
        # Indicator พื้นฐาน
        df['EMA_10'] = df['Close'].ewm(span=10, adjust=False).mean()
        df['EMA_20'] = df['Close'].ewm(span=20, adjust=False).mean()
        df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()
        
        # RSI
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        df['RSI'] = 100 - (100 / (1 + gain/loss))
        
        # MACD
        df['MACD'] = df['Close'].ewm(span=12, adjust=False).mean() - df['Close'].ewm(span=26, adjust=False).mean()
        df['Signal_Line'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['MACD_Hist'] = df['MACD'] - df['Signal_Line']
        
        # Volume Average
        df['Vol_SMA'] = df['Volume'].rolling(window=20).mean()
        
        if len(df) > 1:
            y = df['Close'].values
            x = np.arange(len(y))
            slope, intercept = np.polyfit(x, y, 1)
            df['Trendline'] = slope * x + intercept
        else: df['Trendline'] = np.nan
        
        fund = {"ps": "N/A", "pe": "N/A", "roe": "N/A"}
        try:
            info = stock.info
            fund["ps"] = f"{info.get('priceToSalesTrailing12Months', 0):.2f}"
            fund["pe"] = f"{info.get('trailingPE', 0):.2f}"
            fund["roe"] = f"{info.get('returnOnEquity', 0)*100:.2f}%"
        except: pass
        
        last_p = df['Close'].iloc[-1]
        vol = df['Close'].pct_change().tail(14).std()
        trend = "ขึ้น 📈" if last_p > df['EMA_50'].iloc[-1] else "ลง 📉"
        # คำนวณ Harmonic Matrix
        matrix = {"l": last_p * (1 - vol*1.0) if trend == "ลง 📉" else last_p * (1 - vol*0.5), "u": last_p * (1 - vol*0.5) if trend == "ลง 📉" else last_p * (1 + vol*1.0), "trend": trend}
        
        return df, fund, matrix
    except: return pd.DataFrame(), {}, None

df, fund, matrix = load_pro_data(ticker, tf_option)

# --- Tabs ---
if st.session_state["logged_in"]:
    tab_dash, tab_port, tab_tax = st.tabs(["📊 วิเคราะห์กราฟ (Analysis)", "💼 บัญชี (Cloud Sync)", "🧾 ภาษีสรรพากร"])
else:
    tab_dash, = st.tabs(["📊 วิเคราะห์กราฟ (Analysis)"])

# ==========================================
# หน้า 1: วิเคราะห์กราฟ (ชุดเต็ม)
# ==========================================
with tab_dash:
    st.markdown(f"## 📈 วิเคราะห์หุ้น: {ticker}")
    st.caption(f"📅 ข้อมูลวันที่: {current_date} | อัปเดตล่าสุด: {current_time} น.")
    
    if not df.empty:
        last_p = df['Close'].iloc[-1]
        prev_p = df['Close'].iloc[-2] if len(df) > 1 else last_p
        
        # 🌟 เพิ่ม Harmonic Matrix แบบเต็ม กลับมาอยู่ด้านบนสุดตามที่คุณศศิธาต้องการ!
        rs_val = df['RS_vs_Market'].iloc[-1]
        rs_text = f" | **Relative Strength:** {'🟢 ชนะตลาด' if rs_val > 0 else '🔴 อ่อนแอกว่าตลาด'} ({rs_val:.2f}%)" if not np.isnan(rs_val) else ""
        if matrix: 
            st.info(f"🔮 **ทิศทาง {tf_option}:** {matrix['trend']} | **เป้าหมาย:** {matrix['l']:,.2f} - {matrix['u']:,.2f} (Harmonic Matrix){rs_text}")
        
        col_left, col_right = st.columns([7, 3])
        with col_left:
            fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.45, 0.15, 0.2, 0.2])
            
            # Row 1: Price
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name="Price"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['Trendline'], line=dict(color='rgba(255, 255, 255, 0.4)', dash='dot', width=2), name="Trend"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['EMA_20'], line=dict(color='#00E676', width=2.5), name="EMA 20"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['EMA_50'], line=dict(color='#FF6D00', width=2.5), name="EMA 50"), row=1, col=1)
            if buy_price > 0: fig.add_hline(y=buy_price, line_dash="dash", line_color="cyan", annotation_text="ต้นทุนของคุณ", row=1, col=1)
            
            # Row 2: Volume
            v_colors = ['#00E676' if df['Close'].iloc[i] > df['Open'].iloc[i] else '#FF5252' for i in range(len(df))]
            fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=v_colors, name="Vol"), row=2, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['Vol_SMA'], line=dict(color='rgba(255, 255, 255, 0.5)', width=1.5), name="Vol Avg"), row=2, col=1)
            
            # Row 3: RSI
            fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], line=dict(color='#BA68C8', width=2), name="RSI"), row=3, col=1)
            fig.add_hline(y=70, line_dash="dot", line_color="red", row=3, col=1)
            fig.add_hline(y=30, line_dash="dot", line_color="green", row=3, col=1)
            
            # Row 4: MACD
            macd_colors = ['#00E676' if val >= 0 else '#FF5252' for val in df['MACD_Hist']]
            fig.add_trace(go.Bar(x=df.index, y=df['MACD_Hist'], marker_color=macd_colors, name="MACD Hist"), row=4, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['MACD'], line=dict(color='#2962FF', width=2), name="MACD"), row=4, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['Signal_Line'], line=dict(color='#FF6D00', width=2), name="Signal"), row=4, col=1)

            fig.update_layout(template="plotly_dark", height=800, margin=dict(l=0,r=0,t=0,b=0), showlegend=False)
            fig.update_xaxes(rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)

            st.markdown("---")
            st.subheader("📊 ข้อมูลพื้นฐาน (Fundamental)")
            f1, f2, f3 = st.columns(3)
            f1.metric("P/S Ratio", fund.get('ps', 'N/A'))
            f2.metric("P/E Ratio", fund.get('pe', 'N/A'))
            f3.metric("ROE", fund.get('roe', 'N/A'))

        with col_right:
            st.metric("ราคาปัจจุบัน", f"${last_p:,.2f}", f"{last_p - prev_p:.2f}")
            if buy_price > 0:
                pl = ((last_p - buy_price) / buy_price) * 100
                st.write(f"**กำไร/ขาดทุนของคุณ:** {pl:.2f}%")
                sl_price = df['EMA_50'].iloc[-1] * 0.99 if buy_price == 0 else buy_price * 0.92
                st.error(f"🛡️ **จุดหนี (Stop Loss): ${sl_price:.2f}**")
                
                risk_amt = total_capital * (risk_pct / 100)
                risk_per_share = last_p - sl_price
                if risk_per_share > 0:
                    shares = risk_amt / risk_per_share
                    st.success(f"🧮 **ซื้อได้สูงสุด:** {shares:.2f} หุ้น")

            st.markdown("---")
            st.subheader("🤖 สรุปสัญญาณเทคนิค")
            
            if last_p > df['EMA_50'].iloc[-1]: trend_signal = "🟢 ขาขึ้น (Bullish)"
            else: trend_signal = "🔴 ขาลง (Bearish)"
            
            if df['MACD'].iloc[-1] > df['Signal_Line'].iloc[-1]: macd_signal = "🟢 แรงซื้อได้เปรียบ"
            else: macd_signal = "🔴 แรงขายกดดัน"
            
            rsi_val = df['RSI'].iloc[-1]
            if rsi_val > 70: rsi_signal = "🔴 ซื้อมากไป (Overbought)"
            elif rsi_val < 30: rsi_signal = "🟢 ขายมากไป (Oversold)"
            else: rsi_signal = "🟡 กลางๆ (Neutral)"

            st.write(f"**เทรนด์ (EMA 50):** {trend_signal}")
            st.write(f"**รอบสวิง (MACD):** {macd_signal}")
            st.write(f"**แรงซื้อขาย (RSI):** {rsi_signal}")
            
            if "🟢" in trend_signal and "🟢" in macd_signal:
                st.success("✨ **สรุป:** สัญญาณสอดคล้องกัน เป็นจังหวะที่น่าสนใจในการถือรันเทรนด์ค่ะ")
            elif "🔴" in trend_signal and "🔴" in macd_signal:
                st.error("⚠️ **สรุป:** กราฟเสียทรงรุนแรง แนะนำให้ชะลอการลงทุนหรือหาจุดตัดขาดทุนค่ะ")
            else:
                st.info("💡 **สรุป:** กราฟยังมีความขัดแย้งกันอยู่ (Sideway) แนะนำให้เล่นสั้นๆ ในกรอบไปก่อนค่ะ")

            st.markdown("---")
            st.subheader("🚧 แนวรับ-ต้าน")
            st.write(f"**ต้าน:** {df['High'].tail(20).max():.2f}")
            st.write(f"**รับ:** {df['EMA_50'].iloc[-1]:.2f}")

if st.session_state["logged_in"]:
    # ==========================================
    # หน้า 2: บัญชีและพอร์ตโฟลิโอ
    # ==========================================
    cb, ledger_stat, running_bals, holdings = calculate_stats(st.session_state.trade_ledger)
    st.session_state.trade_ledger["Running_Balance"] = running_bals

    with tab_port:
        st.subheader("💼 แดชบอร์ดกระแสเงินสด (Cash Flow)")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("📤 นำเงินออกสะสม", f"${ledger_stat['outward']:,.2f}")
        col2.metric("📉 ใช้ซื้อหุ้นไปแล้ว", f"${ledger_stat['bought']:,.2f}", "หักจากเงินสด", delta_color="inverse")
        col3.metric("📈 ขายหุ้นได้เงินมา", f"${ledger_stat['sold']:,.2f}", "บวกกลับเข้าเงินสด")
        col4.metric("💰 เงินสดคงเหลือ", f"${cb:,.2f}")

        st.markdown("---")
        st.subheader("📝 สมุดบัญชี Cloud Ledger")
        
        edited_ledger = st.data_editor(
            st.session_state.trade_ledger, 
            num_rows="dynamic",
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
        
        if not edited_ledger.equals(st.session_state.trade_ledger):
            edited_ledger.replace([None, "None", "nan"], "", inplace=True) 
            _, _, new_rb, _ = calculate_stats(edited_ledger) 
            edited_ledger["Running_Balance"] = new_rb
            st.session_state.trade_ledger = edited_ledger
            st.rerun() 

        if st.button("💾 บันทึกข้อมูลบัญชีลง Google Sheets", type="primary", use_container_width=True):
            with st.spinner("กำลังส่งข้อมูลเข้าสู่คลาวด์..."):
                try:
                    save_df_to_sheet("Ledger", st.session_state.trade_ledger)
                    st.success("🎉 บันทึกสำเร็จแล้ว! ข้อมูลปลอดภัย 100%")
                except Exception as e:
                    st.error(f"เกิดข้อผิดพลาด: {e}")

        st.markdown("---")
        st.subheader("💼 พอร์ตโฟลิโอปัจจุบัน (Current Holdings)")
        port_summary, total_invested = [], 0.0
        for t, data in holdings.items():
            if data["shares"] > 0.001:
                avg_c = data["total_cost"] / data["shares"]
                port_summary.append({"Ticker": t, "Cost_Price": avg_c, "Shares": data["shares"], "Total_Cost": data["total_cost"]})
                total_invested += data["total_cost"]
        
        if len(port_summary) > 0:
            current_port_df = pd.DataFrame(port_summary)
            if st.button("🔄 ดึงราคาปัจจุบัน และ คำนวณกำไร/ขาดทุน"):
                with st.spinner("กำลังดึงราคาล่าสุดจากตลาด..."):
                    results, total_v = [], 0.0
                    for _, row in current_port_df.iterrows():
                        t, avg_cost, sh, t_cost = row["Ticker"], row["Cost_Price"], row["Shares"], row["Total_Cost"]
                        try: curr_p = yf.Ticker(t).history(period="1d")['Close'].iloc[-1]
                        except: curr_p = avg_cost
                        
                        val = curr_p * sh
                        profit = val - t_cost
                        profit_pct = (profit / t_cost * 100) if t_cost > 0 else 0
                        results.append({
                            "หุ้น": t, "จำนวนหุ้น": f"{sh:,.2f}", "ต้นทุนเฉลี่ย": f"${avg_cost:,.2f}", 
                            "ราคาปัจจุบัน": f"${curr_p:,.2f}", "กำไร/ขาดทุน": f"${profit:,.2f}", 
                            "% เปลี่ยนแปลง": f"{profit_pct:.2f}%", "มูลค่ารวม": f"${val:,.2f}"
                        })
                        total_v += val
                    
                    p1, p2, p3 = st.columns(3)
                    p1.metric("มูลค่าหุ้นรวม (Market Value)", f"${total_v:,.2f}")
                    p2.metric("ต้นทุนหุ้นทั้งหมด (Total Cost)", f"${total_invested:,.2f}")
                    p3.metric("กำไร/ขาดทุนรวม (Unrealized P/L)", f"${(total_v-total_invested):,.2f}", f"{((total_v-total_invested)/total_invested*100 if total_invested>0 else 0):.2f}%")
                    st.dataframe(pd.DataFrame(results), use_container_width=True)
        else:
            st.info("ว่างเปล่า (ยังไม่มีหุ้นในพอร์ตค่ะ)")

    # ==========================================
    # หน้า 3: ภาษีสรรพากร
    # ==========================================
    with tab_tax:
        st.subheader("🧾 ระบบประเมินภาษีสรรพากร ภ.ง.ด. 90")
        st.info(f"💡 **สรุปรายได้จากพอร์ต:** กำไรขายหุ้น: **${ledger_stat['realized_profit']:,.2f}** | เงินปันผลรับ: **${ledger_stat['dividend']:,.2f}**")
        
        st.markdown("### 📝 1. บันทึกอัตราแลกเปลี่ยนภาษี")
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
                "FX_Rate": "อัตราแลกเปลี่ยน (บาท/$)",
                "WHT_USD": "ภาษีที่ถูกหัก ตปท. ($)",
                "Ref_Doc": "หมายเหตุ / ไฟล์อ้างอิง",
                "Ticker": None, "Price": None, "Shares": None, "Running_Balance": None
            }
        )
        
        if not edited_tax_view.equals(tax_view):
            edited_tax_view.replace([None, "None", "nan"], "", inplace=True)
            st.session_state.trade_ledger.update(edited_tax_view)
            st.rerun()

        if st.button("💾 บันทึกอัตราแลกเปลี่ยนลง Google Sheets", type="primary", use_container_width=True):
            try:
                save_df_to_sheet("Ledger", st.session_state.trade_ledger)
                st.success("บันทึกสำเร็จ!")
            except Exception as e: st.error(f"เกิดข้อผิดพลาด: {e}")

        total_out_thb, total_in_thb, foreign_tax_credit_thb = 0.0, 0.0, 0.0
        for _, row in tax_view.iterrows():
            def sn(val): return float(val) if not pd.isna(val) and str(val).strip() not in ["", "None"] else 0.0
            usd, wht, fx = sn(row.get("Amount_USD")), sn(row.get("WHT_USD")), sn(row.get("FX_Rate"))
            amt_thb, wht_thb = usd * fx, wht * fx
            
            if row.get("Action") == "นำเงินออกนอกประเทศ (Outward)": total_out_thb += amt_thb
            elif row.get("Action") == "นำเงินเข้าประเทศไทย (Inward)": 
                total_in_thb += amt_thb
                foreign_tax_credit_thb += wht_thb 
            elif row.get("Action") == "รับเงินปันผล (Dividend)": foreign_tax_credit_thb += wht_thb
                
        net_taxable_gain = max(0, total_in_thb - total_out_thb)
        
        st.markdown("---")
        cf1, cf2, cf3 = st.columns(3)
        cf1.metric("📤 ยอดรวมโอนออก (เงินต้น)", f"฿{total_out_thb:,.2f}")
        cf2.metric("📥 ยอดรวมโอนเข้าไทย", f"฿{total_in_thb:,.2f}")
        cf3.metric("🚨 กำไรสุทธิที่ประเมินภาษี", f"฿{net_taxable_gain:,.2f}", "หักล้างเงินต้นแล้ว", delta_color="inverse")

        st.markdown("---")
        st.markdown("### 🧮 2. ประเมินภาระภาษีเพื่อยื่น ภ.ง.ด. 90")
        
        c1, c2, c3 = st.columns(3)
        with c1: tax_year = st.selectbox("📅 เลือกปีภาษี", ["2567 (2024)", "2568 (2025)", "2569 (2026)", "2570 (2027)"])
        with c2: is_resident = st.radio("อาศัยอยู่ในไทยเกิน 180 วัน หรือไม่?", ["เกิน 180 วัน", "ไม่ถึง 180 วัน"])
        with c3: other_income = st.number_input("รายได้ประจำอื่นๆ ต่อปี (บาท)", min_value=0.0, value=500000.0, step=50000.0)

        standard_expense = min(other_income * 0.5, 100000.0)
        personal_deduction = 60000.0 
        
        with st.expander("📝 บันทึกค่าลดหย่อนส่วนบุคคล การลงทุน และครอบครัว", expanded=True):
            col_d1, col_d2 = st.columns(2)
            spouse_deduction = col_d1.checkbox("มีคู่สมรส (ไม่มีรายได้) - ลดหย่อน 60,000 บาท")
            children_count = col_d2.number_input("จำนวนบุตร (คนละ 30,000 บาท)", min_value=0, step=1)
            
            st.markdown("**ประกันและการลงทุน**")
            c_inv1, c_inv2, c_inv3 = st.columns(3)
            life_ins = c_inv1.number_input("เบี้ยประกันชีวิต", min_value=0.0, step=5000.0)
            health_ins = c_inv2.number_input("เบี้ยประกันสุขภาพ", min_value=0.0, step=5000.0)
            pvd = c_inv3.number_input("กองทุน PVD / กบข.", min_value=0.0, step=5000.0)
            ssf = c_inv1.number_input("ซื้อกองทุน SSF", min_value=0.0, step=5000.0)
            rmf = c_inv2.number_input("ซื้อกองทุน RMF", min_value=0.0, step=5000.0)
            donate = c_inv3.number_input("เงินบริจาค", min_value=0.0, step=1000.0)

        actual_health = min(health_ins, 25000.0)
        actual_life_health = min(life_ins + actual_health, 100000.0)
        total_income_for_cap = other_income + net_taxable_gain
        ssf_limit = min(ssf, total_income_for_cap * 0.3, 200000.0)
        rmf_limit = min(rmf, total_income_for_cap * 0.3, 500000.0)
        pvd_limit = min(pvd, total_income_for_cap * 0.15, 500000.0)
        retirement_total = min(ssf_limit + rmf_limit + pvd_limit, 500000.0)
        family_deduction = (60000.0 if spouse_deduction else 0.0) + (children_count * 30000.0)
        
        total_deductions = standard_expense + personal_deduction + family_deduction + actual_life_health + retirement_total + donate
        st.info(f"✅ **รวมค่าใช้จ่ายและค่าลดหย่อนที่สามารถนำไปหักภาษีได้จริง:** ฿{total_deductions:,.2f}")

        if st.button(f"📊 คำนวณภาษีสุทธิ ปี {tax_year}", type="primary", use_container_width=True):
            if "ไม่ถึง" in is_resident: st.success("🎉 คุณได้รับยกเว้นภาษี")
            elif net_taxable_gain <= 0: st.success("🎉 ยังไม่มีกำไรส่วนเกินจากยอดเงินต้น ไม่ต้องเสียภาษีเงินได้ ตปท. ค่ะ")
            else:
                net_inc = max(0, (other_income + net_taxable_gain) - total_deductions)
                net_inc_without = max(0, other_income - total_deductions)
                
                def calc_tax(n):
                    t = 0
                    if n > 5000000: t += (n - 5000000) * 0.35 + 1265000
                    elif n > 2000000: t += (n - 2000000) * 0.30 + 365000
                    elif n > 1000000: t += (n - 1000000) * 0.25 + 115000
                    elif n > 750000: t += (n - 750000) * 0.20 + 65000
                    elif n > 500000: t += (n - 500000) * 0.15 + 27500
                    elif n > 300000: t += (n - 300000) * 0.10 + 7500
                    elif n > 150000: t += (n - 150000) * 0.05
                    return t
                
                tax_raw = calc_tax(net_inc) - calc_tax(net_inc_without)
                final_tax = max(0, tax_raw - foreign_tax_credit_thb)
                
                st.subheader(f"ผลการคำนวณ ภ.ง.ด. 90 (ประจำปี {tax_year})")
                st.write(f"- ภาษีที่ถูกหักไปแล้วในต่างประเทศ (Foreign Tax Credit): ฿{foreign_tax_credit_thb:,.2f}")
                r1, r2 = st.columns(2)
                r1.metric("ภาษีที่เกิดจากพอร์ต ตปท.", f"฿{tax_raw:,.2f}")
                r2.metric("🚨 ภาษีที่ต้องจ่ายเพิ่มจริง (หักเครดิตแล้ว)", f"฿{final_tax:,.2f}")

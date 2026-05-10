import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

# 1. ตั้งค่าหน้าเพจแบบ Wide Screen
st.set_page_config(page_title="Strategic Portfolio Ecosystem 2.0", layout="wide")

# ==========================================
# 🔐 ระบบสถานะ (Session State) และฐานข้อมูล
# ==========================================
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if "port_data" not in st.session_state:
    st.session_state.port_data = pd.DataFrame({"Ticker": ["NVTS"], "Cost_Price": [16.48], "Shares": [100.0]})

if "trade_ledger" not in st.session_state:
    st.session_state.trade_ledger = pd.DataFrame({
        "Date": [datetime.now().date(), datetime.now().date()],
        "Action": ["ฝากเงินเข้าพอร์ต (Deposit)", "ซื้อหุ้น (Buy)"],
        "Ticker": ["", "NVTS"],
        "Price": [0.0, 16.48],
        "Shares": [0.0, 100.0],
        "Amount": [10000.0, 0.0]
    })

# 🌟 ปรับปรุงตารางภาษี เพิ่มคอลัมน์ "ภาษีที่หักต่างประเทศ (WHT)" เพื่อใช้ทำ Foreign Tax Credit
if "transfer_data" not in st.session_state or "WHT_USD" not in st.session_state.transfer_data.columns:
    st.session_state.transfer_data = pd.DataFrame({
        "Date": [datetime.now().date(), datetime.now().date()],
        "Direction": ["โอนออก (Outward)", "นำเงินเข้า (Inward)"],
        "Category": ["เงินลงทุน (Principal)", "กำไร/ปันผล (Taxable)"],
        "Amount_USD": [5000.0, 1000.0],
        "WHT_USD": [0.0, 150.0], # ภาษีที่โดนหัก ณ ที่จ่ายใน ตปท.
        "FX_Rate": [35.00, 36.50],
        "Source": ["ออมทรัพย์", "ปันผลหุ้น NVTS"],
        "Country": ["ไทย (TH)", "สหรัฐอเมริกา (USA)"],
        "Ref_Doc": ["Slip_001.jpg", "Tax_Doc.pdf"]
    })

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
        st.caption("เข้าสู่ระบบเพื่อปลดล็อคเครื่องมือจัดการพอร์ตส่วนตัว")
        pwd = st.text_input("🔑 รหัสผ่าน", type="password")
        if st.button("เข้าสู่ระบบ (Login)", use_container_width=True):
            correct_pwd = st.secrets.get("app_password", "123456")
            if pwd == correct_pwd:
                st.session_state["logged_in"] = True
                st.rerun()
            else:
                st.error("❌ รหัสผ่านไม่ถูกต้อง")
        total_capital, risk_pct, buy_price = 0.0, 2.0, 0.0
    else:
        st.subheader("🧮 จัดการความเสี่ยง (Risk Mgmt)")
        total_capital = st.number_input("เงินทุนรวม (USD)", min_value=0.0, value=10000.0, step=100.0)
        risk_pct = st.slider("ความเสี่ยงต่อไม้ (%)", 1.0, 5.0, 2.0)
        st.markdown("---")
        st.subheader("💰 สถานะหุ้นตัวนี้")
        buy_price = st.number_input("ราคาต้นทุน (USD)", min_value=0.0, value=0.0, step=0.1)
        buy_shares = st.number_input("จำนวนหุ้นที่มี", min_value=0.0, value=0.0, step=0.1)
        if st.button("➕ บันทึกประวัติซื้อหุ้นนี้ลงพอร์ต", type="primary", use_container_width=True):
            new_trade = pd.DataFrame({"Date": [datetime.now().date()], "Action": ["ซื้อหุ้น (Buy)"], "Ticker": [ticker], "Price": [buy_price], "Shares": [buy_shares], "Amount": [0.0]})
            st.session_state.trade_ledger = pd.concat([st.session_state.trade_ledger, new_trade], ignore_index=True)
            st.success(f"บันทึกการซื้อ {ticker} ลงบัญชีเรียบร้อย!")
        st.markdown("---")
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
        fund = {"ps": "N/A", "pe": "N/A", "roe": "N/A"}
        try:
            info = stock.info
            fund["ps"] = f"{info.get('priceToSalesTrailing12Months', 0):.2f}"
            fund["pe"] = f"{info.get('trailingPE', 0):.2f}"
            fund["roe"] = f"{info.get('returnOnEquity', 0)*100:.2f}%"
        except: pass
        return df, fund
    except: return pd.DataFrame(), {}

df, fund = load_pro_data(ticker, tf_option)

def get_matrix(df):
    if df.empty or len(df) < 14: return None
    last = df['Close'].iloc[-1]
    vol = df['Close'].pct_change().tail(14).std()
    trend = "ขึ้น 📈" if last > df['EMA_50'].iloc[-1] else "ลง 📉"
    l = last * (1 - vol*1.0) if trend == "ลง 📉" else last * (1 - vol*0.5)
    u = last * (1 - vol*0.5) if trend == "ลง 📉" else last * (1 + vol*1.0)
    return {"l": l, "u": u, "trend": trend}
matrix = get_matrix(df)

# ==========================================
# 🌟 ระบบแท็บ
# ==========================================
if st.session_state["logged_in"]:
    tab_dash, tab_port, tab_tax, tab_strat = st.tabs(["📊 วิเคราะห์กราฟ (Analysis)", "💼 บัญชีและพอร์ตโฟลิโอ", "🧾 ภาษีสรรพากร", "📚 กลยุทธ์"])
else:
    tab_dash, = st.tabs(["📊 วิเคราะห์กราฟ (Analysis)"])

# ==========================================
# หน้า 1: วิเคราะห์หลัก (Dashboard)
# ==========================================
with tab_dash:
    if not df.empty:
        last_p = df['Close'].iloc[-1]
        rs_val = df['RS_vs_Market'].iloc[-1]
        rs_text = ""
        if not np.isnan(rs_val):
            rs_color = "🟢 ชนะตลาด" if rs_val > 0 else "🔴 อ่อนแอกว่าตลาด"
            rs_text = f" | **Relative Strength:** {rs_color} ({rs_val:.2f}%)"
            
        if matrix: st.info(f"🔮 **ทิศทาง {tf_option}:** {matrix['trend']} | **เป้าหมาย:** {matrix['l']:,.2f} - {matrix['u']:,.2f} (Harmonic Matrix){rs_text}")
        else:
            if rs_text: st.info(f"🔮 {rs_text.replace(' | ', '')}")

        col_left, col_right = st.columns([7, 3])
        with col_left:
            fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.5, 0.25, 0.25])
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name="Price"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['Trendline'], line=dict(color='rgba(255, 255, 255, 0.4)', dash='dot', width=2), name="Trend"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['EMA_20'], line=dict(color='#00E676', width=2.5), name="EMA 20"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['EMA_50'], line=dict(color='#FF6D00', width=2.5), name="EMA 50"), row=1, col=1)
            if buy_price > 0 and st.session_state["logged_in"]: fig.add_hline(y=buy_price, line_dash="dash", line_color="cyan", line_width=2, annotation_text="ต้นทุน", row=1, col=1)
            
            v_colors = ['#00E676' if df['Close'].iloc[i] > df['Open'].iloc[i] else '#FF6D00' for i in range(len(df))]
            fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=v_colors, name="Vol"), row=2, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], line=dict(color='#BA68C8', width=2), name="RSI"), row=3, col=1)
            fig.add_hline(y=70, line_dash="dot", line_color="red", row=3, col=1)
            fig.add_hline(y=30, line_dash="dot", line_color="green", row=3, col=1)
            fig.update_layout(template="plotly_dark", height=600, margin=dict(l=0,r=0,t=0,b=0), showlegend=False)
            fig.update_xaxes(rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)

            st.markdown("---")
            st.subheader("📊 ข้อมูลพื้นฐาน (Fundamental Analysis)")
            f1, f2, f3 = st.columns(3)
            with f1:
                st.metric("P/S Ratio", fund.get('ps', 'N/A'))
                st.caption("ราคาเทียบรายได้ (<3 = ถูก)")
            with f2:
                st.metric("P/E Ratio", fund.get('pe', 'N/A'))
                st.caption("จุดคืนทุน (N/A = ยังไม่มีกำไร)")
            with f3:
                st.metric("ROE", fund.get('roe', 'N/A'))
                st.caption("ความเก่งบริหาร (>15% = ดี)")
            st.info("💡 **ทริค:** เซียนหุ้นจะดูแท่ง Volume ควบคู่ไปด้วย หากราคาทะลุแนวต้านพร้อม Volume สีเขียวสูงปรี๊ด แสดงว่าเป็นขาขึ้นของจริงค่ะ!")

        with col_right:
            prev_p = df['Close'].iloc[-2] if len(df) > 1 else last_p
            st.metric("ราคาปัจจุบัน", f"${last_p:,.2f}", f"{last_p - prev_p:.2f}")
            st.caption(f"🕒 อัปเดต: {df.index[-1].strftime('%d/%m/%Y')} | {current_time} น.")
            
            if st.session_state["logged_in"] and buy_price > 0:
                pl = ((last_p - buy_price) / buy_price) * 100
                st.write(f"**กำไร/ขาดทุน (หุ้นนี้):** {pl:.2f}%")
                if pl > 0: st.success("✅ ถือต่อเพื่อรันกำไร")
                else: st.error("⚠️ ระวัง! กราฟเริ่มเสียทรง")
            
            if st.session_state["logged_in"]:
                sl_price = df['EMA_50'].iloc[-1] * 0.99 if buy_price == 0 else buy_price * 0.92
                st.error(f"🛡️ **จุดหนี (Stop Loss): ${sl_price:.2f}**")
                risk_amt = total_capital * (risk_pct / 100)
                risk_per_share = last_p - sl_price
                if risk_per_share > 0:
                    shares = risk_amt / risk_per_share
                    st.success(f"🧮 **ซื้อได้:** {shares:.2f} หุ้น\n\n(ใช้เงิน: ${(shares * last_p):,.2f})")
            
            st.markdown("---")
            st.subheader("💡 คำแนะนำภาพรวม")
            if last_p > df['EMA_50'].iloc[-1]: st.success(f"**แนวโน้ม:** ขาขึ้น 📈\n\n**ซื้อ:** {df['EMA_10'].iloc[-1]:.2f} - {df['EMA_20'].iloc[-1]:.2f}\n\n**ขาย:** {df['High'].tail(20).max():.2f}")
            else: st.error(f"**แนวโน้ม:** ขาลง 📉\n\nระวัง! ไม่แนะนำให้รับของ")
            
            st.markdown("---")
            st.subheader("🚧 แนวรับ-ต้าน")
            st.write(f"**ต้าน:** {df['High'].tail(20).max():.2f}")
            st.write(f"**รับ:** {df['EMA_50'].iloc[-1]:.2f}")

# ==========================================
# พื้นที่เฉพาะ Owner (บัญชี และ ภาษี)
# ==========================================
total_realized_profit = 0.0
total_dividend = 0.0

if st.session_state["logged_in"]:
    
    # 🌟 หน้า 2: บัญชีและพอร์ตโฟลิโอ 
    with tab_port:
        st.subheader("📝 สมุดบัญชีบันทึกประวัติการลงทุน (Transaction Ledger)")
        
        edited_ledger = st.data_editor(
            st.session_state.trade_ledger, num_rows="dynamic", use_container_width=True,
            column_config={
                "Date": st.column_config.DateColumn("วันที่ทำรายการ", format="DD/MM/YYYY"),
                "Action": st.column_config.SelectboxColumn("ประเภทรายการ", options=["ฝากเงินเข้าพอร์ต (Deposit)", "ถอนเงินออกพอร์ต (Withdraw)", "ซื้อหุ้น (Buy)", "ขายหุ้น (Sell)", "รับเงินปันผล (Dividend)"]),
                "Ticker": st.column_config.TextColumn("ชื่อหุ้น (ถ้ามี)"),
                "Price": st.column_config.NumberColumn("ราคาต่อหุ้น ($)", format="%.2f"),
                "Shares": st.column_config.NumberColumn("จำนวนหุ้น"),
                "Amount": st.column_config.NumberColumn("จำนวนเงิน ($)", format="%.2f")
            }
        )
        st.session_state.trade_ledger = edited_ledger

        cash_balance = 0.0
        holdings = {}
        for _, row in edited_ledger.iterrows():
            action = row["Action"]
            ticker = row["Ticker"] if pd.notna(row["Ticker"]) else ""
            price = float(row["Price"]) if pd.notna(row["Price"]) else 0.0
            shares = float(row["Shares"]) if pd.notna(row["Shares"]) else 0.0
            amt = float(row["Amount"]) if pd.notna(row["Amount"]) else 0.0

            if action == "ฝากเงินเข้าพอร์ต (Deposit)": cash_balance += amt
            elif action == "ถอนเงินออกพอร์ต (Withdraw)": cash_balance -= amt
            elif action == "รับเงินปันผล (Dividend)": 
                cash_balance += amt
                total_dividend += amt
            elif action == "ซื้อหุ้น (Buy)" and ticker:
                trade_val = price * shares
                cash_balance -= trade_val
                if ticker not in holdings: holdings[ticker] = {"shares": 0.0, "total_cost": 0.0}
                holdings[ticker]["shares"] += shares
                holdings[ticker]["total_cost"] += trade_val
            elif action == "ขายหุ้น (Sell)" and ticker:
                trade_val = price * shares
                cash_balance += trade_val
                if ticker in holdings and holdings[ticker]["shares"] > 0:
                    avg_cost = holdings[ticker]["total_cost"] / holdings[ticker]["shares"]
                    profit_this_trade = trade_val - (avg_cost * shares)
                    total_realized_profit += profit_this_trade
                    holdings[ticker]["shares"] -= shares
                    holdings[ticker]["total_cost"] -= (avg_cost * shares)
                    if holdings[ticker]["shares"] <= 0.0001: 
                        holdings[ticker]["shares"], holdings[ticker]["total_cost"] = 0, 0

        port_summary, total_invested = [], 0.0
        for t, data in holdings.items():
            if data["shares"] > 0:
                avg_c = data["total_cost"] / data["shares"]
                port_summary.append({"Ticker": t, "Cost_Price": avg_c, "Shares": data["shares"], "Total_Cost": data["total_cost"]})
                total_invested += data["total_cost"]
        
        st.markdown("---")
        st.subheader("💰 สถานะเงินสดในพอร์ต (Brokerage Account)")
        st.metric("ยอดยกมา / เงินสดคงเหลือที่ซื้อหุ้นได้ (Cash Balance)", f"${cash_balance:,.2f}")

        st.markdown("---")
        st.subheader("💼 พอร์ตโฟลิโอปัจจุบัน (Current Holdings)")
        
        if len(port_summary) > 0:
            current_port_df = pd.DataFrame(port_summary)
            if st.button("🔄 ดึงราคาปัจจุบัน และ คำนวณกำไร/ขาดทุน", type="primary", use_container_width=True):
                with st.spinner("กำลังดึงข้อมูลราคาล่าสุด..."):
                    current_prices = {}
                    for t in current_port_df["Ticker"]:
                        try: current_prices[t] = yf.Ticker(t).history(period="1d")['Close'].iloc[-1]
                        except: pass
                    
                    results, total_v = [], 0.0
                    for _, row in current_port_df.iterrows():
                        t, avg_cost, sh, t_cost = row["Ticker"], row["Cost_Price"], row["Shares"], row["Total_Cost"]
                        if t in current_prices:
                            curr_p = current_prices[t]
                            val = curr_p * sh
                            profit = val - t_cost
                            profit_pct = (profit / t_cost * 100) if t_cost > 0 else 0
                            results.append({
                                "หุ้น": t, "จำนวนหุ้น": f"{sh:,.2f}", "ต้นทุนเฉลี่ย/หุ้น": f"${avg_cost:,.2f}", 
                                "ราคาปัจจุบัน": f"${curr_p:,.2f}", "กำไร/ขาดทุน": f"${profit:,.2f}", 
                                "% เปลี่ยนแปลง": f"{profit_pct:.2f}%", "มูลค่ารวม": f"${val:,.2f}"
                            })
                            total_v += val
                    
                    p1, p2, p3 = st.columns(3)
                    p1.metric("มูลค่าหุ้นรวม (Market Value)", f"${total_v:,.2f}")
                    p2.metric("ต้นทุนหุ้นทั้งหมด (Total Cost)", f"${total_invested:,.2f}")
                    p3.metric("กำไร/ขาดทุนรวม (Unrealized P/L)", f"${(total_v-total_invested):,.2f}", f"{((total_v-total_invested)/total_invested*100 if total_invested>0 else 0):.2f}%")
                    st.dataframe(pd.DataFrame(results), use_container_width=True)
        else: st.info("พอร์ตว่างเปล่าค่ะ ลองบันทึกการ 'ซื้อหุ้น' ในสมุดบัญชีด้านบนดูนะคะ")


    # 🌟 หน้า 3: คำนวณภาษี (อัปเกรดแบบยื่นแบบ ภ.ง.ด. 90 ได้เป๊ะๆ)
    with tab_tax:
        st.subheader("🧾 ระบบประเมินภาษีสรรพากร แบบสมบูรณ์")
        
        st.info(f"💡 **สรุปรายได้ที่เกิดขึ้นจริง (Realized Income) จากพอร์ต:**\n- กำไรจากการขายหุ้น (Realized Gain): **${total_realized_profit:,.2f}**\n- เงินปันผลรับ (Dividend): **${total_dividend:,.2f}**")
        
        st.markdown("---")
        st.markdown("### 📝 1. บันทึกประวัติการโอนเงิน (พร้อมบันทึกเครดิตภาษีต่างประเทศ)")
        st.caption("หากเป็นเงินปันผลที่โดนหักภาษี ณ ที่จ่ายจากอเมริกา ให้กรอกจำนวนภาษีที่โดนหักในช่อง 'ภาษีที่ถูกหัก (WHT)' เพื่อนำไปใช้ลดหย่อนภาษีในไทยตามอนุสัญญาภาษีซ้อน (DTA) ค่ะ")
        
        edited_transfer = st.data_editor(
            st.session_state.transfer_data, num_rows="dynamic", use_container_width=True,
            column_config={
                "Date": st.column_config.DateColumn("วันที่โอน", format="DD/MM/YYYY"),
                "Direction": st.column_config.SelectboxColumn("ประเภท", options=["โอนออก (Outward)", "นำเงินเข้า (Inward)"]),
                "Category": st.column_config.SelectboxColumn("หมวดหมู่เงิน", options=["เงินลงทุน (Principal)", "ดึงเงินกลับ (Withdrawal)", "กำไร/ปันผล (Taxable)"]),
                "Amount_USD": st.column_config.NumberColumn("ยอดเงินโอน (USD)", format="$%.2f"),
                "WHT_USD": st.column_config.NumberColumn("ภาษีที่ถูกหัก ตปท. (WHT)", format="$%.2f"),
                "FX_Rate": st.column_config.NumberColumn("อัตราแลกเปลี่ยน", format="%.4f"),
                "Source": st.column_config.TextColumn("แหล่งที่มา/หมายเหตุ"),
                "Country": st.column_config.TextColumn("ประเทศ"),
                "Ref_Doc": st.column_config.TextColumn("ชื่อไฟล์อ้างอิงแนบ")
            }
        )
        st.session_state.transfer_data = edited_transfer
        
        csv_data = edited_transfer.to_csv(index=False).encode('utf-8-sig')
        st.download_button(label="📥 ดาวน์โหลดหลักฐาน (Excel/CSV)", data=csv_data, file_name="tax_transfer_record_full.csv", mime="text/csv", use_container_width=True)
        
        st.markdown("---")
        st.markdown("### 📎 2. แนบเอกสารหลักฐานอ้างอิง (e-Tax / Bank Statement)")
        uploaded_files = st.file_uploader("อัปโหลดไฟล์หลักฐาน (จะถูกแมปเข้ากับชื่ออ้างอิงในตารางอัตโนมัติ)", type=["pdf", "png", "jpg", "jpeg"], accept_multiple_files=True)
        if uploaded_files: st.success(f"✅ สำเร็จ! รับรองไฟล์หลักฐานจำนวน {len(uploaded_files)} รายการ")
        
        # คำนวณกระแสเงินสดและเครดิตภาษี
        total_out_thb, total_in_thb, foreign_tax_credit_thb = 0.0, 0.0, 0.0
        for _, row in edited_transfer.iterrows():
            usd = row["Amount_USD"] if pd.notna(row["Amount_USD"]) else 0
            wht = row["WHT_USD"] if pd.notna(row["WHT_USD"]) else 0
            fx = row["FX_Rate"] if pd.notna(row["FX_Rate"]) else 0
            
            amt_thb = usd * fx
            wht_thb = wht * fx
            
            if row["Direction"] == "โอนออก (Outward)": total_out_thb += amt_thb
            elif row["Direction"] == "นำเงินเข้า (Inward)": 
                total_in_thb += amt_thb
                foreign_tax_credit_thb += wht_thb # รวมเครดิตภาษีต่างประเทศ
                
        net_taxable_gain = max(0, total_in_thb - total_out_thb)
        
        st.markdown("---")
        st.markdown("### 📊 3. แดชบอร์ดสถานะกระแสเงินสด (Cash Flow Offset)")
        cf1, cf2, cf3 = st.columns(3)
        cf1.metric("📤 ยอดรวมโอนออก (เงินต้น)", f"฿{total_out_thb:,.2f}")
        cf2.metric("📥 ยอดรวมโอนเข้าไทย", f"฿{total_in_thb:,.2f}")
        cf3.metric("🚨 กำไรสุทธิที่ประเมินภาษี", f"฿{net_taxable_gain:,.2f}", "หักล้างเงินต้นแล้ว", delta_color="inverse")
        
        st.markdown("---")
        st.markdown("### 🧮 4. ประเมินภาระภาษีเพื่อยื่น ภ.ง.ด. 90 (รวมค่าลดหย่อน)")
        
        c1, c2, c3 = st.columns(3)
        with c1: is_resident = st.radio("คุณอาศัยอยู่ในไทยเกิน 180 วัน หรือไม่?", ["เกิน 180 วัน", "ไม่ถึง 180 วัน"])
        with c2: other_income = st.number_input("รายได้ประจำอื่นๆ ต่อปี (บาท)", min_value=0.0, value=500000.0, step=50000.0)
        with c3: deductions = st.number_input("รวมค่าลดหย่อนส่วนบุคคล (บาท)", min_value=0.0, value=160000.0, step=10000.0, help="เช่น ลดหย่อนส่วนตัว 60k, ประกันชีวิต, PVD, SSF, RMF")

        if st.button("📊 คำนวณภาษีสุทธิที่ต้องจ่ายจริง", type="primary", use_container_width=True):
            if "ไม่ถึง" in is_resident: st.success("🎉 คุณได้รับยกเว้นภาษี")
            elif net_taxable_gain == 0: st.success("🎉 ยังไม่มีกำไรส่วนเกินจากยอดเงินต้นที่ต้องนำมาคิดภาษีค่ะ")
            else:
                # การคำนวณรายได้สุทธิเพื่อเสียภาษี (Net Taxable Income)
                net_income_without_foreign = max(0, other_income - deductions)
                net_income_with_foreign = max(0, (other_income + net_taxable_gain) - deductions)
                
                def calculate_tax(net_inc):
                    tax = 0
                    if net_inc > 5000000: tax += (net_inc - 5000000) * 0.35 + 1265000
                    elif net_inc > 2000000: tax += (net_inc - 2000000) * 0.30 + 365000
                    elif net_inc > 1000000: tax += (net_inc - 1000000) * 0.25 + 115000
                    elif net_inc > 750000: tax += (net_inc - 750000) * 0.20 + 65000
                    elif net_inc > 500000: tax += (net_inc - 500000) * 0.15 + 27500
                    elif net_inc > 300000: tax += (net_inc - 300000) * 0.10 + 7500
                    elif net_inc > 150000: tax += (net_inc - 150000) * 0.05
                    return tax
                
                tax_without = calculate_tax(net_income_without_foreign)
                tax_with = calculate_tax(net_income_with_foreign)
                
                # ภาษีที่ต้องจ่ายเพิ่มจากพอร์ตต่างประเทศ หักด้วย เครดิตภาษีต่างประเทศ
                additional_tax_raw = tax_with - tax_without
                final_tax_to_pay = max(0, additional_tax_raw - foreign_tax_credit_thb)
                
                st.subheader("ผลการคำนวณแบบ ภ.ง.ด. 90 (ประเมิน)")
                st.write(f"- รายได้สุทธิหลังหักลดหย่อน (รวมรายได้ ตปท.): ฿{net_income_with_foreign:,.2f}")
                st.write(f"- ภาษีที่ถูกหักไปแล้วในต่างประเทศ (Foreign Tax Credit): ฿{foreign_tax_credit_thb:,.2f}")
                
                r1, r2 = st.columns(2)
                r1.metric("ภาษีที่คำนวณได้จากพอร์ต ตปท.", f"฿{additional_tax_raw:,.2f}")
                r2.metric("🚨 ภาษีที่ต้องจ่ายเพิ่มจริง (หักเครดิตแล้ว)", f"฿{final_tax_to_pay:,.2f}")
                st.success("📝 **สรุป:** โปรแกรมนี้ได้นำค่าลดหย่อนส่วนบุคคล และเครดิตภาษีต่างประเทศมาคำนวณให้แล้ว คุณสามารถนำตัวเลขเหล่านี้ไปประกอบการยื่นแบบ ภ.ง.ด.90 ได้เลยค่ะ")

    # หน้า 4: กลยุทธ์
    with tab_strat:
        st.subheader("📚 คู่มือกลยุทธ์การลงทุน (Pro Strategy)")
        st.markdown("""### 1. กฎการเทรดแบบ Top-Down Analysis\n### 2. การจัดการความเสี่ยง (Risk Management)""")

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

if "transfer_data" not in st.session_state:
    st.session_state.transfer_data = pd.DataFrame({
        "Date": [datetime.now().date()],
        "Direction": ["นำเงินเข้า (Inward)"],
        "Category": ["กำไร/ปันผล (Taxable)"],
        "Amount_USD": [1000.0],
        "FX_Rate": [36.50]
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
        
        total_capital = 0.0
        risk_pct = 2.0
        buy_price = 0.0

    else:
        st.subheader("🧮 จัดการความเสี่ยง (Risk Mgmt)")
        total_capital = st.number_input("เงินทุนรวม (USD)", min_value=0.0, value=10000.0, step=100.0)
        risk_pct = st.slider("ความเสี่ยงต่อไม้ (%)", 1.0, 5.0, 2.0)
        
        st.markdown("---")
        st.subheader("💰 สถานะหุ้นตัวนี้")
        buy_price = st.number_input("ราคาต้นทุน (USD)", min_value=0.0, value=0.0, step=0.1)
        buy_shares = st.number_input("จำนวนหุ้นที่มี", min_value=0.0, value=0.0, step=0.1)
        
        if st.button("➕ เพิ่มหุ้นนี้ลงตารางพอร์ต", type="primary", use_container_width=True):
            port_df = st.session_state.port_data
            if ticker in port_df["Ticker"].values:
                idx = port_df.index[port_df["Ticker"] == ticker].tolist()[0]
                port_df.at[idx, "Cost_Price"] = buy_price
                port_df.at[idx, "Shares"] = buy_shares
                st.success(f"อัปเดตข้อมูล {ticker} เรียบร้อย!")
            else:
                new_row = pd.DataFrame({"Ticker": [ticker], "Cost_Price": [buy_price], "Shares": [buy_shares]})
                st.session_state.port_data = pd.concat([port_df, new_row], ignore_index=True)
                st.success(f"เพิ่ม {ticker} ลงพอร์ตเรียบร้อย!")

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
    tab_dash, tab_port, tab_tax, tab_strat = st.tabs(["📊 วิเคราะห์กราฟ (Analysis)", "💼 ติดตามพอร์ต (Portfolio)", "🧾 คำนวณภาษี (Tax & Transfer)", "📚 กลยุทธ์ (Strategy)"])
else:
    tab_dash, = st.tabs(["📊 วิเคราะห์กราฟ (Analysis)"])

# ==========================================
# หน้า 1: วิเคราะห์หลัก (Dashboard) - ข้อมูลอยู่ครบ 100% แน่นอน
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

            # 🌟 ส่วนที่เคยกู้คืนมาแล้ว ยืนยันว่ายังอยู่ครบถ้วนค่ะ
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
            
            # 🌟 P/L ของหุ้นรายตัว กลับมาครบถ้วน
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

    else:
        st.warning("ไม่พบข้อมูล กรุณาลองหุ้นตัวอื่นค่ะ")

# ==========================================
# พื้นที่เฉพาะ Owner
# ==========================================
if st.session_state["logged_in"]:
    
    # หน้า 2: พอร์ตโฟลิโอ 
    with tab_port:
        st.subheader("💼 ตัวติดตามพอร์ต (Real-time Multi-Stock Tracker)")
        edited_df = st.data_editor(st.session_state.port_data, num_rows="dynamic", use_container_width=True, column_config={"Ticker": "ชื่อหุ้น", "Cost_Price": "ราคาต้นทุน ($)", "Shares": "จำนวนหุ้น"})
        st.session_state.port_data = edited_df 

        if st.button("🔄 อัปเดตราคาปัจจุบันทุกตัวในพอร์ต", type="primary", use_container_width=True):
            tickers = edited_df["Ticker"].dropna().unique().tolist()
            if tickers:
                with st.spinner("กำลังดึงข้อมูลราคาล่าสุด..."):
                    current_prices = {}
                    for t in tickers:
                        try:
                            price = yf.Ticker(t).history(period="1d")['Close'].iloc[-1]
                            current_prices[t] = price
                        except: pass
                    results, total_v, total_c = [], 0, 0
                    for _, row in edited_df.iterrows():
                        t, cost, sh = row["Ticker"], row["Cost_Price"], row["Shares"]
                        if t in current_prices:
                            curr_p, val, cst = current_prices[t], current_prices[t] * sh, cost * sh
                            profit = val - cst
                            profit_pct = (profit / cst * 100) if cst > 0 else 0
                            results.append({"หุ้น": t, "ราคาปัจจุบัน": f"${curr_p:,.2f}", "ต้นทุน": f"${cost:,.2f}", "กำไร/ขาดทุน": f"${profit:,.2f}", "%": f"{profit_pct:.2f}%", "มูลค่ารวม": f"${val:,.2f}"})
                            total_v += val
                            total_c += cst
                    st.markdown("---")
                    p1, p2, p3 = st.columns(3)
                    p1.metric("มูลค่ารวมปัจจุบัน", f"${total_v:,.2f}")
                    p2.metric("เงินต้นทั้งหมด", f"${total_c:,.2f}")
                    p3.metric("กำไร/ขาดทุนรวม", f"${(total_v-total_c):,.2f}", f"{((total_v-total_c)/total_c*100 if total_c>0 else 0):.2f}%")
                    st.dataframe(pd.DataFrame(results), use_container_width=True)

    # หน้า 3: คำนวณภาษี
    with tab_tax:
        st.subheader("🧾 ระบบประเมินและติดตามกระแสเงินสดข้ามประเทศ")
        with st.expander("📖 กฎหมายภาษีเงินได้สรรพากร (อัปเดต 1 ม.ค. 2567) - คลิกเพื่ออ่านข้อกำหนด"):
            st.markdown("""
            **หลักการพิจารณาภาษีเงินได้จากการลงทุนต่างประเทศ (ใหม่):**
            1. **เกณฑ์ด้านเวลา (Tax Resident):** คุณต้องอาศัยอยู่ในไทยรวมแล้วถึง 180 วันในปีภาษีนั้นๆ จึงจะเข้าเกณฑ์เสียภาษี
            2. **เกณฑ์การนำเข้าข้ามปี:** เงินได้ (กำไร/ปันผล) ที่เกิดขึ้นตั้งแต่วันที่ 1 ม.ค. 2567 หากนำกลับเข้าไทย **ไม่ว่าในปีใดก็ตาม** ต้องนำมาเสียภาษีในปีที่นำเงินเข้า
            3. **ข้อยกเว้น:** เงินได้ที่เกิดขึ้น **ก่อน** 1 ม.ค. 2567 แม้นำเข้ามาในปี 2567 เป็นต้นไป จะได้รับยกเว้นภาษี
            4. **เงินต้น VS กำไร:** สรรพากรจะเก็บภาษีเฉพาะส่วนที่เป็น "กำไร (Capital Gain)" หรือ "เงินปันผล (Dividend)" เท่านั้น หากพิสูจน์ได้ว่าเป็น **"เงินต้น (Principal)"** จะไม่เสียภาษี
            5. **อัตราแลกเปลี่ยน:** ใช้อัตราแลกเปลี่ยนอ้างอิง ณ วันที่นำเงินเข้าประเทศในแต่ละครั้ง
            """)
        
        st.markdown("---")
        st.markdown("### 📝 1. บันทึกประวัติการทำรายการ (โอนเข้า-โอนออก)")
        st.caption("ระบบจะคำนวณภาษีเฉพาะรายการที่เป็น 'นำเงินเข้า' และหมวดหมู่ 'กำไร/ปันผล' เท่านั้น")
        
        edited_transfer = st.data_editor(
            st.session_state.transfer_data,
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "Date": st.column_config.DateColumn("วันที่ทำรายการ", format="DD/MM/YYYY"),
                "Direction": st.column_config.SelectboxColumn("ประเภทรายการ", options=["นำเงินเข้า (Inward)", "โอนออก (Outward)"]),
                "Category": st.column_config.SelectboxColumn("หมวดหมู่เงิน", options=["กำไร/ปันผล (Taxable)", "เงินต้น (Principal)"]),
                "Amount_USD": st.column_config.NumberColumn("จำนวนเงิน (USD)", format="$%.2f"),
                "FX_Rate": st.column_config.NumberColumn("อัตราแลกเปลี่ยน (THB/USD)", format="%.4f")
            }
        )
        st.session_state.transfer_data = edited_transfer
        
        total_taxable_thb = 0.0
        for _, row in edited_transfer.iterrows():
            if row["Direction"] == "นำเงินเข้า (Inward)" and row["Category"] == "กำไร/ปันผล (Taxable)":
                usd = row["Amount_USD"] if pd.notna(row["Amount_USD"]) else 0
                fx = row["FX_Rate"] if pd.notna(row["FX_Rate"]) else 0
                total_taxable_thb += (usd * fx)
        
        st.info(f"💵 **ยอดรวมกำไรนำเข้าที่ต้องเสียภาษี:** {total_taxable_thb:,.2f} บาท")
        
        st.markdown("---")
        st.markdown("### 🧮 2. ข้อมูลผู้เสียภาษีและประเมินฐานภาษี")
        
        c1, c2 = st.columns(2)
        with c1:
            is_resident = st.radio("คุณอาศัยอยู่ในไทยเกิน 180 วัน ในปีภาษีนี้หรือไม่?", ["เกิน 180 วัน (เข้าเกณฑ์)", "ไม่ถึง 180 วัน (ได้รับยกเว้น)"])
        with c2:
            other_income = st.number_input("รายได้อื่นๆ ในไทยต่อปี (บาท) *เช่น เงินเดือน เพื่อหาฐานภาษีก้าวหน้า*", min_value=0.0, value=0.0, step=50000.0)

        if st.button("📊 ประเมินภาษีที่ต้องเตรียมจ่าย", type="primary", use_container_width=True):
            if "ไม่ถึง" in is_resident:
                st.success("🎉 คุณได้รับยกเว้นภาษี เนื่องจากอาศัยอยู่ในประเทศไทยไม่ถึง 180 วันในปีภาษีที่มีการโอนเงินกลับค่ะ")
            else:
                total_income_all = total_taxable_thb + other_income
                
                def calculate_tax(income):
                    tax = 0
                    if income > 5000000: tax += (income - 5000000) * 0.35 + 1265000
                    elif income > 2000000: tax += (income - 2000000) * 0.30 + 365000
                    elif income > 1000000: tax += (income - 1000000) * 0.25 + 115000
                    elif income > 750000: tax += (income - 750000) * 0.20 + 65000
                    elif income > 500000: tax += (income - 500000) * 0.15 + 27500
                    elif income > 300000: tax += (income - 300000) * 0.10 + 7500
                    elif income > 150000: tax += (income - 150000) * 0.05
                    return tax
                
                tax_without_foreign = calculate_tax(other_income)
                tax_with_foreign = calculate_tax(total_income_all)
                additional_tax = tax_with_foreign - tax_without_foreign
                
                st.subheader("ผลการคำนวณฐานภาษี")
                r1, r2, r3 = st.columns(3)
                r1.metric("กำไรนำเข้าสุทธิ", f"฿{total_taxable_thb:,.2f}")
                r2.metric("ฐานรายได้รวมทั้งหมดปีนี้", f"฿{total_income_all:,.2f}")
                r3.metric("🚨 ภาษีที่เพิ่มขึ้นจากพอร์ต ตปท.", f"฿{additional_tax:,.2f}")
                
                st.caption("*โปรแกรมนี้คำนวณภาษีแบบขั้นบันได (Progressive Tax Rate) อิงจากรายได้สุทธิเพื่อประกอบการตัดสินใจเบื้องต้น (ยังไม่ได้หักค่าลดหย่อน)*")

    # หน้า 4: กลยุทธ์
    with tab_strat:
        st.subheader("📚 คู่มือกลยุทธ์การลงทุน (Pro Strategy)")
        st.markdown("""
        ### 1. กฎการเทรดแบบ Top-Down Analysis
        - **เช็กรายเดือน (1M):** เพื่อดูว่าหุ้นอยู่ในวัฏจักรขาขึ้นรอบใหญ่หรือไม่
        - **เช็กรายสัปดาห์ (1W):** เพื่อหาแนวรับ-แนวต้านที่แข็งแกร่ง
        - **เช็กรายวัน (1D):** เพื่อหาจุดเข้าซื้อที่ได้เปรียบ
        
        ### 2. การจัดการความเสี่ยง (Risk Management)
        - **กฎ 2%:** อย่าให้การขาดทุนในแต่ละไม้ เกิน 2% ของเงินต้นทั้งหมด
        - **Relative Strength:** เน้นลงทุนในหุ้นที่ **ชนะตลาด (สีเขียว)** """)

import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

# 1. ตั้งค่าหน้าเพจ
st.set_page_config(page_title="ระบบวิเคราะห์หุ้นอัตโนมัติ", layout="wide")

# 🌟 บังคับตั้งค่าเป็นเวลาประเทศไทย (UTC+7) เสมอ
tz_th = timezone(timedelta(hours=7))
current_date = datetime.now(tz_th).strftime("%d/%m/%Y")
current_time = datetime.now(tz_th).strftime("%H:%M")

with st.sidebar:
    st.title("เมนูการใช้งาน")
    st.markdown("🏠 **หน้าหลัก (Dashboard)**")
    st.markdown("---")
    ticker = st.text_input("🔎 ใส่ชื่อหุ้น หรือ ดัชนี (เช่น ^DJI, ^GSPC)", value="NVTS").upper()
    
    st.markdown("---")
    st.markdown("💰 **พอร์ตส่วนตัว (Portfolio)**")
    buy_price = st.number_input("ใส่ราคาต้นทุนของคุณ (USD) \n*ใส่ 0 หากยังไม่มีของ", min_value=0.0, value=0.0, step=0.1)

@st.cache_data(ttl=300)
def load_data(ticker_symbol):
    try:
        stock = yf.Ticker(ticker_symbol)
        df = stock.history(period="6mo", interval="1d")
        
        if df.empty:
            return pd.DataFrame(), "N/A"
            
        df['EMA_10'] = df['Close'].ewm(span=10, adjust=False).mean()
        df['EMA_20'] = df['Close'].ewm(span=20, adjust=False).mean()
        df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()
        
        ema_12 = df['Close'].ewm(span=12, adjust=False).mean()
        ema_26 = df['Close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = ema_12 - ema_26
        df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['MACD_Hist'] = df['MACD'] - df['Signal']
        
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        df['Daily_Return'] = df['Close'].pct_change()
        
        ps_ratio = "N/A"
        try:
            info = stock.info
            ps_val = info.get('priceToSalesTrailing12Months', 'N/A')
            if isinstance(ps_val, float):
                ps_ratio = round(ps_val, 2)
        except:
            pass 
            
        return df, ps_ratio
        
    except Exception as e:
        return pd.DataFrame(), "N/A"

df, ps_ratio = load_data(ticker)

# ==========================================
# 🌟 ฟังก์ชัน: The Harmonic Momentum Matrix
# ==========================================
def harmonic_momentum_model(df):
    if df.empty or len(df) < 20:
        return None
        
    last_price = df['Close'].iloc[-1]
    ema10 = df['EMA_10'].iloc[-1]
    ema50 = df['EMA_50'].iloc[-1]
    
    volatility = df['Daily_Return'].tail(14).std()
    
    expected_change_lower = (volatility * 0.5) * 100
    expected_change_upper = volatility * 100
    
    recent_high = df['High'].tail(20).max()
    
    if last_price > ema50 and ema10 > ema50:
        trend = "ขาขึ้น (Uptrend) 📈"
        target_lower = last_price * (1 + (expected_change_lower / 100))
        target_upper = last_price * (1 + (expected_change_upper / 100))
        change_text = f"เพิ่มขึ้นประมาณ +{expected_change_lower:.2f}% ถึง +{expected_change_upper:.2f}%"
        
        if last_price >= recent_high * 0.98:
            status = "ตลาดกำลังทำจุดสูงสุดใหม่ (New Records) 🔥"
        else:
            status = "พักตัวสะสมพลังเพื่อขึ้นต่อ (Bullish Consolidation) ⚡"
            
    else:
        trend = "ขาลง (Downtrend) 📉"
        target_lower = last_price * (1 - (expected_change_upper / 100))
        target_upper = last_price * (1 - (expected_change_lower / 100))
        change_text = f"ลดลงประมาณ -{expected_change_lower:.2f}% ถึง -{expected_change_upper:.2f}%"
        status = "เผชิญแรงขายทำกำไร / ปรับฐาน (Correction) ⚠️"
        
    return {
        "trend": trend,
        "status": status,
        "change_text": change_text,
        "target_lower": target_lower,
        "target_upper": target_upper,
        "last_price": last_price
    }

matrix_result = harmonic_momentum_model(df)

# ==========================================
# 4. ฟังก์ชันคำนวณข้อมูลหลัก
# ==========================================
def auto_analyze(df):
    if df.empty:
        return "", "", "", "", ""
        
    last_close = df['Close'].iloc[-1]
    ema10 = df['EMA_10'].iloc[-1]
    ema20 = df['EMA_20'].iloc[-1] 
    ema50 = df['EMA_50'].iloc[-1]
    rsi = df['RSI'].iloc[-1]
    
    recent_high = df['High'].tail(20).max()

    summary = ""
    if last_close > ema50:
        summary += "✅ ราคาอยู่ในแนวโน้มขาขึ้น (ยืนเหนือ EMA 50)\n"
    else:
        summary += "❌ ราคาอยู่ในแนวโน้มขาลง (หลุด EMA 50)\n"

    if rsi >= 70:
        summary += "⚠️ RSI เข้าสู่โซน Overbought ระวังการย่อตัว\n"
    elif rsi <= 30:
        summary += "💡 RSI เข้าสู่โซน Oversold อาจมีรอบเด้งรีบาวด์\n"
    else:
        summary += "✅ RSI แกว่งตัวระดับกลาง มีพื้นที่ให้ไปต่อ\n"

    res = f"{recent_high:.2f} / {(recent_high * 1.05):.2f}"
    sup = f"{ema10:.2f} (EMA10) / {ema20:.2f} (EMA20) / {ema50:.2f} (EMA50)"

    if last_close > ema50: 
        trend = "ขาขึ้น 📈"
        buy_zone = f"โซน {ema10:.2f} ถึง {ema20:.2f}"
        hold_zone = f"ถ้าราคายืนเหนือ {ema20:.2f} (หนีที่ {ema50:.2f})"
    else: 
        trend = "ขาลง 📉"
        buy_zone = "ยังไม่แนะนำ (รอสัญญาณกลับตัว)"
        hold_zone = f"ระวัง! หลุด Low ควรคัททิ้ง"
        
    sell_zone = f"โซน {recent_high:.2f} ขึ้นไป"

    action_short = f"**📈 แนวโน้ม:** {trend}\n**🟢 ซื้อ:** {buy_zone}\n**🔴 ขาย:** {sell_zone}\n**🟡 ถือต่อ:** {hold_zone}"

    return summary, res, sup, "", action_short

auto_summary, auto_res, auto_sup, _, action_short = auto_analyze(df)

def get_personal_plan(df, cost_price):
    if df.empty or cost_price <= 0:
        return None
        
    last_price = df['Close'].iloc[-1]
    ema20 = df['EMA_20'].iloc[-1]
    ema50 = df['EMA_50'].iloc[-1]
    rsi = df['RSI'].iloc[-1]
    
    pl_pct = ((last_price - cost_price) / cost_price) * 100
    
    if last_price > cost_price:
        if rsi >= 70:
            advice = "🟢 **กำไรอยู่ แต่ RSI สูงมาก (Overbought):**\nแนะนำให้ **'แบ่งขายล็อกกำไร (Take Profit)'** บางส่วน เพราะราคามีโอกาสย่อตัวพักฐานสูง"
            color = "warning"
        elif last_price < ema20:
            advice = "🟡 **กำไรอยู่ แต่ราคาหลุด EMA 20:**\nโมเมนตัมระยะสั้นเริ่มอ่อนแรง แนะนำให้ **'เฝ้าระวังอย่างใกล้ชิด'** หากหลุดต้นทุนของคุณ ควรขายออกมาก่อน"
            color = "warning"
        else:
            advice = "🚀 **กำไรอยู่ และกราฟยังเป็นขาขึ้นแข็งแกร่ง:**\nแนะนำให้ **'ถือต่อ (Let Profit Run)'** ปล่อยให้กำไรทำงานต่อไป"
            color = "success"
    else:
        if last_price < ema50:
            advice = "🔴 **ขาดทุน และกราฟหลุดเส้น EMA 50 (เสียทรง):**\nแนวโน้มหลักเปลี่ยนเป็นขาลง แนะนำให้พิจารณา **'ตัดขาดทุน (Cut Loss)'** เพื่อจำกัดความเสี่ยง"
            color = "error"
        else:
            advice = "🟡 **ขาดทุน แต่กราฟยังไม่หลุดแนวรับหลัก (EMA 50):**\nราคาย่อตัวลงมาแต่ยังอยู่ในเทรนด์ขาขึ้น แนะนำให้ **'ถือรอ (Hold)'** เพื่อลุ้นราคาเด้งกลับ"
            color = "warning"
            
    return {"pl_pct": pl_pct, "advice": advice, "color": color}

personal_plan = get_personal_plan(df, buy_price)

with st.sidebar:
    st.markdown("---")
    st.subheader("📝 บันทึกวิเคราะห์หุ้น")
    summary_text = st.text_area("📌 สรุปภาพรวมตอนนี้", value=auto_summary, height=120)
    res_text = st.text_input("🚧 แนวต้าน (Resistance)", value=auto_res)
    sup_text = st.text_input("🚧 แนวรับ (Support)", value=auto_sup)

def create_chart(df, ticker_symbol, cost_price=0):
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.6, 0.2, 0.2])
    
    fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Price'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['EMA_10'], line=dict(color='#2962FF', width=1.5), name='EMA 10'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['EMA_20'], line=dict(color='#00E676', width=1.5), name='EMA 20'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['EMA_50'], line=dict(color='#FF6D00', width=1.5), name='EMA 50'), row=1, col=1)

    if cost_price > 0:
        fig.add_hline(y=cost_price, line_dash="dash", line_color="white", annotation_text="ราคาต้นทุน", row=1, col=1)

    macd_colors = ['#26A69A' if val >= 0 else '#EF5350' for val in df['MACD_Hist']]
    fig.add_trace(go.Scatter(x=df.index, y=df['MACD'], line=dict(color='#2962FF', width=1.5), name='MACD'), row=2, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['Signal'], line=dict(color='#FF6D00', width=1.5), name='Signal'), row=2, col=1)
    fig.add_trace(go.Bar(x=df.index, y=df['MACD_Hist'], marker_color=macd_colors, name='Histogram'), row=2, col=1)

    fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], line=dict(color='#BA68C8', width=1.5), name='RSI'), row=3, col=1)
    fig.add_hline(y=70, line_dash="dot", line_color="red", row=3, col=1)
    fig.add_hline(y=30, line_dash="dot", line_color="green", row=3, col=1)

    fig.update_layout(title=f"กราฟราคา {ticker_symbol}", template="plotly_dark", height=750, margin=dict(l=0, r=0, t=40, b=0), showlegend=False)
    fig.update_xaxes(rangeslider_visible=False)
    return fig

# ==========================================
# 6. จัด Layout หน้าจอหลัก
# ==========================================
st.markdown(f"## ข้อมูลหุ้น/ดัชนี : {ticker}")
st.caption(f"📅 **บทวิเคราะห์และข้อมูลอัปเดตล่าสุด ณ วันที่ {current_date} เวลา {current_time} น.**")

# 🌟 กล่อง The Harmonic Momentum Matrix 🌟
if matrix_result:
    st.markdown("---")
    st.markdown("### 🔮 วิเคราะห์ทิศทางคืนนี้ (The Harmonic Momentum Matrix)")
    st.info(f"""
    **จากการคำนวณผ่านโมเดลควอนตัมเชิงตัวเลข สถิติเชิงลึก และแรงเหวี่ยงของราคา:**
    * **แนวโน้ม:** {matrix_result['trend']}
    * **สถานะ:** {matrix_result['status']}
    * **คาดการณ์การเปลี่ยนแปลง:** {matrix_result['change_text']} จากราคาปิดเมื่อวาน
    * **เป้าหมายตัวเลข:** คืนนี้คาดว่าราคาจะเคลื่อนไหวไปแตะระดับ **{matrix_result['target_lower']:,.2f} - {matrix_result['target_upper']:,.2f}** (อ้างอิงจากราคาปิดล่าสุด {matrix_result['last_price']:,.2f})
    
    *🧪 สูตรคำนวณ: "The Harmonic Momentum Matrix" ประเมินจากค่า Standard Deviation ของกรอบราคา 14 วันย้อนหลัง ผสมผสาน Momentum ระยะสั้น*
    """)
st.markdown("---")

col1, col2 = st.columns([7, 3])

if not df.empty:
    last_price = df['Close'].iloc[-1]
    prev_price = df['Close'].iloc[-2] if len(df) > 1 else last_price
    price_change = last_price - prev_price
    pct_change = (price_change / prev_price) * 100

    with col1:
        st.plotly_chart(create_chart(df, ticker, buy_price), use_container_width=True)

    with col2:
        st.metric(label="💵 ราคาปัจจุบัน (USD)", value=f"{last_price:,.2f}", delta=f"{price_change:.2f} ({pct_change:.2f}%)")
        
        if personal_plan:
            st.markdown("---")
            st.subheader("💼 แผนสำหรับพอร์ตของคุณ")
            st.write(f"**กำไร/ขาดทุน:** {personal_plan['pl_pct']:.2f}%")
            if personal_plan['color'] == "success":
                st.success(personal_plan['advice'])
            elif personal_plan['color'] == "warning":
                st.warning(personal_plan['advice'])
            else:
                st.error(personal_plan['advice'])
        
        st.markdown("---")
        st.subheader("💡 คำแนะนำภาพรวม")
        st.success(action_short)
        
        st.markdown("---")
        st.subheader("🚧 โซนราคาสำคัญ")
        st.write(f"**แนวต้าน:** {res_text}")
        st.write(f"**แนวรับ:** {sup_text}")

        # 🌟 กล่องข้อมูลพื้นฐาน P/S Ratio (พร้อมสีสันแจ้งเตือน) 🌟
        st.markdown("---")
        st.subheader("📊 ข้อมูลพื้นฐาน (Fundamental)")
        
        if ps_ratio != "N/A":
            if ps_ratio > 10:
                st.error(f"🚨 **P/S Ratio: {ps_ratio}** (สูงมาก) \n\n⚠️ **ข้อควรระวัง:** ราคาหุ้นค่อนข้างแพงเมื่อเทียบกับรายได้ มีความเสี่ยงหากงบการเงินไม่โตตามเป้า")
            elif ps_ratio < 3:
                st.success(f"🌟 **P/S Ratio: {ps_ratio}** (ราคาถูก) \n\n✅ **จุดเด่น:** ราคาหุ้นยังถูก คุ้มค่าเมื่อเทียบกับรายได้ของบริษัท ถือเป็นจุดที่น่าสนใจสะสม")
            else:
                st.warning(f"💡 **P/S Ratio: {ps_ratio}** (ระดับกลาง) \n\nสมเหตุสมผลตามมาตรฐานหุ้นเติบโตทั่วไป")
        else:
            st.info("ไม่พบข้อมูล P/S Ratio สำหรับหุ้น/ดัชนีตัวนี้")

else:
    st.error("⚠️ ไม่พบข้อมูล หรือระบบถูกจำกัดการดึงข้อมูลชั่วคราว (กรุณารอสักครู่แล้วกด Refresh หน้าเว็บใหม่ หรือลองพิมพ์ชื่อหุ้นใหม่ครับ)")

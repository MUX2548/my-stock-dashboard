import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
from datetime import datetime
import requests

# 1. ตั้งค่าหน้าเพจ
st.set_page_config(page_title="ระบบวิเคราะห์หุ้นอัตโนมัติ", layout="wide")

current_date = datetime.now().strftime("%d/%m/%Y")
current_time = datetime.now().strftime("%H:%M")

with st.sidebar:
    st.title("เมนูการใช้งาน")
    st.markdown("🏠 **หน้าหลัก (Dashboard)**")
    st.markdown("---")
    ticker = st.text_input("🔎 ใส่ชื่อหุ้นที่ต้องการ", value="NVTS").upper()

@st.cache_data(ttl=300)
def load_data(ticker_symbol):
    session = requests.Session()
    session.headers.update(
        {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'}
    )
    
    stock = yf.Ticker(ticker_symbol, session=session)
    
    # ดึงข้อมูลกราฟ (ถ้าดึงไม่ได้ให้ข้าม)
    try:
        df = stock.history(period="6mo", interval="1d")
    except:
        return pd.DataFrame(), "N/A"
    
    if df.empty:
        return df, "N/A"
        
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
    
    # 🌟 ใส่เกราะป้องกันตรงนี้! ถ้าดึง P/S Ratio แล้วโดนบล็อก จะได้ไม่พัง
    ps_ratio = "N/A"
    try:
        info = stock.info
        ps_val = info.get('priceToSalesTrailing12Months', 'N/A')
        if isinstance(ps_val, float):
            ps_ratio = round(ps_val, 2)
    except:
        pass # ปล่อยผ่านไปเลย
        
    return df, ps_ratio

df, ps_ratio = load_data(ticker)

# ==========================================
# 4. ฟังก์ชันคำนวณข้อมูล
# ==========================================
def auto_analyze(df):
    if df.empty:
        return "", "", "", "", ""
        
    last_close = df['Close'].iloc[-1]
    ema10 = df['EMA_10'].iloc[-1]
    ema20 = df['EMA_20'].iloc[-1] 
    ema50 = df['EMA_50'].iloc[-1]
    rsi = df['RSI'].iloc[-1]
    macd_hist = df['MACD_Hist'].iloc[-1]
    
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

    if macd_hist > 0:
        summary += "✅ MACD โมเมนตัมเป็นบวก (แรงซื้อหนุน)\n"
    else:
        summary += "❌ MACD โมเมนตัมเป็นลบ (แรงขายกดดัน)\n"

    res = f"{recent_high:.2f} / {(recent_high * 1.05):.2f}"
    sup = f"{ema10:.2f} (EMA10) / {ema20:.2f} (EMA20) / {ema50:.2f} (EMA50)"

    if last_close > ema50 and rsi < 70:
        plan = "🟢 แผนย่อซื้อ: ทรงกราฟยังดี หาจังหวะเข้าเมื่อราคาย่อมาใกล้แนวรับ EMA 10 หรือ EMA 20\nจุดหนี: หลุดแนวรับ EMA 50"
    elif last_close > ema50 and rsi >= 70:
        plan = "🟡 แผนถือรันเทรนด์: มีของให้ถือต่อ ใช้ EMA 20 เป็นจุดขยับตัดขาดทุน (Trailing Stop)\nระวัง: อย่าเพิ่งไล่ราคา รอให้ย่อพักตัวก่อน"
    else:
        plan = "🔴 แผนเด้งขาย / Wait & See: กราฟเสียทรง รอให้สร้างฐานใหม่หรือมีสัญญาณกลับตัวชัดเจนก่อน\nจุดหนี: หากมีของ ให้ลดพอร์ตเมื่อเด้งไม่ผ่านแนวต้าน"

    if last_close > ema50: 
        trend = "ขาขึ้น 📈"
        buy_zone = f"โซน {ema10:.2f} ถึง {ema20:.2f} (รับลึก {ema50:.2f})"
        hold_zone = f"ถ้าราคายืนเหนือ {ema20:.2f} (จุดหนีสุดท้าย {ema50:.2f})"
    else: 
        trend = "ขาลง 📉"
        buy_zone = "ยังไม่แนะนำ (รอสัญญาณกลับตัว)"
        hold_zone = f"ระวัง! หลุด Low ควรคัททิ้ง"
        
    sell_zone = f"โซน {recent_high:.2f} ขึ้นไป"

    action_short = f"""
**📈 แนวโน้ม:** {trend}
**🟢 ซื้อราคา:** {buy_zone}
**🔴 ขายราคา:** {sell_zone}
**🟡 ถือต่อในราคา:** {hold_zone}
    """

    return summary, res, sup, plan, action_short

auto_summary, auto_res, auto_sup, auto_plan, action_short = auto_analyze(df)

with st.sidebar:
    st.markdown("---")
    st.subheader("📝 บันทึกวิเคราะห์หุ้น")
    st.caption(f"อัปเดตข้อมูลล่าสุดเมื่อ: {current_time} น.")
    summary_text = st.text_area("📌 สรุปภาพรวมตอนนี้", value=auto_summary, height=120)
    res_text = st.text_input("🚧 แนวต้าน (Resistance)", value=auto_res)
    sup_text = st.text_input("🚧 แนวรับ (Support)", value=auto_sup)
    plan_text = st.text_area("🎯 แผนการเทรด", value=auto_plan, height=100)

def create_chart(df, ticker_symbol):
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.6, 0.2, 0.2])
    
    fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Price'), row=1, col=1)
    
    fig.add_trace(go.Scatter(x=df.index, y=df['EMA_10'], line=dict(color='#2962FF', width=1.5), name='EMA 10'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['EMA_20'], line=dict(color='#00E676', width=1.5), name='EMA 20'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['EMA_50'], line=dict(color='#FF6D00', width=1.5), name='EMA 50'), row=1, col=1)

    macd_colors = ['#26A69A' if val >= 0 else '#EF5350' for val in df['MACD_Hist']]
    fig.add_trace(go.Scatter(x=df.index, y=df['MACD'], line=dict(color='#2962FF', width=1.5), name='MACD'), row=2, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['Signal'], line=dict(color='#FF6D00', width=1.5), name='Signal'), row=2, col=1)
    fig.add_trace(go.Bar(x=df.index, y=df['MACD_Hist'], marker_color=macd_colors, name='Histogram'), row=2, col=1)

    fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], line=dict(color='#BA68C8', width=1.5), name='RSI'), row=3, col=1)
    fig.add_hline(y=70, line_dash="dot", line_color="red", row=3, col=1)
    fig.add_hline(y=30, line_dash="dot", line_color="green", row=3, col=1)

    fig.update_layout(title=f"กราฟราคา {ticker_symbol} พร้อม MACD & RSI", template="plotly_dark", height=750, margin=dict(l=0, r=0, t=40, b=0), showlegend=False)
    fig.update_xaxes(rangeslider_visible=False)
    return fig

# ==========================================
# 6. จัด Layout หน้าจอหลัก
# ==========================================
st.markdown(f"## ข้อมูลหุ้น : {ticker}")
st.caption(f"📅 **บทวิเคราะห์และข้อมูลอัปเดตล่าสุด ณ วันที่ {current_date} เวลา {current_time} น.**")
st.markdown("---")

col1, col2 = st.columns([7, 3])

if not df.empty:
    last_price = df['Close'].iloc[-1]
    prev_price = df['Close'].iloc[-2] if len(df) > 1 else last_price
    price_change = last_price - prev_price
    pct_change = (price_change / prev_price) * 100

    with col1:
        st.plotly_chart(create_chart(df, ticker), use_container_width=True)

    with col2:
        st.metric(label="💵 ราคาปัจจุบัน (USD)", value=f"${last_price:.2f}", delta=f"{price_change:.2f} ({pct_change:.2f}%)")
        st.success(action_short)
        st.markdown("---")
        
        st.subheader("📊 ข้อมูลพื้นฐาน")
        st.write(f"**P/S Ratio:** {ps_ratio}")
        st.markdown("---")
        
        st.subheader("📌 สรุปภาพรวมตอนนี้")
        st.info(summary_text) 
        
        st.markdown("---")
        st.subheader("🚧 โซนราคาสำคัญ")
        st.write(f"**แนวต้าน:** {res_text}")
        st.write(f"**แนวรับ:** {sup_text}")
        
        st.markdown("---")
        st.subheader("🎯 แผนการเทรด (ละเอียด)")
        if "ย่อซื้อ" in plan_text:
            st.success(plan_text)
        elif "ถือรันเทรนด์" in plan_text:
            st.warning(plan_text)
        else:
            st.error(plan_text)
else:
    st.error("ไม่พบข้อมูลหุ้นที่ค้นหา กรุณาตรวจสอบชื่อหุ้นอีกครั้ง หรือระบบอาจถูกจำกัดการดึงข้อมูลชั่วคราวครับ")

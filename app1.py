import streamlit as st
import requests
import numpy as np
import sys
import os
import geocoder  # 用于自动IP定位

# ==========================================
# 真实 JOS-3 模型导入
# ==========================================
current_dir = os.path.dirname(os.path.abspath(__file__))
jos3_path = os.path.join(current_dir, "JOS-3-master", "src")
sys.path.append(jos3_path)
import jos3
# ==========================================

# 设置页面基本属性
st.set_page_config(page_title="个性化气候预警APP", layout="centered")
st.title("🌡️ 气候暴露预测预警系统")
st.markdown("基于气象数据与热生理模型的个性化气候信息")
st.divider()

# --- 1. 获取定位和天气（修复+自动定位） ---
st.header("🌍 1. 环境数据采集")

# 自动定位开关 + 手动输入 fallback
auto_locate = st.checkbox("🔍 自动定位当前城市", value=True)
city_input = ""

if auto_locate:
    with st.spinner("正在通过IP自动定位..."):
        # 尝试IP定位
        g = geocoder.ip('me')
        if g.ok and g.city:
            city_input = g.city.lower()
            st.success(f"✅ 自动定位成功：{g.city}")
        else:
            st.warning("⚠️ 自动定位失败（可能是网络/IP限制），请手动输入城市")
            city_input = st.text_input(
                "请输入拼音城市名（如 beijing, shanghai）", 
                value="beijing",
                placeholder="输入城市拼音"
            )
else:
    city_input = st.text_input(
        "请输入拼音城市名（如 beijing, shanghai）", 
        value="beijing",
        placeholder="输入城市拼音"
    )

def get_weather_desc(code):
    """根据 WMO 天气代码返回天气描述"""
    if code == 0: return "☀️ 晴天"
    elif code in [1, 2, 3]: return "⛅ 多云/阴天"
    elif code in [45, 48]: return "🌫️ 雾"
    elif code in [51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82]: return "🌧️ 雨天"
    elif code in [71, 73, 75, 77, 85, 86]: return "❄️ 雪天"
    elif code in [95, 96, 99]: return "⛈️ 雷暴"
    else: return "🌈 未知"

@st.cache_data(ttl=300)  # 缓存5分钟，避免频繁调用API
def get_weather(city_name):
    """修复后的天气获取函数，带详细异常处理"""
    if not city_name:
        return None, None, None, None
    
    try:
        # 1. 地理编码获取经纬度（增加中文支持+超时）
        geo_url = (
            f"https://geocoding-api.open-meteo.com/v1/search?"
            f"name={city_name}&count=1&language=zh&format=json"
        )
        geo_resp = requests.get(geo_url, timeout=10)
        geo_resp.raise_for_status()  # 触发HTTP错误
        geo_data = geo_resp.json()
        
        # 检查是否有匹配结果
        if not geo_data.get("results"):
            st.error(f"❌ 未找到「{city_name}」的地理信息，请检查拼音是否正确")
            return None, None, None, None
        
        # 提取经纬度
        lat = geo_data["results"][0]["latitude"]
        lon = geo_data["results"][0]["longitude"]
        st.info(f"📍 定位到：{geo_data['results'][0]['name']} (纬度: {lat}, 经度: {lon})")
        
        # 2. 获取天气数据（指定时区+明确参数）
        weather_url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}&"
            f"current=temperature_2m,relative_humidity_2m,wind_speed_10m,weathercode&"
            f"wind_speed_unit=ms&timezone=Asia/Shanghai&forecast_days=1"
        )
        weather_resp = requests.get(weather_url, timeout=10)
        weather_resp.raise_for_status()
        weather_data = weather_resp.json()["current"]
        
        return (
            weather_data["temperature_2m"],
            weather_data["relative_humidity_2m"],
            weather_data["wind_speed_10m"],
            weather_data["weathercode"]
        )
    
    except requests.exceptions.Timeout:
        st.error("❌ 请求超时：请检查网络连接或稍后重试")
    except requests.exceptions.HTTPError as e:
        st.error(f"❌ HTTP错误：{e}（API服务可能暂时不可用）")
    except KeyError:
        st.error("❌ 数据解析错误：API返回格式异常")
    except Exception as e:
        st.error(f"❌ 未知错误：{str(e)}")
    
    return None, None, None, None

# 获取天气数据并展示
temp, humidity, wind, weather_code = get_weather(city_input)
if temp is not None:
    weather_desc = get_weather_desc(weather_code)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("天气情况", weather_desc)
    col2.metric("空气温度 (Ta)", f"{temp} °C")
    col3.metric("相对湿度 (RH)", f"{humidity} %")
    col4.metric("风速 (Va)", f"{wind} m/s")
else:
    st.warning("⚠️ 暂未获取到有效天气数据，请确认城市名称或网络后重试")

st.divider()

# --- 2. 输入 JOS-3 模型所需的人体数据 ---
st.header("👤 2. 个人生理与行为参数")

col_a, col_b = st.columns(2)
with col_a:
    height = st.number_input("身高 (m)", value=1.72, step=0.01, min_value=1.0, max_value=2.5)
    weight = st.number_input("体重 (kg)", value=74.43, step=0.1, min_value=30.0, max_value=200.0)
    age = st.number_input("年龄 (岁)", value=20, step=1, min_value=1, max_value=100)
with col_b:
    fat = st.number_input("体脂率 (%)", value=15.0, step=0.1, min_value=5.0, max_value=50.0)
    sex = st.selectbox("性别", ["male", "female"])

st.markdown("**活动强度:**")
par_options = {
    "A 休息（坐着、安静站立） [PAR=1.0-1.2]": 1.1,
    "B 低 - 慢走（≈3–4 km/h） [PAR=2.0-2.5]": 2.25,
    "C 适中 - 正常步行（≈5 km/h） [PAR=3.0-3.5]": 3.25,
    "D 高 - 快走（≈6 km/h） [PAR=4.0-4.5]": 4.25,
    "E 极强 - 跑步（≈9 km/h） [PAR=8.0-9.0]": 8.5
}
par_choice = st.selectbox("请选择当前的活动状态", list(par_options.keys()))
par_val = par_options[par_choice]

st.markdown("**衣物配置:**")
clo_options = {
    "短袖T恤 + 短裤": 0.36,
    "短袖T恤 + 长裤": 0.50,
    "薄衬衫 + 薄长裤": 0.60,
    "长袖衬衫 + 长裤": 0.70,
    "工作服（单层）": 0.80,
    "薄外套 + 长裤": 1.00,
    "毛衣 + 长裤": 1.20,
    "厚外套 + 毛衣 + 长裤": 1.80,
    "羽绒服组合": 2.20,
    "手动输入 (自定义热阻)": None
}
clo_choice = st.selectbox("请选择穿着的衣物组合", list(clo_options.keys()))

if clo_options[clo_choice] is None:
    clo_val = st.number_input("请输入自定义衣物热阻值 (clo)", value=0.6, step=0.1, min_value=0.0, max_value=5.0)
else:
    clo_val = clo_options[clo_choice]
    st.info(f"当前衣物组合热阻值为: **{clo_val} clo**")

st.divider()

# --- 3. 核心计算与预警建议 ---
st.header("⚙️ 3. 风险预测与预警分析")

if st.button("🚀 开始分析气候风险", type="primary"):
    # 先校验天气数据是否有效
    if temp is None:
        st.error("❌ 请先成功获取天气数据后再进行分析！")
    else:
        # 低温：风寒指数模型
        if temp < 15.0:
            st.info(f"❄️ 当前环境温度 ({temp}℃) 低于15℃，自动切换为 **Wind Chill 风寒指数模型**。")
            
            # 风速转换：m/s → km/h
            v_kmh = wind * 3.6 
            # 风寒指数计算公式
            wci = 13.12 + 0.6215 * temp - 11.37 * (v_kmh ** 0.16) + 0.3965 * temp * (v_kmh ** 0.16)
            wci = round(wci, 1)
            
            st.metric("计算得出风寒等效温度 (WCI)", f"{wci} ℃")
            
            st.subheader("🔔 低温预警建议")
            if wci < -10:
                st.error("**高危警报 (冻伤风险)：** 寒冷刺激强，存在冻伤风险！")
                st.write("应对建议：立即停止户外暴露，寻找温暖避难所，增加极寒防护衣物。")
            elif wci < 0:
                st.warning("**中度风险 (明显寒冷)：** 提示明显寒冷。")
                st.write("应对建议：需穿戴防风厚外套（如羽绒服）、手套及帽子，缩短户外作业时间。")
            elif wci <= 10:
                st.info("**低度风险 (微凉～较冷)：** 提示微凉～较冷。")
                st.write("应对建议：注意保暖，适当增加防风夹克或毛衣，保持身体干燥。")
            else:
                st.success("**状态安全：** 当前风寒指数在安全范围内，正常着装即可。")
                
        # 高温：JOS-3 热生理模型
        else:
            with st.spinner("🔥 正在使用 JOS-3 动态模拟计算盆腔核心温度升温曲线，请稍候..."):
                model = jos3.JOS3(height=height, weight=weight, fat=fat, age=age, sex=sex)
                model.Ta = temp
                model.Tr = temp 
                model.RH = humidity
                model.Va = wind
                model.PAR = par_val
                model.Icl = clo_val
                
                # 初始化阈值时间
                time_to_385 = None
                time_to_390 = None
                time_to_400 = None
                max_minutes = 180
                final_pelvis_temp = 37.0
                
                # 逐分钟模拟
                for m in range(1, max_minutes + 1):
                    model.simulate(times=1, dtime=60)
                    pelvis_temp = model.Tcr[4]  # Pelvis索引为4
                    final_pelvis_temp = pelvis_temp
                    
                    # 记录首次达到阈值的时间
                    if pelvis_temp >= 38.5 and time_to_385 is None:
                        time_to_385 = m
                    if pelvis_temp >= 39.0 and time_to_390 is None:
                        time_to_390 = m
                    if pelvis_temp >= 40.0 and time_to_400 is None:
                        time_to_400 = m
                        break

                # 展示预警时效
                st.subheader("⏱️ 盆腔核心温度 (Tcr) 预警时效预测")
                st.markdown(f"*基于当前工况模拟最长 {max_minutes} 分钟内身体状态的变化。*")
                
                col_t1, col_t2, col_t3 = st.columns(3)
                val_385 = f"{time_to_385} 分钟" if time_to_385 else "安全 (>3小时)"
                val_390 = f"{time_to_390} 分钟" if time_to_390 else "未触发"
                val_400 = f"{time_to_400} 分钟" if time_to_400 else "未触发"
                
                col_t1.metric("到达 38.5℃ (初级警告)", val_385)
                col_t2.metric("到达 39.0℃ (中度危险)", val_390)
                col_t3.metric("到达 40.0℃ (极度危险)", val_400)
                
                # 预警建议
                st.subheader("🔔 高温预警建议")
                if time_to_400 is not None:
                    st.error(f"**极危警报：** 预测在 {time_to_400} 分钟内盆腔核心温度将达到 40.0℃，可能引发致命性热射病！")
                    st.write("**应对建议：** 严禁在此环境下进行该强度作业！必须立即大幅降低活动强度，撤离至空调房，并在作业前做好物理降温准备。")
                elif time_to_390 is not None:
                    st.warning(f"**高风险预警：** 预测在 {time_to_390} 分钟内盆腔核心温度将达到 39.0℃，有严重中暑风险。")
                    st.write("**应对建议：** 单次连续作业时间绝不可超过上述时长！建议采用“干活15分钟，休息15分钟”的轮换制，脱去多余衣物散热。")
                elif time_to_385 is not None:
                    st.warning(f"**关注预警：** 预测在 {time_to_385} 分钟内核心温度将达到 38.5℃，身体出现明显热应激。")
                    st.write("**应对建议：** 请设置闹钟，在此时间点前必须强制休息一次，并足量补充含盐电解质水。")
                else:
                    st.success(f"**状态安全：** 预测连续暴露 {max_minutes} 分钟内，盆腔核心温度未达到危险阈值 (最终温度约 {round(final_pelvis_temp, 2)}℃)。")
                    st.write("**应对建议：** 当前气候及劳动强度适配良好，保持正常补水与常规休息节奏即可。")
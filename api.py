from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests
import sys
import os
import math

# ==========================================
# 导入 JOS-3 模型
# ==========================================
current_dir = os.path.dirname(os.path.abspath(__file__))
jos3_path = os.path.join(current_dir, "JOS-3-master", "src")
sys.path.append(jos3_path)
import jos3

app = FastAPI(title="气候预警核心计算 API")

# ==========================================
# 1. 结构与辅助函数
# ==========================================
class AppInput(BaseModel):
    city: str
    height: float
    weight: float
    age: int
    fat: float
    sex: str
    par: float
    clo: float

def get_at_guidance(at_value):
    """根据综合体感温度(AT)返回人类感受与作业建议"""
    if at_value < 0:
        return {"level": "极度严寒", "feeling": "极其寒冷，刺骨感强烈，有冻伤风险。", "advice": "穿着重型防寒服，严禁长时间静止。"}
    elif 0 <= at_value < 15:
        return {"level": "寒冷", "feeling": "感觉寒冷，热量流失较快。", "advice": "穿着保暖防风衣物，增加肢体活动。"}
    elif 15 <= at_value < 27:
        return {"level": "舒适", "feeling": "温度适宜，无明显冷热应激。", "advice": "适合进行正常的体力作业。"}
    elif 27 <= at_value < 32:
        return {"level": "注意", "feeling": "略感闷热，重体力活动易感疲劳。", "advice": "保持水分补充，适当降低作业强度。"}
    elif 32 <= at_value < 41:
        return {"level": "极度注意", "feeling": "明显炎热，大量出汗，可能出现热痉挛。", "advice": "强制规律饮水，增加阴凉处休息频率。"}
    elif 41 <= at_value < 54:
        return {"level": "危险", "feeling": "极度酷热，极易发生严重热衰竭。", "advice": "严格限制作业时间，启动物理降温干预。"}
    else: 
        return {"level": "极度危险", "feeling": "致命高温环境，极易诱发热射病。", "advice": "立即停止所有非紧急作业！采取强制降温。"}

# ==========================================
# 2. 核心预警预测接口
# ==========================================
@app.post("/predict")
def predict_thermal_risk(data: AppInput):
    # --- 第一步：获取经纬度 ---
    geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={data.city}&count=1&language=en&format=json"
    try:
        geo_resp = requests.get(geo_url, timeout=5).json()
        if "results" not in geo_resp:
            raise HTTPException(status_code=404, detail="未找到该城市，请检查拼写")
        lat = geo_resp["results"][0]["latitude"]
        lon = geo_resp["results"][0]["longitude"]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取城市经纬度失败: {str(e)}")

    # --- 第二步：获取实时天气 (新增 shortwave_radiation 获取太阳辐射) ---
    weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,wind_speed_10m,apparent_temperature,shortwave_radiation"
    try:
        w_data = requests.get(weather_url, timeout=5).json()["current"]
        current_temp = w_data["temperature_2m"]
        current_humidity = w_data["relative_humidity_2m"]
        current_wind = w_data["wind_speed_10m"] / 3.6  # m/s
        current_at = w_data["apparent_temperature"]
        current_sr = w_data["shortwave_radiation"]     # 太阳短波辐射 (W/m²)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取天气失败: {str(e)}")

    at_guidance = get_at_guidance(current_at)

    # --- 第三步：初始化 JOS-3 模型 ---
    model = jos3.JOS3(height=data.height, weight=data.weight, fat=data.fat, age=data.age, sex=data.sex)
    model.Ta = current_temp
    model.Tr = current_temp 
    model.RH = current_humidity
    model.Va = current_wind
    model.PAR = data.par
    model.Icl = data.clo

    # ==========================================
    # 场景 A：低温计算 (WCI + JOS-3)
    # ==========================================
    if current_temp < 15.0:
        v_kmh = current_wind * 3.6
        # 计算 WCI 风寒指数
        wci = 13.12 + 0.6215 * current_temp - 11.37 * (v_kmh ** 0.16) + 0.3965 * current_temp * (v_kmh ** 0.16)
        
        # 运行 JOS-3 热生理推演模型
        time_to_360, time_to_350, time_to_320 = None, None, None
        for m in range(1, 181):
            model.simulate(times=1, dtime=60)
            pelvis_temp = model.Tcr[4] 
            if pelvis_temp <= 36.0 and time_to_360 is None: time_to_360 = m
            if pelvis_temp <= 35.0 and time_to_350 is None: time_to_350 = m
            if pelvis_temp <= 32.0 and time_to_320 is None:
                time_to_320 = m
                break
                
        return {
            "status": "success",
            "mode": "cold_combined",
            "weather": {
                "temp": current_temp, 
                "rh": current_humidity, 
                "wind": round(current_wind, 2),
                "apparent_temp": current_at,
                "solar_radiation": current_sr
            },
            "at_guidance": at_guidance,      
            "wci_result": round(wci, 1), 
            "prediction": {
                "time_to_360": time_to_360,
                "time_to_350": time_to_350,
                "time_to_320": time_to_320
            },
            "message": "WCI风寒指数与JOS-3低温生理模型计算完成"
        }

    # ==========================================
    # 场景 B：高温计算 (双工况 WBGT + JOS-3)
    # ==========================================
    else:
        # 1. 计算自然湿球温度 (Tw) - 采用 Stull 公式
        tw = (current_temp * math.atan(0.151977 * (current_humidity + 8.313659)**0.5) +
              math.atan(current_temp + current_humidity) -
              math.atan(current_humidity - 1.676331) +
              0.00391838 * (current_humidity)**1.5 * math.atan(0.023101 * current_humidity) -
              4.686035)
        
        # 2. 计算黑球温度 (Tg) - 基于辐射与对流热平衡近似
        # 加 0.1 防止除以0报错
        tg = current_temp + (0.037 * current_sr) / ((current_wind + 0.1) ** 0.6)

        # 3. 计算两种工况下的 WBGT
        # 室内/遮阳工况 (无太阳直射，Tg近似等于Ta)
        wbgt_indoor = 0.7 * tw + 0.3 * current_temp
        # 室外暴晒工况 (受太阳直射影响)
        wbgt_outdoor = 0.7 * tw + 0.2 * tg + 0.1 * current_temp

        # 4. 运行 JOS-3 热生理推演模型
        time_to_385, time_to_390, time_to_400 = None, None, None
        for m in range(1, 181):
            model.simulate(times=1, dtime=60)
            pelvis_temp = model.Tcr[4] 
            if pelvis_temp >= 38.5 and time_to_385 is None: time_to_385 = m
            if pelvis_temp >= 39.0 and time_to_390 is None: time_to_390 = m
            if pelvis_temp >= 40.0 and time_to_400 is None:
                time_to_400 = m
                break
                
        return {
            "status": "success",
            "mode": "heat_combined",
            "weather": {
                "temp": current_temp, 
                "rh": current_humidity, 
                "wind": round(current_wind, 2),
                "apparent_temp": current_at,
                "solar_radiation": current_sr
            },
            "at_guidance": at_guidance,      
            "wbgt_result": {
                "indoor_shaded": round(wbgt_indoor, 2),    # 室内/井下作业安全参考线
                "outdoor_exposed": round(wbgt_outdoor, 2)  # 露天暴晒作业安全参考线
            }, 
            "prediction": {
                "time_to_385": time_to_385,
                "time_to_390": time_to_390,
                "time_to_400": time_to_400
            },
            "message": "全场景WBGT环境指数与JOS-3生理推演计算完成"
        }

# ==========================================
# 3. 智能降温服/水泵硬件控制接口
# ==========================================
@app.get("/control_pump")
def control_pump(ip: str, mode: int):
    """
    ⚠️ 核心网络提示：
    如果部署在公网云端（如 Render），此接口无法访问 192.168.x.x 等局域网 IP！
    建议在实际的手机 App 中，让手机直接向 ESP32 发起网络请求，
    因为手机和 ESP32 通常连接在同一个现场 Wi-Fi 下，可以直接内网通信。
    """
    url = f"http://{ip}/set_mode?m={mode}"
    try:
        # 发送 GET 请求，设置 3 秒超时防止卡死
        resp = requests.get(url, timeout=3)
        return {
            "status": "success", 
            "message": f"成功向 {ip} 发送档位 {mode}", 
            "device_response": resp.text
        }
    except requests.exceptions.RequestException as e:
        # 触发这里的报错，99% 是因为云端服务器无法跨越公网访问局域网硬件
        raise HTTPException(
            status_code=504, 
            detail="连接设备失败！云端无法直接访问局域网 IP，请让 App 直接发起控制请求。"
        )

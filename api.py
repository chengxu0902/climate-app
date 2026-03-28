from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware  # 👈 1. 新增：引入跨域处理模块
from pydantic import BaseModel
import sys
import os
import math
import requests

# ==========================================
# 导入 JOS-3 模型
# ==========================================
current_dir = os.path.dirname(os.path.abspath(__file__))
jos3_path = os.path.join(current_dir, "JOS-3-master", "src")
sys.path.append(jos3_path)
import jos3

app = FastAPI(title="气候预警核心计算 API")

# 👇 2. 新增：加上这段配置，保安就会对你的微搭小程序直接放行！
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有前端网址访问（最省事的做法）
    allow_credentials=True,
    allow_methods=["*"],  # 允许 POST, GET 等所有请求
    allow_headers=["*"],
)

# ==========================================
# 1. 结构与辅助函数 (新增了接收天气参数)
# ==========================================
class AppInput(BaseModel):
    # 个体参数
    height: float
    weight: float
    age: int
    fat: float
    sex: str
    par: float
    clo: float
    # 新增：接收前端直接传过来的气象数据！
    temp: float
    rh: float
    wind: float
    at: float
    sr: float

def get_at_guidance(at_value):
    if at_value < 0: return {"level": "极度严寒", "feeling": "极其寒冷，刺骨感强烈，有冻伤风险。", "advice": "穿着重型防寒服，严禁长时间静止。"}
    elif 0 <= at_value < 15: return {"level": "寒冷", "feeling": "感觉寒冷，热量流失较快。", "advice": "穿着保暖防风衣物，增加肢体活动。"}
    elif 15 <= at_value < 27: return {"level": "舒适", "feeling": "温度适宜，无明显冷热应激。", "advice": "适合进行正常的体力作业。"}
    elif 27 <= at_value < 32: return {"level": "注意", "feeling": "略感闷热，重体力活动易感疲劳。", "advice": "保持水分补充，适当降低作业强度。"}
    elif 32 <= at_value < 41: return {"level": "极度注意", "feeling": "明显炎热，大量出汗，可能出现热痉挛。", "advice": "强制规律饮水，增加阴凉处休息频率。"}
    elif 41 <= at_value < 54: return {"level": "危险", "feeling": "极度酷热，极易发生严重热衰竭。", "advice": "严格限制作业时间，启动物理降温干预。"}
    else: return {"level": "极度危险", "feeling": "致命高温环境，极易诱发热射病。", "advice": "立即停止所有非紧急作业！采取强制降温。"}

# ==========================================
# 2. 核心预警预测接口 (纯净计算版)
# ==========================================
@app.post("/predict")
def predict_thermal_risk(data: AppInput):
    # 直接使用前端传过来的干净数据，彻底告别气象局封禁！
    current_temp = data.temp
    current_humidity = data.rh
    current_wind = data.wind
    current_at = data.at
    current_sr = data.sr
    
    at_guidance = get_at_guidance(current_at)

    # --- 初始化 JOS-3 模型 ---
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
        wci = 13.12 + 0.6215 * current_temp - 11.37 * (v_kmh ** 0.16) + 0.3965 * current_temp * (v_kmh ** 0.16)
        
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
            "status": "success", "mode": "cold_combined",
            "weather": {"temp": current_temp, "rh": current_humidity, "wind": round(current_wind, 2), "apparent_temp": current_at, "solar_radiation": current_sr},
            "at_guidance": at_guidance, "wci_result": round(wci, 1), 
            "prediction": {"time_to_360": time_to_360, "time_to_350": time_to_350, "time_to_320": time_to_320},
            "message": "WCI风寒指数与JOS-3低温生理模型计算完成"
        }

    # ==========================================
    # 场景 B：高温计算 (双工况 WBGT + JOS-3)
    # ==========================================
    else:
        tw = (current_temp * math.atan(0.151977 * (current_humidity + 8.313659)**0.5) +
              math.atan(current_temp + current_humidity) - math.atan(current_humidity - 1.676331) +
              0.00391838 * (current_humidity)**1.5 * math.atan(0.023101 * current_humidity) - 4.686035)
        
        tg = current_temp + (0.037 * current_sr) / ((current_wind + 0.1) ** 0.6)

        wbgt_indoor = 0.7 * tw + 0.3 * current_temp
        wbgt_outdoor = 0.7 * tw + 0.2 * tg + 0.1 * current_temp

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
            "status": "success", "mode": "heat_combined",
            "weather": {"temp": current_temp, "rh": current_humidity, "wind": round(current_wind, 2), "apparent_temp": current_at, "solar_radiation": current_sr},
            "at_guidance": at_guidance,      
            "wbgt_result": {"indoor_shaded": round(wbgt_indoor, 2), "outdoor_exposed": round(wbgt_outdoor, 2)}, 
            "prediction": {"time_to_385": time_to_385, "time_to_390": time_to_390, "time_to_400": time_to_400},
            "message": "全场景WBGT环境指数与JOS-3生理推演计算完成"
        }

# ==========================================
# 3. 智能降温服/水泵硬件控制接口
# ==========================================
@app.get("/control_pump")
def control_pump(ip: str, mode: int):
    url = f"http://{ip}/set_mode?m={mode}"
    try:
        resp = requests.get(url, timeout=3)
        return {"status": "success", "message": f"成功向 {ip} 发送档位 {mode}", "device_response": resp.text}
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=504, detail="连接设备失败！云端无法直接访问局域网 IP，请让 App 直接发起控制请求。")

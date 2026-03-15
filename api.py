from fastapi import FastAPI
from pydantic import BaseModel
import sys
import os

# ==========================================
# 导入 JOS-3 模型
# ==========================================
current_dir = os.path.dirname(os.path.abspath(__file__))
jos3_path = os.path.join(current_dir, "JOS-3-master", "src")
sys.path.append(jos3_path)
import jos3

# 创建一个 FastAPI 实例（你的云端大脑）
app = FastAPI(title="气候预警核心计算 API")

# ==========================================
# 定义前端 App 传过来的数据“结构”
# ==========================================
class AppInput(BaseModel):
    height: float
    weight: float
    age: int
    fat: float
    sex: str
    temp: float
    humidity: float
    wind: float
    par: float
    clo: float

# ==========================================
# 核心接口：接收数据 -> 计算 -> 返回结果
# ==========================================
@app.post("/predict")
def predict_thermal_risk(data: AppInput):
    # 1. 应对低温：风寒指数模式
    if data.temp < 15.0:
        v_kmh = data.wind * 3.6
        wci = 13.12 + 0.6215 * data.temp - 11.37 * (v_kmh ** 0.16) + 0.3965 * data.temp * (v_kmh ** 0.16)
        return {
            "status": "success",
            "mode": "wind_chill", 
            "result": round(wci, 1),
            "message": "当前使用风寒指数计算"
        }

    # 2. 应对高温：JOS-3 模型模式
    model = jos3.JOS3(height=data.height, weight=data.weight, fat=data.fat, age=data.age, sex=data.sex)
    model.Ta = data.temp
    model.Tr = data.temp 
    model.RH = data.humidity
    model.Va = data.wind
    model.PAR = data.par
    model.Icl = data.clo
    
    time_to_385 = None
    time_to_390 = None
    time_to_400 = None
    
    # 模拟最长 180 分钟
    for m in range(1, 181):
        model.simulate(times=1, dtime=60)
        pelvis_temp = model.Tcr[4] 
        
        if pelvis_temp >= 38.5 and time_to_385 is None: time_to_385 = m
        if pelvis_temp >= 39.0 and time_to_390 is None: time_to_390 = m
        if pelvis_temp >= 40.0 and time_to_400 is None:
            time_to_400 = m
            break
            
    # 计算完成后，把数据打包成 JSON 格式返回给前端 App
    return {
        "status": "success",
        "mode": "jos3_heat",
        "time_to_385": time_to_385,
        "time_to_390": time_to_390,
        "time_to_400": time_to_400,
        "message": "JOS-3 模型计算完成"
    }
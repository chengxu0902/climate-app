from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
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

# 允许跨域请求 (保安放行配置)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 1. 数据结构与辅助函数
# ==========================================
class AppInput(BaseModel):
    height: float
    weight: float
    age: int
    fat: float
    sex: str
    par: float
    clo: float
    temp: float
    rh: float
    wind: float
    at: float
    sr: float

def get_at_guidance(at_value):
    if at_value < 0: return {"level": "极度严寒", "feeling": "极其寒冷，刺骨感强烈，有冻伤风险。", "advice": "穿着重型防寒服，严禁长时间静止。"}
    elif 0 <= at_value < 15: return {"level": "寒冷", "feeling": "感觉寒冷，热量流失较快。", "advice": "穿着保暖防风衣物，增加肢体活动。"}
    elif 15 <= at_value < 27: return {"level": "舒适", "feeling": "温度适宜，无明显冷热应激。", "advice": "适合进行正常的体力作业。"}
    elif 27 <= at_value < 32: return {"level": "闷热", "feeling": "略感闷热，重体力活动易感疲劳。", "advice": "保持水分补充，适当降低作业强度。"}
    elif 32 <= at_value < 41: return {"level": "炎热", "feeling": "明显炎热，大量出汗，可能出现热痉挛。", "advice": "强制规律饮水，增加阴凉处休息频率。"}
    elif 41 <= at_value < 54: return {"level": "酷热", "feeling": "极度酷热，极易发生严重热衰竭。", "advice": "严格限制作业时间，启动物理降温干预。"}
    else: return {"level": "极度危险", "feeling": "致命高温环境，极易诱发热射病。", "advice": "立即停止所有非紧急作业！采取强制降温。"}

# ==========================================
# 2. 核心预警预测接口 (带分级建议决策大脑)
# ==========================================
@app.post("/predict")
def predict_thermal_risk(data: AppInput):
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
                
        # 低温智能建议生成逻辑
        wci_val = float(wci)
        advice_mode = "cold"
        adv_lvl_id = 1 

        if wci_val < -45.0: adv_lvl_id = 4
        elif wci_val < -25.0: adv_lvl_id = 3
        elif wci_val < -10.0: adv_lvl_id = 2
        else: adv_lvl_id = 1

        if time_to_350 is not None and time_to_350 <= 60 and adv_lvl_id < 3: adv_lvl_id = 3
        if time_to_320 is not None and adv_lvl_id < 4: adv_lvl_id = 4

        if adv_lvl_id == 4:
            adv_title = "🟣 极度危险 (立即撤离/生命维持)"
            adv_summary = "极寒环境，风寒极高。面临重度失温与肢体快速冻伤的双重危险！严禁户外暴露！"
            adv_clo = "🧤 必须全封闭极寒防护系统（≥2.20clo）。严防所有面部和皮肤暴露，使用发热貼干预。"
            adv_act = "🚨 立即停止所有户外作业。全员强制转移至温暖避难所进行被动复温。"
            adv_hyd = "💧 提供温热含糖含盐饮料。强制补充能量，维持核心体温产热。"
        elif adv_lvl_id == 3:
            adv_title = "🔵 危险 (缩短暴露/提供温饮)"
            adv_summary = "极寒酷冷环境，中度冷应激与冻伤风险增加。强制缩短单次暴露时间。"
            adv_clo = "🧤 穿着重型防寒防风系统（≥1.50-2.0clo）。必须佩戴防风手套和帽子盖住耳朵。"
            adv_act = "🏃‍♂️ 严格限制中重体力作业节奏。实行作30休30的轮换制。在温暖干燥遮阴处休息复温。"
            adv_hyd = "💧 足量补充热淡盐水或含糖温热饮料（不可饮酒/咖啡）。采取少量多次原则补水。"
        elif adv_lvl_id == 2:
            adv_title = "❄️ 注意 (常规防寒/增加活动)"
            adv_summary = "寒冷环境，感觉冷，核心体温产热不足。注意肢体保暖，不可长时间静止。"
            adv_clo = "🧤 穿着正常的保暖防风衣物组合（约1.0-1.50clo）。重点保持肢体干燥。"
            adv_act = "🏃‍♂️ 维持正常的作业节奏，增加肢体活动产热，设置强制复温闹钟（作业50分钟休息10分钟）。"
            adv_hyd = "💧 规律饮水！每小时至少补充500-750ml温白开或淡盐水。"
        else:
            adv_title = "✅ 安全 (状态良好/注意防风)"
            adv_summary = "JOS-3模型未预测到明显冷应激，当前风寒指数与着装组合安全。注意日间常规保暖。"
            adv_clo = "🧤 穿着当前的保暖衣物（约0.7-1.00clo）即可良好适配环境。"
            adv_act = "🏃‍♂️ 可按常规节奏进行作业和活动。根据体感变化适当调节休息频率。"
            adv_hyd = "💧 保持正常的饮水频率即可（约250-500ml/h）。"

        combined_advice = {
            "mode_key": advice_mode, 
            "level_id": adv_lvl_id,
            "title": adv_title,
            "summary": adv_summary,
            "clo_desc": adv_clo,
            "act_desc": adv_act,
            "hyd_desc": adv_hyd
        }
                
        return {
            "status": "success", "mode": "cold_combined",
            "weather": {"temp": current_temp, "rh": current_humidity, "wind": round(current_wind, 2), "apparent_temp": current_at, "solar_radiation": current_sr},
            "at_guidance": at_guidance, "wci_result": round(wci, 1), 
            "prediction": {"time_to_360": time_to_360, "time_to_350": time_to_350, "time_to_320": time_to_320},
            "structured_advice": combined_advice,
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
                
        # 高温智能建议生成逻辑
        wbgt_val = float(wbgt_outdoor)
        advice_mode = "heat"
        adv_lvl_id = 1 
        
        if wbgt_val >= 32.2: adv_lvl_id = 4
        elif wbgt_val >= 29.4: adv_lvl_id = 3
        elif wbgt_val >= 26.7: adv_lvl_id = 2
        else: adv_lvl_id = 1

        if time_to_390 is not None and time_to_390 <= 60 and adv_lvl_id < 3: adv_lvl_id = 3
        if time_to_400 is not None and adv_lvl_id < 4: adv_lvl_id = 4

        if adv_lvl_id == 4:
            adv_title = "🔴 极度危险 (强制撤离/强制降温)"
            adv_summary = "极高温环境，致命热射病风险极高！必须强制撤离高温区或立即采取强制降温措施。"
            adv_clo = "🎽 建议着短袖短裤（0.3-0.5clo），严禁着厚重密闭防护服。若需户外严禁暴晒，必须全身物理降温。"
            adv_act = "🚨 立即停止所有重体力作业！实行全员强制休息，每作业30分钟必须在遮阴处休息30分钟。启动应急预案。"
            adv_hyd = "💧 强制补水节奏！每小时饮用1000ml含盐电解质水（运动饮料）。严禁饮用含咖啡因和高糖饮料。"
        elif adv_lvl_id == 3:
            adv_title = "🟠 危险 (高危预警/降温服干预)"
            adv_summary = "酷热环境，极易发生重度热应激。严限作业强度，必须启用物理降温干预。"
            adv_clo = "🎽 选择浅色、吸湿排汗轻便衣物。若着高阻热防护服作业，单次暴露严禁超40分钟，强烈建议开启降温服2档。"
            adv_act = "🏃‍♂️ 严格限制中重体力作业。强制执行作业40分钟，休息20分钟的轮换制。在遮阴处或空调房休息。"
            adv_hyd = "💧 规律补水节奏！每小时足量补充750-1000ml含盐电解质水。采取“少量多次”原则。"
        elif adv_lvl_id == 2:
            adv_title = "🟡 注意 (常规预警/适度休息)"
            adv_summary = "明显炎热环境，热痉挛、热衰竭风险增加。保持常规保水，适当降低强度。"
            adv_clo = "🎽 保持透气、排汗轻便衣物（约0.50clo）。适当增加皮肤散热面积。"
            adv_act = "🏃‍♂️ 适度降低中高强度作业的节奏，设置强制休息闹钟（作业50分钟休息10分钟）。"
            adv_hyd = "💧 规律饮水！每小时至少补充500-750ml凉白开或淡盐水。不可等口渴时才饮水。"
        else:
            adv_title = "🟢 安全 (负荷适中/状态安全)"
            adv_summary = "JOS-3模型未预测到危险核心体温攀升。当前气候与活动强度负荷良好。注意日常防暑降温即可。"
            adv_clo = "🎽 穿着当前的衣物组合即可良好适配。注意作业时的透气性。"
            adv_act = "🏃‍♂️ 可按常规节奏进行作业和活动。根据体感变化适当调节休息频率。"
            adv_hyd = "💧 保持正常的饮水频率即可（约250-500ml/h）。保持体内水分平衡。"

        combined_advice = {
            "mode_key": advice_mode, 
            "level_id": adv_lvl_id,  
            "title": adv_title,
            "summary": adv_summary,
            "clo_desc": adv_clo,
            "act_desc": adv_act,
            "hyd_desc": adv_hyd
        }
        
        return {
            "status": "success", "mode": "heat_combined",
            "weather": {"temp": current_temp, "rh": current_humidity, "wind": round(current_wind, 2), "apparent_temp": current_at, "solar_radiation": current_sr},
            "at_guidance": at_guidance,      
            "wbgt_result": {"indoor_shaded": round(wbgt_indoor, 2), "outdoor_exposed": round(wbgt_outdoor, 2)}, 
            "prediction": {"time_to_385": time_to_385, "time_to_390": time_to_390, "time_to_400": time_to_400},
            "structured_advice": combined_advice,
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

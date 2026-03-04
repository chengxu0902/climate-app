from jos3 import JOS3
import pandas as pd
import matplotlib.pyplot as plt

# 1. 建立模型
mod = JOS3(ex_output="all")

# 2. 设置工况
mod.PAR = 2
mod.To = 36
mod.RH = 60
mod.Va = 0.3
mod.Icl = 0.6

# 3. 运行模型
mod.simulate(60)   # 60 min

# 4. 取出结果
df = pd.DataFrame(mod.dict_results())

# 5. 可视化 TskMean
plt.plot(df["TskMean"])
plt.xlabel("Time (min)")
plt.ylabel("Mean skin temperature (°C)")
plt.title("Variation of mean skin temperature")
plt.show()

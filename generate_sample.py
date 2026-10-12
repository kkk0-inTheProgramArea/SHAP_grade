"""生成一份与原始格式一致的样例成绩文件，用于本地测试。"""
import random
import pandas as pd

random.seed(7)
rows = []
q_ids = list(range(11, 21))  # 11~20 共 10 题
for sid in range(1, 81):
    学号 = f"2026{sid:04d}"
    姓名 = f"学生{sid:02d}"
    rec = {"学号": 学号, "姓名": 姓名}
    total = 0
    for q in q_ids:
        # 选项：大部分正常 A/B/C/D，个别缺扫
        if random.random() < 0.04:
            opt = "缺扫"
            score = None
        else:
            opt = random.choice(["A", "B", "C", "D"])
            score = random.randint(0, 10)
        rec[f"{q}_选项"] = opt
        rec[f"{q}_得分"] = score
        if isinstance(score, int):
            total += score
    # 科目成绩：大部分正常，混入 缺扫/缺考/0
    r = random.random()
    if r < 0.05:
        科目成绩 = "缺扫"
    elif r < 0.10:
        科目成绩 = "缺考"
    elif r < 0.15:
        科目成绩 = 0
    else:
        科目成绩 = total + random.randint(-5, 5)
    rec["科目成绩"] = 科目成绩
    rows.append(rec)

df = pd.DataFrame(rows)
df.to_excel("sample_成绩.xlsx", index=False, sheet_name="Sheet1")
print("已生成 sample_成绩.xlsx，行数：", len(df))
print("列：", df.columns.tolist())

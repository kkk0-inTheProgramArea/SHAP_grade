# 成绩数据清洗 & SHAP 分析小程序

面向中学老师的小工具：上传 Excel / CSV 成绩表 → 网页内做列映射 → 自动剔除
「缺扫 / 缺考 / 0 分 / 空值」等无效学生 → 导出标准成绩宽表；
可选训练 LightGBM 做成绩预测，并输出 SHAP 特征重要性图（分「得分」和「选项」两张图）。

线上体验：https://grade-clean-shap.app.workbuddy.host/

## 本地运行

```bash
pip install -r requirements.txt
python app.py
```

然后浏览器打开 http://127.0.0.1:5000
（Windows 用户也可以直接双击 `启动.bat`）

## 文件说明

| 文件 | 作用 |
|---|---|
| `app.py` | 后端：读文件、列角色自动识别、清洗、LightGBM + SHAP 分析。**顶部「常用设置区」集中了所有可调参数** |
| `templates/index.html` | 前端页面（原生 HTML/JS/CSS，无构建步骤） |
| `static/NotoSansSC.ttf` | 中文字体，保证 SHAP 图里的中文不乱码 |
| `sample_成绩.xlsx` / `sample_各科目.xlsx` | 示例数据 |
| `启动.bat` | Windows 双击启动本地服务 |
| `如何修改代码.md` | 不改代码也能看懂的修改指南 + 常见问题速查表 |

## 想改点什么？

直接改 `app.py` 顶部「★★★ 常用设置区 ★★★」即可，例如默认剔除的关键词、
SHAP 显示前几个特征、多跑几遍取平均的轮数、柱状图颜色等。
详细的改法见 **`如何修改代码.md`**。
改完 `app.py` 需要重启服务，改 `index.html` 刷新浏览器即可。

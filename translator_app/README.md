# 🐟 中译英训练器

上海高考英语中译英刷题 + AI 批改。题库 702 题（上海各区一二模 + 各校高三月考/期中 + 2021 翻译专项汇编），已去重、已清掉作文污染。

## 功能

| 功能 | 说明 |
| --- | --- |
| 定向出题 | 按 年份 / 一模二模 / 月考期中 / 区县学校 筛选，随机抽一套（自选 1~10 道） |
| 对照自评 | 提交后显示参考译文，自己点 🟢会做 / 🟡半会 / 🔴不会 |
| 错题本 | 半会/不会自动进错题本，可导出 JSON、导入 JSON、一键只练错题 |
| 📖 词汇本 | 记录词语/成语的英文翻译与用法；手动加或让 AI 自动查词，可导出导入 |
| 🤖 AI 批改 | 提交后自动打分（X/10）+ 准确性 + 语言问题 + 更地道的一版 |
| 🧠 AI 讲解 | 考点、提示词用法、易错点、加分表达 |
| 题库总览 | 按年/类型统计 + 关键词搜索题干 |
| 📷 拍照识别 | 手写答案拍照/选图 → 视觉模型识别成英文 → 自动填进答案框 |
| ✨ AI 补题 | 读你的错题找薄弱点 + 抽真题学风格，生成针对性新题供训练 |

## 一、本地先跑（确认能用）

```bash
cd translator_app
pip install -r requirements.txt
streamlit run app.py
```

浏览器打开 <http://localhost:8501>。**手机上同一个 WiFi 下**可以打开 `http://<你电脑的IP>:8501`。

## 二、部署成在线版（Streamlit Community Cloud，免费）

前提：有 GitHub 账号。

1. 把 `translator_app` 文件夹上传成一个 GitHub 仓库。
   - ⚠️ `.streamlit/secrets.toml` **不要传**（已写进 `.gitignore`，里面是你的 API Key）。
2. 打开 <https://share.streamlit.io>，用 GitHub 登录，点 **New app**。
3. Repository 选你刚建的仓库，Main file path 填 `app.py`，点 **Deploy**。
4. 等 1~2 分钟，拿到一个 `xxx.streamlit.app` 网址。
5. **填 Key**：在 Streamlit 网页右下角 `Manage app → Settings → Secrets`，粘贴：

   ```toml
   DEEPSEEK_API_KEY = "sk-你的key"
   ```

   保存后 App 会自动重启，AI 批改就生效了。

> 为什么 Key 要放 Secrets 而不是代码里？因为代码仓库可能公开，Secrets 只有你能看到。而且服务端调用 AI，浏览器里看不到你的 Key。

## 三、手机加到桌面

iOS：Safari 打开网址 → 分享 → "添加到主屏幕"。
Android：Chrome 打开网址 → 右上角菜单 → "添加到主屏幕"。

## 文件说明

```
translator_app/
├── app.py                    # 全部界面与逻辑
├── requirements.txt          # 部署时装什么
├── data/questions.json       # 题库（702 题）
├── .streamlit/secrets.toml   # 本地 Key（不上传）
└── .gitignore
```

## 费用

DeepSeek API 按量计费。一次批改约 1~2 千 token，非常便宜；一天练 20 题也就几分钱。

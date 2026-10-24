# -*- coding: utf-8 -*-
"""上海高考英语 中译英翻译训练器

两种用法：
  1) 离线自评（默认，不需要任何 Key）：做题 -> 对照参考译文 -> 自己打分 -> 进错题本
  2) AI 批改（可选）：在侧栏填入 DeepSeek API Key，提交后自动三维度批改
"""
import base64
import hashlib
import json
import os
import random
import re
import urllib.request
import urllib.error
from collections import Counter

import streamlit as st

VISION_MODEL = "deepseek-v4-flash-vision-exp"

st.set_page_config(
    page_title="中译英训练器",
    page_icon="🐟",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# 手机端适配：禁止横向缩放，输入框字号 >=16px 防 iOS 自动放大
st.markdown(
    """
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <style>
      .block-container { padding-top: 1.2rem; padding-bottom: 4rem; max-width: 720px; }
      textarea, input { font-size: 16px !important; }
      .stButton > button { width: 100%; min-height: 44px; }
      .q-cn { font-size: 19px; line-height: 1.7; font-weight: 600; margin: 6px 0 10px; }
      .q-hint { display:inline-block; background:#FFF4E5; color:#B25E00; border-radius:6px;
                padding:2px 8px; font-size:14px; margin-bottom:8px; }
      .q-meta { color:#8A8F98; font-size:13px; margin-bottom:10px; }
      .ref-en { background:#F2F7FF; border-left:4px solid #4A7DFF; padding:10px 12px;
                border-radius:6px; line-height:1.7; }
      .tag-ok { color:#1B8A4B; font-weight:600; }
      .tag-mid { color:#C77C00; font-weight:600; }
      .tag-bad { color:#C0392B; font-weight:600; }
    </style>
    """,
    unsafe_allow_html=True,
)

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "questions.json")


@st.cache_data
def load_bank():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        rows = json.load(f)
    # 去重：同一道中文题干只保留第一条（月考卷常复用一二模真题）
    seen, bank = set(), []
    for r in rows:
        key = re.sub(r"\s+", "", (r.get("chinese") or "")).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        bank.append(r)
    for i, r in enumerate(bank, 1):
        r["uid"] = i
    return bank


BANK = load_bank()


# ---------- 会话状态 ----------
def init_state():
    st.session_state.setdefault("pool", [])
    st.session_state.setdefault("idx", 0)
    st.session_state.setdefault("submitted", False)
    st.session_state.setdefault("_answer_ver", 0)  # 答案版本号：靠它让输入框能被程序改写
    st.session_state.setdefault("_ocr_text", None)  # 识别结果暂存（普通 key，可自由赋值）
    st.session_state.setdefault("wrong", {})      # uid -> {q, count, level}
    st.session_state.setdefault("vocab", {})      # 词汇本：中文词 -> {zh,en,usage,example,tag}
    st.session_state.setdefault("done", [])       # 本轮已练 uid
    st.session_state.setdefault("show_ref", False)


init_state()


def get_answer():
    """读当前答案框内容。"""
    return st.session_state.get(f"answer_{st.session_state.get('_answer_ver', 0)}", "")


def set_answer(text):
    """程序改写答案框：升版本号，把新值预置到新版本 key（在 widget 实例化前，合法）。"""
    ver = st.session_state.get("_answer_ver", 0) + 1
    st.session_state["_answer_ver"] = ver
    st.session_state[f"answer_{ver}"] = text


def clear_answer():
    """清空答案框：升版本号，让输入框变成全新的空 key。"""
    st.session_state["_answer_ver"] = st.session_state.get("_answer_ver", 0) + 1


def pick_pool(year_s, exam_s, district_s, n, shuffle):
    pool = [
        r for r in BANK
        if (year_s == "全部" or r.get("year") == year_s)
        and (exam_s == "全部" or r.get("exam") == exam_s)
        and (district_s == "全部" or r.get("district") == district_s)
    ]
    if shuffle:
        random.shuffle(pool)
    return pool[:n] if n and n < len(pool) else pool


def ai_explain(chinese, hint, reference, api_key):
    """AI 讲透：考点、提示词用法、易错点、可替换表达。"""
    prompt = f"""你是上海高考英语冲刺名师。请拆解下面这道中译英，帮高三学生真正记住它。

【中文原句】{chinese}
【必须使用的提示词/词组】{hint or "无"}
【参考译文】{reference}

请严格按以下格式输出（纯文本，不要 Markdown 代码块）：

考点：…（1 句，说出这道题真正考的是什么）
提示词用法：…（{hint or "本句"} 在这里怎么搭配、常见误用）
易错点：…（2-3 条，每条一行，指出学生最可能写错的地方）
加分表达：…（2 个可以替换的更高级写法，带完整英文句子）
"""
    body = json.dumps(
        {
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.4,
            "stream": False,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + api_key},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return True, data["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        return False, f"API 报错 {e.code}: {e.read().decode('utf-8', 'ignore')[:300]}"
    except Exception as e:  # noqa: BLE001
        return False, f"请求失败：{e}"


def ai_vocab(word, api_key):
    """AI 查词：中文词语/成语 -> 英文翻译 + 用法 + 例句。返回 (ok, dict)。"""
    prompt = f"""你是上海高考英语中译英名师。请解析这个中文词语/成语的英文翻译与用法。

【词语/成语】{word}

请严格按以下 JSON 格式输出（不要 Markdown 代码块，不要多余文字）：
{{"en": "英文翻译（若是短语用动词原形）", "tag": "动词短语/介词搭配/四字格/成语/名词短语 之一", "usage": "用法说明（搭配、介词、常见语境，2 句内）", "example": "一个完整英文例句"}}
"""
    body = json.dumps(
        {
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "stream": False,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + api_key},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        raw = data["choices"][0]["message"]["content"].strip()
        raw = re.sub(r"^```(json)?|```$", "", raw, flags=re.MULTILINE).strip()
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        parsed = json.loads(m.group(0)) if m else {}
        return True, parsed
    except Exception as e:  # noqa: BLE001
        return False, {"error": str(e)}


def get_secret_key():
    """按优先级读 DeepSeek Key：Streamlit Secrets → 环境变量 → 空（侧栏手动填）。"""
    try:
        k = st.secrets.get("DEEPSEEK_API_KEY", "") or ""
        if k:
            return k
    except Exception:  # noqa: BLE001
        pass
    return os.environ.get("DEEPSEEK_API_KEY", "") or ""


def vision_ocr(img_bytes, api_key):
    """拍照识别：把图片发给 DeepSeek 视觉模型，读出手写英文。返回 (ok, text)。"""
    b64 = base64.b64encode(img_bytes).decode()
    prompt = ("这是一张手写英文照片。请逐字识别图中所有手写内容，只输出英文原文本身。"
              "要求：1)严格按字面输出，不要翻译、不要润色、不要纠正拼写、不要加引号或解释；"
              "2)如果看到涂改/划掉后重写的词，只输出最终保留的版本；"
              "3)看不清的字符用[?]标注；4)没有任何文字就输出【空】。")
    body = json.dumps(
        {
            "model": VISION_MODEL,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}},
            ]}],
            "temperature": 0.1,
            "stream": False,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + api_key},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return True, data["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        return False, f"识别失败 {e.code}: {e.read().decode('utf-8', 'ignore')[:300]}"
    except Exception as e:  # noqa: BLE001
        return False, f"请求失败：{e}"


def ai_generate_questions(n, api_key, wrong_items, samples):
    """AI 命题：结合错题（薄弱点）+ 真题（风格），生成 n 道新中译英。返回 (ok, list)。"""
    wrong_desc = "\n".join(
        f"- 给定词「{w.get('hint') or '无'}」：{w.get('chinese','')}"
        for w in wrong_items[:12]
    ) or "（暂无错题，请出常规难度真题）"
    sample_desc = "\n".join(
        f"- {s.get('chinese','')}（给定词:{s.get('hint') or '无'}）→ {s.get('english','')}"
        for s in samples[:6]
    )
    prompt = f"""你是上海高考英语中译英命题老师。请生成 {n} 道新的中译英题，用于训练一位高三学生。

【学生薄弱点（来自错题本，请重点针对这些考点/给定词）】
{wrong_desc}

【真题风格与难度参考】
{sample_desc}

要求：
1. 题干是地道、自然的中文，考点密度和句子长度贴近上海高考真题；
2. 每道题给一个"给定词"（hint，英文单词/词组，学生翻译时必须用到）；
3. 给标准参考译文（english）；
4. 难度贴近真题，不要偏难怪。

严格只输出一个 JSON 数组（不要 Markdown 代码块、不要多余文字），格式：
[{{"chinese":"中文原句","hint":"给定词","english":"参考译文"}}, ...]
"""
    body = json.dumps(
        {
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "stream": False,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + api_key},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        raw = data["choices"][0]["message"]["content"].strip()
        raw = re.sub(r"^```(json)?|```$", "", raw, flags=re.MULTILINE).strip()
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        if not m:
            return False, []
        arr = json.loads(m.group(0))
        if not isinstance(arr, list):
            return False, []
        # 只保留字段齐全的题
        out = [x for x in arr if isinstance(x, dict) and x.get("chinese") and x.get("english")]
        return (True, out) if out else (False, [])
    except Exception as e:  # noqa: BLE001
        return False, []


BUILTIN_KEY = get_secret_key()


def ai_review(chinese, hint, reference, user_answer, api_key):
    """调用 DeepSeek 做三维度批改。返回 (ok, text)。"""
    prompt = f"""你是上海高考英语阅卷老师。请批改下面这道中译英。

【中文原句】{chinese}
【必须使用的提示词/词组】{hint or "无"}
【参考译文】{reference}
【学生译文】{user_answer}

请严格按以下格式输出（纯文本，不要 Markdown 代码块）：

评分：X/10
准确性：…（是否漏译、错译提示词，2 句内）
语言：…（语法、搭配、用词问题，2 句内，并直接指出错处原文）
更地道的一版：…
必记：…（1 条最该记住的点）
"""
    body = json.dumps(
        {
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "stream": False,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + api_key,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return True, data["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        return False, f"API 报错 {e.code}: {e.read().decode('utf-8', 'ignore')[:300]}"
    except Exception as e:  # noqa: BLE001
        return False, f"请求失败：{e}"


# ---------- 侧栏 ----------
with st.sidebar:
    st.header("⚙️ 设置")
    # api_key 提前定义，供「AI 补题」「AI 批改」「拍照识别」「词汇本」共用
    if BUILTIN_KEY:
        api_key = BUILTIN_KEY
    else:
        api_key = st.text_input("DeepSeek API Key", type="password",
                                help="不填也能用：靠参考译文自评。填了才有 AI 批改/补题/查词。")
    years = ["全部"] + sorted({r.get("year", "") for r in BANK if r.get("year")}, reverse=True)
    year_s = st.selectbox("年份", years)
    exams = ["全部"] + sorted({r.get("exam", "") for r in BANK if r.get("exam")})
    exam_s = st.selectbox("考试类型", exams)
    ds = ["全部"] + sorted({r.get("district", "") for r in BANK if r.get("district")})
    district_s = st.selectbox("区县 / 学校", ds)
    n = st.number_input("本轮题量", min_value=1, max_value=10, value=5, step=1)
    shuffle = st.checkbox("随机打乱", value=True)
    if st.button("🎯 出一套新题", use_container_width=True):
        st.session_state.pool = pick_pool(year_s, exam_s, district_s, int(n), shuffle)
        st.session_state.idx = 0
        st.session_state.submitted = False
        clear_answer()
        st.session_state.done = []
        st.rerun()

    st.divider()
    st.subheader("✨ AI 补题")
    st.caption("让 AI 读你的错题 + 抽真题风格，生成针对薄弱点的新题。")
    ai_n = st.number_input("生成题数", min_value=1, max_value=10, value=5, step=1, key="ai_n")
    if st.button("✨ AI 生成题并开始练", use_container_width=True):
        if not api_key:
            st.warning("需要 DeepSeek Key（下方「AI 批改」里配置）")
        else:
            with st.spinner("AI 命题中（约 20~40 秒）…"):
                wrong_items = list(st.session_state.wrong.values())
                samples = random.sample(BANK, min(6, len(BANK)))
                ok, qs = ai_generate_questions(int(ai_n), api_key, wrong_items, samples)
            if ok and qs:
                base = 100000 + random.randint(0, 899999)
                pool = []
                for idx, it in enumerate(qs):
                    pool.append({
                        "uid": base + idx, "year": "AI", "exam": "AI生成",
                        "district": "薄弱点专项", "hint": it.get("hint", ""),
                        "chinese": it.get("chinese", ""), "english": it.get("english", ""),
                        "source": "AI生成",
                    })
                st.session_state.pool = pool
                st.session_state.idx = 0
                st.session_state.submitted = False
                clear_answer()
                st.session_state.show_ref = False
                st.rerun()
            else:
                st.error("生成失败，请重试")

    st.divider()
    st.subheader("🤖 AI 批改")
    if BUILTIN_KEY:
        st.success("AI 批改已启用 ✅")
    else:
        st.caption("Key 只存在你自己的浏览器会话里，不会写进题库文件。")

    st.divider()
    st.subheader("📒 错题本")
    if st.session_state.wrong:
        st.download_button(
            "⬇️ 导出错题",
            data=json.dumps(list(st.session_state.wrong.values()), ensure_ascii=False, indent=2),
            file_name="wrong_book.json",
            mime="application/json",
            use_container_width=True,
        )
    up = st.file_uploader("⬆️ 导入错题", type=["json"])
    if up is not None:
        try:
            loaded = json.loads(up.read().decode("utf-8"))
            for it in loaded:
                st.session_state.wrong[it["uid"]] = it
            st.success(f"已导入 {len(loaded)} 条错题")
        except Exception as e:  # noqa: BLE001
            st.error(f"导入失败：{e}")


# ---------- 主界面 ----------
st.title("🐟 中译英训练器")
tab1, tab2, tab3, tab4 = st.tabs(["练习", "错题本", "词汇本", "题库总览"])

with tab1:
    if not st.session_state.pool:
        st.info("左侧「⚙️ 设置」里选好范围，点 **🎯 出一套新题** 就开始。")
        st.caption(f"题库共 {len(BANK)} 题（已去重），来源：上海各区一二模 + 各校月考/期中 + 2021 翻译专项汇编。")
        st.stop()

    pool = st.session_state.pool
    i = st.session_state.idx
    if i >= len(pool):
        st.success("🎉 这套题做完了！回到左侧再出一套，或去「错题本」复习。")
        st.stop()

    q = pool[i]
    st.progress((i + 1) / len(pool), text=f"第 {i + 1} / {len(pool)} 题")
    st.markdown(
        f'<div class="q-meta">{q.get("year","")} · {q.get("exam","")} · {q.get("district","")}</div>',
        unsafe_allow_html=True,
    )
    if q.get("hint"):
        st.markdown(f'<span class="q-hint">给定词：{q["hint"]}</span>', unsafe_allow_html=True)
    st.markdown(f'<div class="q-cn">{q.get("chinese","")}</div>', unsafe_allow_html=True)

    # 识别结果若有待填入的文本，先在创建输入框之前把它提升为新版本的值
    if st.session_state.get("_ocr_text") is not None:
        set_answer(st.session_state["_ocr_text"])
        st.session_state["_ocr_text"] = None

    st.text_area(
        "你的译文", key=f"answer_{st.session_state.get('_answer_ver', 0)}", height=100,
        placeholder="在这里写英文句子…",
    )

    # 拍照识别手写答案（手机直接调相机 / 或从相册选图）
    with st.expander("📷 拍照识别手写答案", expanded=not get_answer()):
        if not api_key:
            st.caption("需要配置 DeepSeek Key 才能识别（侧栏「AI 批改」里填）。")
        else:
            cam = st.camera_input("拍照", key=f"cam_{q['uid']}_{i}")
            up_img = st.file_uploader("或从相册选图", type=["jpg", "jpeg", "png", "webp"],
                                      key=f"img_{q['uid']}_{i}")
            img_bytes = cam.getvalue() if cam is not None else (up_img.getvalue() if up_img is not None else None)
            if img_bytes is not None:
                # 用图片指纹防重复识别：同一张图只识别一次；重拍/换图（指纹变了）会重新识别
                hkey = f"_ocr_hash_{q['uid']}_{i}"
                img_hash = hashlib.md5(img_bytes).hexdigest()
                if st.session_state.get(hkey) != img_hash:
                    with st.spinner("识别手写中（约 10~20 秒）…"):
                        ok, txt = vision_ocr(img_bytes, api_key)
                    if ok:
                        st.session_state[hkey] = img_hash
                        st.session_state["_ocr_text"] = txt   # 暂存，rerun 后填进输入框
                        st.session_state._ocr_filled = True
                        st.rerun()
                    else:
                        st.error(txt)
        if st.session_state.pop("_ocr_filled", False):
            st.success("已识别并填入上方答案框，请人工瞄一眼再提交。")

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        submit = st.button("✅ 提交并对照", use_container_width=True)
    with col2:
        peek = st.button("👀 先看答案", use_container_width=True)
    with col3:
        skip = st.button("⏭ 跳过", use_container_width=True)

    if skip:
        # 把当前题移到本套队尾：本次稍后还会再遇到，已写的答案保留
        if len(pool) > 1:
            st.session_state.pool.append(st.session_state.pool.pop(i))
        else:
            st.session_state.idx += 1
        st.session_state.submitted = False
        st.session_state.show_ref = False
        st.rerun()

    if peek:
        st.session_state.show_ref = True
    if submit:
        st.session_state.submitted = True
        st.session_state.show_ref = True

    if st.session_state.show_ref:
        st.markdown("**参考译文**")
        st.markdown(f'<div class="ref-en">{q.get("english") or "（暂无）"}</div>',
                    unsafe_allow_html=True)
        hint = q.get("hint") or ""
        if hint and hint not in (q.get("english") or ""):
            st.caption(f"⚠️ 给定词 `{hint}` 未出现在参考译文中，注意核对。")

        if api_key:
            # 1) 自动批改（提交后）
            if st.session_state.submitted:
                ck = f"ai_review_{q['uid']}_{i}"
                if ck not in st.session_state:
                    with st.spinner("AI 正在批改…"):
                        ok, txt = ai_review(q.get("chinese", ""), hint,
                                            q.get("english", ""), get_answer(), api_key)
                    st.session_state[ck] = (ok, txt)
                ok, txt = st.session_state[ck]
                if ok:
                    st.markdown("**🤖 AI 批改**")
                    st.info(txt)
                else:
                    st.error(txt)
            # 2) 讲透这道题（随时可点）
            if st.button("🧠 AI 讲透这道题（考点 / 易错点）", key=f"ex_{i}", use_container_width=True):
                ek = f"ai_explain_{q['uid']}"
                if ek not in st.session_state:
                    with st.spinner("AI 正在拆解…"):
                        ok2, txt2 = ai_explain(q.get("chinese", ""), hint,
                                               q.get("english", ""), api_key)
                    st.session_state[ek] = (ok2, txt2)
                ok2, txt2 = st.session_state[ek]
                st.markdown("**🧠 AI 讲解**")
                (st.info if ok2 else st.error)(txt2)

        st.markdown("**自评**（决定要不要进错题本）")
        c1, c2, c3 = st.columns(3)
        if c1.button("🟢 会做", key=f"g_{i}", use_container_width=True):
            st.session_state.idx += 1
            st.session_state.submitted = False
            clear_answer()
            st.session_state.show_ref = False
            st.rerun()
        if c2.button("🟡 半会", key=f"y_{i}", use_container_width=True):
            st.session_state.wrong[q["uid"]] = {
                "uid": q["uid"], "chinese": q.get("chinese"), "hint": q.get("hint"),
                "english": q.get("english"), "year": q.get("year"),
                "exam": q.get("exam"), "district": q.get("district"),
                "level": "半会", "my": get_answer(),
            }
            st.session_state.idx += 1
            st.session_state.submitted = False
            clear_answer()
            st.session_state.show_ref = False
            st.rerun()
        if c3.button("🔴 不会", key=f"r_{i}", use_container_width=True):
            st.session_state.wrong[q["uid"]] = {
                "uid": q["uid"], "chinese": q.get("chinese"), "hint": q.get("hint"),
                "english": q.get("english"), "year": q.get("year"),
                "exam": q.get("exam"), "district": q.get("district"),
                "level": "不会", "my": get_answer(),
            }
            st.session_state.idx += 1
            st.session_state.submitted = False
            clear_answer()
            st.session_state.show_ref = False
            st.rerun()

with tab2:
    wrong = st.session_state.wrong
    if not wrong:
        st.info("还没有错题。做题时点 🟡半会 或 🔴不会 就会进来。")
    else:
        st.subheader(f"错题 {len(wrong)} 条")
        lv = Counter(v.get("level") for v in wrong.values())
        st.caption("　".join(f"{k}:{v}" for k, v in lv.items()))
        for uid, it in list(wrong.items()):
            with st.expander(f"[{it.get('level')}] {it.get('chinese','')[:34]}…"):
                if it.get("hint"):
                    st.markdown(f'<span class="q-hint">给定词：{it["hint"]}</span>',
                                unsafe_allow_html=True)
                st.write(it.get("chinese"))
                if it.get("my"):
                    st.caption(f"我的译文：{it['my']}")
                st.markdown(f'<div class="ref-en">{it.get("english") or "（暂无）"}</div>',
                            unsafe_allow_html=True)
                st.caption(f"{it.get('year','')} · {it.get('exam','')} · {it.get('district','')}")
                if st.button("✅ 已掌握，移除", key=f"rm_{uid}"):
                    st.session_state.wrong.pop(uid, None)
                    st.rerun()
        st.divider()
        if st.button("🔁 只练错题", use_container_width=True):
            st.session_state.pool = [r for r in BANK if r["uid"] in wrong]
            st.session_state.idx = 0
            st.session_state.submitted = False
            clear_answer()
            st.session_state.show_ref = False
            st.rerun()

with tab3:
    st.subheader("📖 词汇本")
    st.caption("记录词语、成语、固定搭配的英文翻译与用法。手动加，或让 AI 帮你查。")

    with st.expander("➕ 手动添加一个词", expanded=False):
        nz = st.text_input("中文词语/成语", key="v_zh")
        ne = st.text_input("英文翻译", key="v_en")
        nu = st.text_input("用法（搭配 / 介词 / 语境）", key="v_usage")
        nx = st.text_input("例句（英文）", key="v_ex")
        nt = st.selectbox("分类", ["动词短语", "介词搭配", "四字格", "成语", "名词短语", "其他"], key="v_tag")
        if st.button("保存到词汇本", use_container_width=True):
            z = (nz or "").strip()
            if z:
                st.session_state.vocab[z] = {
                    "zh": z, "en": (ne or "").strip(), "usage": (nu or "").strip(),
                    "example": (nx or "").strip(), "tag": nt,
                }
                st.rerun()
            else:
                st.warning("至少填「中文词语/成语」")

    with st.expander("🤖 AI 帮我查词", expanded=False):
        ai_word = st.text_input("输入中文词语 / 成语", key="ai_word")
        if st.button("让 AI 生成翻译用法", use_container_width=True):
            if not ai_word.strip():
                st.warning("先输入词语")
            elif not api_key:
                st.warning("需要 DeepSeek Key（左侧「AI 批改」里配置）")
            else:
                with st.spinner("AI 查询中…"):
                    ok, res = ai_vocab(ai_word.strip(), api_key)
                if ok and res.get("en"):
                    st.session_state.vocab[ai_word.strip()] = {
                        "zh": ai_word.strip(), "en": res.get("en", ""),
                        "usage": res.get("usage", ""), "example": res.get("example", ""),
                        "tag": res.get("tag", "其他"),
                    }
                    st.rerun()
                else:
                    st.error(res.get("error", "生成失败，请重试"))

    vocab = st.session_state.vocab
    st.divider()
    if not vocab:
        st.info("词汇本还是空的。点上方「🤖 AI 帮我查词」输入一个成语试试，比如「保持低调」。")
    else:
        st.subheader(f"共 {len(vocab)} 个词")
        for z, it in list(vocab.items()):
            with st.expander(f"[{it.get('tag','')}] {z} → {it.get('en','')}"):
                st.markdown(f"**{z}** —— {it.get('en','')}")
                if it.get("usage"):
                    st.caption(f"用法：{it['usage']}")
                if it.get("example"):
                    st.markdown(f'<div class="ref-en">{it["example"]}</div>', unsafe_allow_html=True)
                if st.button("🗑 删除", key=f"vd_{z}"):
                    st.session_state.vocab.pop(z, None)
                    st.rerun()
        st.divider()
        c1, c2 = st.columns(2)
        c1.download_button("⬇️ 导出词汇本",
            data=json.dumps(list(vocab.values()), ensure_ascii=False, indent=2),
            file_name="vocab.json", mime="application/json", use_container_width=True)
        vup = c2.file_uploader("⬆️ 导入", type=["json"], key="vup")
        if vup is not None:
            try:
                for it in json.loads(vup.read().decode("utf-8")):
                    st.session_state.vocab[it["zh"]] = it
                st.success("已导入")
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(f"导入失败：{e}")

with tab4:
    st.subheader("题库总览")
    c = Counter((r.get("year"), r.get("exam")) for r in BANK)
    st.dataframe(
        [{"年份": k[0], "类型": k[1], "题数": v} for k, v in sorted(c.items())],
        use_container_width=True, hide_index=True,
    )
    st.caption(f"合计 {len(BANK)} 题（原始 {len(json.load(open(DATA_PATH, encoding='utf-8')))} 条，已按题干去重）。")
    kw = st.text_input("🔍 搜题干关键词")
    if kw:
        hits = [r for r in BANK if kw in (r.get("chinese") or "") or kw in (r.get("english") or "")]
        st.write(f"命中 {len(hits)} 条")
        for r in hits[:50]:
            st.markdown(f'- **{r.get("chinese")}**  \n  <span style="color:#666">{r.get("english")}</span>',
                        unsafe_allow_html=True)

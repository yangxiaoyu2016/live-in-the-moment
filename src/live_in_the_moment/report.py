from __future__ import annotations

import datetime as dt
import html
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


@dataclass(frozen=True)
class TextMoment:
    created: dt.datetime
    content: str

    @property
    def year(self) -> str:
        return self.created.strftime("%Y")

    @property
    def month(self) -> str:
        return self.created.strftime("%Y-%m")


YEARLY_SUMMARY_PROMPT = """请根据下面的朋友圈内容，按年份总结我的生活变化。
要求：
1. 每一年单独总结；
2. 总结主要主题、情绪、生活重心、人际关系、代表性表达；
3. 不要编造没有出现的信息；
4. 不确定的地方写“无法判断”。"""

UNSURE = "无法判断"

ANALYSIS_CATEGORIES = {
    "工作/事业": ["工作", "上班", "公司", "同事", "客户", "项目", "会议", "加班", "方案", "创业", "offer", "deadline"],
    "学习/成长": ["学习", "读书", "课程", "考试", "学校", "毕业", "论文", "研究", "训练", "成长", "复盘"],
    "家庭": ["家人", "家庭", "父母", "爸爸", "妈妈", "孩子", "宝宝", "回家", "亲戚", "过年"],
    "朋友/社交": ["朋友", "同学", "聚会", "见面", "聊天", "生日", "约饭", "一起", "社交"],
    "爱情/伴侣": ["恋爱", "爱人", "男朋友", "女朋友", "老公", "老婆", "结婚", "婚礼", "伴侣"],
    "旅行/城市": ["旅行", "旅游", "出发", "到达", "机场", "机票", "酒店", "海边", "城市", "北京", "上海", "东京"],
    "健康/运动": ["健康", "生病", "医院", "医生", "跑步", "运动", "健身", "睡眠", "疫情", "恢复"],
    "创作/表达": ["写作", "摄影", "拍照", "视频", "音乐", "演出", "舞台", "作品", "创作", "画画", "记录"],
    "美食/日常": ["咖啡", "吃饭", "早餐", "晚餐", "午餐", "火锅", "奶茶", "做饭", "周末", "日常"],
}

EMOTION_CATEGORIES = {
    "偏积极": ["开心", "快乐", "喜欢", "幸福", "美好", "期待", "感谢", "顺利", "可爱", "爱", "笑", "happy", "nice"],
    "偏消沉/压力": ["累", "难过", "崩溃", "焦虑", "生气", "痛", "病", "哭", "失望", "压力", "不想", "sad"],
    "偏思考/回望": ["想", "觉得", "记得", "以后", "希望", "生活", "时间", "选择", "明白", "也许", "可能"],
}

RELATION_CATEGORIES = {
    "家庭关系": ["家人", "家庭", "父母", "爸爸", "妈妈", "孩子", "宝宝", "亲戚"],
    "朋友关系": ["朋友", "同学", "聚会", "见面", "聊天", "生日", "一起"],
    "工作关系": ["同事", "老板", "客户", "团队", "公司", "合作"],
    "亲密关系": ["恋爱", "爱人", "男朋友", "女朋友", "老公", "老婆", "结婚", "伴侣"],
}


def _count_category_hits(text: str, categories: dict[str, list[str]]) -> Counter:
    counter: Counter = Counter()
    lowered = text.lower()
    for label, keywords in categories.items():
        for keyword in keywords:
            counter[label] += lowered.count(keyword.lower())
    return counter


def _top_labels(counter: Counter, limit: int = 3) -> list[str]:
    return [label for label, count in counter.most_common(limit) if count > 0]


def _field_value(labels: list[str]) -> str:
    return "、".join(labels) if labels else UNSURE


def _representative_expressions(records: list[TextMoment], limit: int = 3) -> list[str]:
    contents = [record.content.strip() for record in records if record.content.strip()]
    if not contents:
        return [UNSURE]
    ranked = sorted(contents, key=lambda value: (len(set(value)), len(value)), reverse=True)
    picked: list[str] = []
    for content in ranked:
        compact = " ".join(content.split())
        if len(compact) > 90:
            compact = compact[:87] + "..."
        if compact not in picked:
            picked.append(compact)
        if len(picked) >= limit:
            break
    return picked or [UNSURE]


def _change_summary(current: dict, previous: dict | None) -> str:
    if previous is None:
        return UNSURE
    pieces = []
    if current["main_themes"] != UNSURE and previous["main_themes"] != UNSURE:
        if current["main_themes"] == previous["main_themes"]:
            pieces.append(f"主要主题延续了 {current['main_themes']}。")
        else:
            pieces.append(f"主要主题从 {previous['main_themes']} 变化为 {current['main_themes']}。")
    if current["emotion"] != UNSURE and previous["emotion"] != UNSURE and current["emotion"] != previous["emotion"]:
        pieces.append(f"情绪线索从 {previous['emotion']} 变化为 {current['emotion']}。")
    if current["life_focus"] != UNSURE and previous["life_focus"] != UNSURE and current["life_focus"] != previous["life_focus"]:
        pieces.append(f"生活重心从 {previous['life_focus']} 转向 {current['life_focus']}。")
    return "".join(pieces) if pieces else UNSURE


def build_yearly_summaries(records: list[TextMoment]) -> list[dict]:
    by_year: dict[str, list[TextMoment]] = defaultdict(list)
    for record in records:
        by_year[record.year].append(record)

    summaries = []
    previous: dict | None = None
    for year in sorted(by_year):
        year_records = by_year[year]
        text = "\n".join(record.content for record in year_records if record.content)
        theme_labels = _top_labels(_count_category_hits(text, ANALYSIS_CATEGORIES))
        emotion_labels = _top_labels(_count_category_hits(text, EMOTION_CATEGORIES), limit=1)
        relation_labels = _top_labels(_count_category_hits(text, RELATION_CATEGORIES))
        summary = {
            "year": year,
            "count": len(year_records),
            "main_themes": _field_value(theme_labels),
            "emotion": _field_value(emotion_labels),
            "life_focus": theme_labels[0] if theme_labels else UNSURE,
            "relationships": _field_value(relation_labels),
            "representative_expressions": _representative_expressions(year_records),
        }
        summary["life_change"] = _change_summary(summary, previous)
        summaries.append(summary)
        previous = summary
    return summaries


def _clean_content(lines: list[str]) -> str:
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    content = "\n".join(lines).strip()
    return "" if content == "[No text]" else content


def parse_moments_txt(input_path: Path) -> list[TextMoment]:
    if not input_path.exists():
        raise ValueError(f"Input TXT not found: {input_path}")
    if not input_path.is_file():
        raise ValueError(f"Input path is not a file: {input_path}")

    records: list[TextMoment] = []
    current_time: dt.datetime | None = None
    body_lines: list[str] = []

    def flush() -> None:
        nonlocal current_time, body_lines
        if current_time is None:
            body_lines = []
            return
        records.append(TextMoment(created=current_time, content=_clean_content(body_lines)))
        current_time = None
        body_lines = []

    for raw_line in input_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if TIMESTAMP_RE.match(stripped):
            flush()
            current_time = dt.datetime.strptime(stripped, "%Y-%m-%d %H:%M:%S")
            continue
        if current_time is not None:
            body_lines.append(line)

    flush()
    if not records:
        raise ValueError("No valid Moments timestamps found in TXT")
    return sorted(records, key=lambda item: item.created)


def _html_text(value: str) -> str:
    return html.escape(value, quote=True).replace("\n", "<br>")


def _script_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def _render_report(records: list[TextMoment]) -> str:
    by_month: dict[str, list[TextMoment]] = defaultdict(list)
    for record in records:
        by_month[record.month].append(record)

    month_counts = Counter(record.month for record in records)
    year_counts = Counter(record.year for record in records)
    first = records[0].created
    last = records[-1].created
    busiest_month, busiest_count = month_counts.most_common(1)[0]
    yearly_summaries = build_yearly_summaries(records)

    month_links = "\n".join(
        f"<a href='#month-{month}'>{html.escape(month)} <span>{len(by_month[month])}</span></a>"
        for month in sorted(by_month)
    )
    year_summary = "\n".join(
        f"<li><strong>{html.escape(year)}</strong><span>{count}</span></li>" for year, count in sorted(year_counts.items())
    )

    month_sections = []
    for month in sorted(by_month):
        cards = []
        for record in by_month[month]:
            text = _html_text(record.content) if record.content else "<span class='empty'>无文字</span>"
            cards.append(
                "\n".join(
                    [
                        f"<article class='moment-card' data-year='{record.year}' data-month='{month}'>",
                        f"  <time>{record.created:%Y-%m-%d %H:%M:%S}</time>",
                        f"  <p>{text}</p>",
                        "</article>",
                    ]
                )
            )
        month_sections.append(
            "\n".join(
                [
                    f"<section class='month-section' id='month-{month}'>",
                    f"  <h2>{html.escape(month)} <span>{len(by_month[month])} 条</span></h2>",
                    "\n".join(cards),
                    "</section>",
                ]
            )
        )

    yearly_summary_cards = []
    for summary in yearly_summaries:
        expressions = "\n".join(
            f"<li>{_html_text(expression)}</li>" for expression in summary["representative_expressions"]
        )
        yearly_summary_cards.append(
            "\n".join(
                [
                    "<article class='year-card'>",
                    f"  <h3>{html.escape(summary['year'])} <span>{summary['count']} 条</span></h3>",
                    "  <dl>",
                    f"    <dt>生活变化</dt><dd>{_html_text(summary['life_change'])}</dd>",
                    f"    <dt>主要主题</dt><dd>{_html_text(summary['main_themes'])}</dd>",
                    f"    <dt>情绪</dt><dd>{_html_text(summary['emotion'])}</dd>",
                    f"    <dt>生活重心</dt><dd>{_html_text(summary['life_focus'])}</dd>",
                    f"    <dt>人际关系</dt><dd>{_html_text(summary['relationships'])}</dd>",
                    "  </dl>",
                    "  <h4>代表性表达</h4>",
                    f"  <ul>{expressions}</ul>",
                    "</article>",
                ]
            )
        )

    generated_at = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>微信朋友圈个人报告</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #18202a;
      --muted: #657080;
      --line: #d9dee7;
      --accent: #0f7b6c;
      --accent-dark: #09584d;
      --soft: #e8f3f1;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: "Segoe UI", "Microsoft YaHei", system-ui, sans-serif;
      line-height: 1.6;
    }}
    header {{
      background: linear-gradient(135deg, #113a3a, #0f7b6c);
      color: white;
      padding: 36px 24px 42px;
    }}
    .wrap {{ max-width: 1120px; margin: 0 auto; }}
    h1 {{ margin: 0 0 10px; font-size: 32px; }}
    h2 {{ margin: 0 0 16px; font-size: 22px; }}
    h2 span {{ color: var(--muted); font-size: 15px; font-weight: 500; }}
    .subtitle {{ margin: 0; color: rgba(255,255,255,.82); }}
    main {{ padding: 24px; }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      gap: 12px;
      margin-top: -44px;
    }}
    .stat, .panel, .month-section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 12px 28px rgba(24,32,42,.06);
    }}
    .stat {{ padding: 16px; }}
    .stat strong {{ display: block; font-size: 26px; line-height: 1.15; }}
    .stat span {{ color: var(--muted); font-size: 13px; }}
    .tools {{
      display: grid;
      grid-template-columns: minmax(220px, 1fr) auto;
      gap: 14px;
      align-items: start;
      margin: 18px 0;
    }}
    .panel {{ padding: 16px; }}
    input[type="search"] {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 12px 13px;
      font-size: 15px;
    }}
    .month-nav {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      max-width: 520px;
    }}
    .month-nav a {{
      color: var(--accent-dark);
      background: var(--soft);
      border-radius: 999px;
      padding: 6px 10px;
      text-decoration: none;
      font-size: 13px;
    }}
    .month-nav span {{ color: var(--muted); }}
    .year-list {{ display: flex; gap: 8px; flex-wrap: wrap; padding: 0; margin: 10px 0 0; list-style: none; }}
    .year-list li {{ border: 1px solid var(--line); border-radius: 999px; padding: 5px 10px; }}
    .year-list span {{ color: var(--muted); margin-left: 6px; }}
    .analysis-section {{ margin: 18px 0; }}
    .analysis-intro {{ margin-top: 0; color: var(--muted); }}
    .year-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 12px;
    }}
    .year-card {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 15px;
      background: #ffffff;
    }}
    .year-card h3 {{ margin: 0 0 10px; font-size: 20px; }}
    .year-card h3 span {{ color: var(--muted); font-size: 13px; font-weight: 500; }}
    .year-card h4 {{ margin: 14px 0 6px; font-size: 15px; }}
    dl {{ display: grid; grid-template-columns: 78px 1fr; gap: 8px 10px; margin: 0; }}
    dt {{ color: var(--muted); font-weight: 700; }}
    dd {{ margin: 0; }}
    .year-card ul {{ margin: 6px 0 0; padding-left: 18px; }}
    .month-section {{ padding: 20px; margin: 18px 0; scroll-margin-top: 14px; }}
    .moment-card {{
      border-top: 1px solid var(--line);
      padding: 14px 0;
    }}
    .moment-card:first-of-type {{ border-top: 0; }}
    time {{ color: var(--accent-dark); font-weight: 700; }}
    p {{ margin: 8px 0 0; white-space: normal; }}
    .empty {{ color: var(--muted); font-style: italic; }}
    .empty-state {{ display: none; padding: 22px; text-align: center; color: var(--muted); }}
    .top-link {{
      position: fixed;
      right: 18px;
      bottom: 18px;
      background: var(--accent);
      color: white;
      text-decoration: none;
      border-radius: 999px;
      padding: 9px 13px;
      box-shadow: 0 10px 24px rgba(15,123,108,.28);
    }}
    @media (max-width: 720px) {{
      h1 {{ font-size: 26px; }}
      main {{ padding: 16px; }}
      .tools {{ grid-template-columns: 1fr; }}
      .stats {{ margin-top: -32px; }}
    }}
  </style>
</head>
<body>
  <header id="top">
    <div class="wrap">
      <h1>微信朋友圈个人报告</h1>
      <p class="subtitle">生成时间：{html.escape(generated_at)}，所有内容均来自本地 TXT 文件。</p>
    </div>
  </header>
  <main class="wrap">
    <section class="stats" aria-label="统计">
      <div class="stat"><strong>{len(records)}</strong><span>朋友圈条数</span></div>
      <div class="stat"><strong>{first:%Y-%m-%d}</strong><span>最早日期</span></div>
      <div class="stat"><strong>{last:%Y-%m-%d}</strong><span>最新日期</span></div>
      <div class="stat"><strong>{html.escape(busiest_month)}</strong><span>最活跃月份（{busiest_count} 条）</span></div>
    </section>
    <section class="tools">
      <div class="panel">
        <input id="search" type="search" placeholder="搜索朋友圈文字或日期">
        <p id="resultCount" class="subtitle" style="color: var(--muted); margin-top: 8px;"></p>
        <ul class="year-list">{year_summary}</ul>
      </div>
      <nav class="panel month-nav" aria-label="月份导航">{month_links}</nav>
    </section>
    <section class="analysis-section panel" id="yearly-summary">
      <h2>年度总结 <span>本地分析</span></h2>
      <p class="analysis-intro">以下内容只基于 TXT 中已经出现的朋友圈文字做本地分析；没有足够证据的字段会写“无法判断”。</p>
      <div class="year-grid">
        {"".join(yearly_summary_cards)}
      </div>
    </section>
    <div id="emptyState" class="empty-state panel">没有匹配的朋友圈。</div>
    {"".join(month_sections)}
  </main>
  <a class="top-link" href="#top">回到顶部</a>
  <script>
    const metadata = {_script_json({"moments": len(records), "start": first.strftime("%Y-%m-%d %H:%M:%S"), "end": last.strftime("%Y-%m-%d %H:%M:%S")})};
    const search = document.getElementById('search');
    const resultCount = document.getElementById('resultCount');
    const emptyState = document.getElementById('emptyState');
    const cards = Array.from(document.querySelectorAll('.moment-card'));
    const sections = Array.from(document.querySelectorAll('.month-section'));
    function applySearch() {{
      const query = search.value.trim().toLowerCase();
      let visible = 0;
      for (const card of cards) {{
        const matched = !query || card.textContent.toLowerCase().includes(query);
        card.hidden = !matched;
        if (matched) visible += 1;
      }}
      for (const section of sections) {{
        section.hidden = !Array.from(section.querySelectorAll('.moment-card')).some(card => !card.hidden);
      }}
      resultCount.textContent = `当前显示 ${{visible}} / ${{metadata.moments}} 条`;
      emptyState.style.display = visible ? 'none' : 'block';
    }}
    search.addEventListener('input', applySearch);
    applySearch();
  </script>
</body>
</html>
"""


def build_report_from_txt(input_path: Path, output_path: Path | None = None) -> dict:
    records = parse_moments_txt(input_path)
    html_path = output_path or input_path.with_name("moments_report.html")
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(_render_report(records), encoding="utf-8")
    yearly_summaries = build_yearly_summaries(records)
    return {
        "input": str(input_path),
        "html": str(html_path),
        "moments": len(records),
        "start_time": records[0].created.strftime("%Y-%m-%d %H:%M:%S"),
        "end_time": records[-1].created.strftime("%Y-%m-%d %H:%M:%S"),
        "analysis_prompts": ["yearly_summary"],
        "yearly_summaries": len(yearly_summaries),
    }

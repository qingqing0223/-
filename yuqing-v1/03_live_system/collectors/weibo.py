# -*- coding: utf-8 -*-
"""微博采集器：热榜（公开接口，无需登录）+ 第三方导出（文件导入）+ 开放平台 API + 移动端搜索（实验）

接入模式（WEIBO_MODE，默认 auto）：
- hot     微博热榜公开接口 https://weibo.com/ajax/side/hotSearch（实测可用，无需登录）
- export  第三方导出文件（csv/json/jsonl），放到 WEIBO_EXPORT_DIR（默认 data/weibo_exports/）
- openapi 微博开放平台 API（需开发者资质；搜索接口一般要高级权限）
- mobile  微博移动端搜索（需登录 Cookie WEIBO_COOKIE；有风控/封号风险，建议低频使用）

auto = hot + export 始终执行；配置了开放平台密钥则自动叠加 openapi；配置了 Cookie 则自动叠加 mobile。
"""
import csv
import hashlib
import html
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime

import config
from collectors.base import BaseCollector, http_get_json, ts_iso

_DESKTOP_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
)


def _clean(v):
    if v is None:
        return ""
    return re.sub(r"\s+", " ", str(v).replace("\u3000", " ").replace("\xa0", " ")).strip()


def _strip_html(v):
    s = _clean(v)
    if not s:
        return ""
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return html.unescape(s).strip()


def _parse_weibo_time(v):
    """兼容微博 API 的 'Fri Aug 14 10:00:00 +0800 2026'、ISO、Unix 时间戳"""
    if v is None or str(v).strip() == "":
        return ""
    if isinstance(v, (int, float)):
        t = int(v)
        if t > 10_000_000_000:
            t = t // 1000
        return ts_iso(t)
    s = _clean(v)
    for fmt in (
        "%a %b %d %H:%M:%S %z %Y",
        "%a %b %d %H:%M:%S %Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            continue
    return ""


def _find_key(row, names):
    """按列名查找导出文件中的值；支持去掉空格/下划线/横线后的模糊匹配"""
    if not isinstance(row, dict):
        return ""
    for want in names:
        w = re.sub(r"[\s_\-—–]", "", str(want)).lower()
        for k, v in row.items():
            if k is None:
                continue
            kk = re.sub(r"[\s_\-—–]", "", str(k)).lower()
            if kk == w:
                return v if v is not None else ""
    return ""


def _to_int(v):
    if v is None or str(v).strip() == "":
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    s = _clean(v).replace(",", "").replace("，", "")
    m = re.search(r"([\d.]+)\s*(万|w|W|k|K)?", s)
    if not m:
        return 0
    val = float(m.group(1))
    unit = m.group(2)
    if unit and unit.lower() == "万":
        val *= 10000
    elif unit and unit.lower() == "k":
        val *= 1000
    return int(val)


class WeiboCollector(BaseCollector):
    name = "weibo"
    label = "微博/热榜"
    enabled = True
    interval = 300
    note = "热榜公开接口（无需登录）+ 第三方导出文件；开放平台 API / 移动端 Cookie 可选"

    _token = None

    # ---------------- 公开热榜（无需登录，实测可用） ----------------

    def _request_hot(self):
        data = http_get_json(
            "https://weibo.com/ajax/side/hotSearch",
            headers={"User-Agent": _DESKTOP_UA, "Referer": "https://weibo.com/"},
            timeout=config.HTTP_TIMEOUT,
        )
        if data.get("ok") != 1:
            raise RuntimeError(f"热榜接口返回 ok={data.get('ok')}")
        return (data.get("data") or {}).get("realtime") or []

    def _collect_hot(self):
        kws = config.WEIBO_HOT_KEYWORDS
        if not kws:
            print("[weibo] WEIBO_HOT_KEYWORDS 为空，跳过热榜采集")
            return []
        items = self._request_hot()
        out = []
        seen = set()
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        day = now[:10]
        for it in items:
            word = _strip_html(it.get("word"))
            note = _strip_html(it.get("note"))
            if not word:
                continue
            if not any(k in word or k in note for k in kws):
                continue
            key = f"{word}|{day}"
            if key in seen:
                continue
            seen.add(key)
            rank = int(it.get("realpos") or 0) or len(out) + 1
            heat = _to_int(it.get("num"))
            text = _strip_html(it.get("word_scheme")) or word
            if note and note != word and note not in text:
                text = f"{text} {note}"
            uid = "weibo-hot-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
            out.append({
                "唯一编号": uid,
                "采集时间": now,
                "发布时间": now,
                "平台": "微博",
                "平台组": "微博/热榜",
                "具体来源": f"微博热榜·第{rank}位",
                "账号": "",
                "正文": text,
                "原始链接": "https://s.weibo.com/weibo?q=" + urllib.parse.quote(text),
                "地区": "",
                "省份": "",
                "城市": "",
                "IP属地": "",
                "语言": "中文",
                "总体态度": "待核实",
                "具体问题类别": "-",
                # 热榜本身没有点赞数；WEIBO_HOT_AS_LIKES=1 时用“热度值”近似填入点赞量，
                # 这样高热话题能进入大屏“高热内容”，备注里写明是热度值而非点赞量。
                "点赞量": heat if config.WEIBO_HOT_AS_LIKES else 0,
                "评论量": 0,
                "转发量": 0,
                "是否重点": "是" if rank <= 10 else "否",
                "是否计入统计": config.WEIBO_HOT_COUNTED,
                "备注": f"微博热榜快照 {now}，第{rank}位，热度值{heat}（非点赞量）；态度待人工复核",
            })
        return out

    # ---------------- 第三方导出文件（每天/人工导出也能进流水线） ----------------

    def _parse_export(self, path, ext):
        if ext == ".csv":
            rows = []
            with open(path, encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    if row and any(str(v).strip() for v in row.values()):
                        rows.append(dict(row))
            return rows
        if ext == ".json":
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                for k in ("records", "items", "数据", "记录", "statuses"):
                    if isinstance(data.get(k), list):
                        return data[k]
                if any(v for v in data.values()):
                    return [data]
            return []
        if ext == ".jsonl":
            rows = []
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        rows.append(json.loads(line))
            return rows
        return []

    def _map_export_row(self, row):
        rec = {
            "唯一编号": _clean(_find_key(row, ["唯一编号", "uid", "编号", "微博id", "微博ID", "id", "mid"])),
            "发布时间": _parse_weibo_time(_find_key(row, ["发布时间", "发布日期", "创建时间", "时间", "日期", "created_at"])),
            "平台": _clean(_find_key(row, ["平台", "platform", "平台/网站"])),
            "具体来源": _clean(_find_key(row, ["具体来源", "来源", "来源网站", "来源账号/栏目", "source"])),
            "账号": _clean(_find_key(row, ["账号", "发布人", "用户名", "昵称", "博主", "博主昵称", "发布者", "author", "user_name"])),
            "正文": _clean(_find_key(row, ["微博正文", "正文", "内容", "微博内容", "评论原文", "全文", "text"])),
            "原始链接": _clean(_find_key(row, ["原始链接", "链接", "微博链接", "原文链接", "url"])),
            "地区": _clean(_find_key(row, ["地区", "涉及地区", "地区大类", "region"])),
            "地区组": _clean(_find_key(row, ["地区组", "region_group"])),
            "省份": _clean(_find_key(row, ["省份", "省", "province"])),
            "城市": _clean(_find_key(row, ["城市", "city"])),
            "IP属地": _clean(_find_key(row, ["IP属地", "IP", "ip_location"])),
            "语言": _clean(_find_key(row, ["语言", "原始语言", "language"])),
            "总体态度": _clean(_find_key(row, ["总体态度", "态度", "意见类型", "attitude"])),
            "具体问题类别": _clean(_find_key(row, ["具体问题类别", "问题类别", "issue_category"])),
            "点赞量": _to_int(_find_key(row, ["点赞量", "点赞数", "点赞", "likes", "attitudes_count"])),
            "评论量": _to_int(_find_key(row, ["评论量", "评论数", "评论", "comments", "comments_count"])),
            "转发量": _to_int(_find_key(row, ["转发量", "转发数", "转发", "shares", "reposts_count"])),
            "是否重点": _clean(_find_key(row, ["是否重点", "是否为重点舆情", "重点舆情", "is_key"])),
            "是否计入统计": _clean(_find_key(row, ["是否计入统计", "是否计入", "counted"])),
            "备注": _clean(_find_key(row, ["备注", "说明", "其他备注", "notes"])),
        }
        if not rec["平台"]:
            rec["平台"] = "微博"
        if not rec["语言"]:
            rec["语言"] = "中文"
        if not rec["总体态度"]:
            rec["总体态度"] = "待核实"
        return rec

    def _collect_exports(self):
        d = config.WEIBO_EXPORT_DIR
        if not os.path.isdir(d):
            return []
        processed = os.path.join(d, "processed")
        os.makedirs(processed, exist_ok=True)
        out = []
        seen = set()
        for fn in sorted(os.listdir(d)):
            if fn.startswith("."):
                continue
            path = os.path.join(d, fn)
            ext = os.path.splitext(fn)[1].lower()
            if ext not in (".csv", ".json", ".jsonl"):
                continue
            try:
                rows = self._parse_export(path, ext)
                stamp = datetime.now().strftime("%Y%m%d%H%M%S")
                os.rename(path, os.path.join(processed, f"{stamp}-{fn}"))
            except Exception as e:
                os.rename(path, path + ".error")
                print(f"[weibo] 导出文件解析失败 {fn}: {e}")
                continue
            for row in rows:
                rec = self._map_export_row(row)
                if not rec.get("正文"):
                    continue
                uid = rec.get("唯一编号")
                if not uid:
                    key = "|".join([
                        rec.get("平台") or "微博",
                        rec.get("发布时间") or "",
                        rec.get("账号") or "",
                        str(rec.get("正文") or "")[:200],
                    ])
                    uid = "weibo-export-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
                if uid in seen:
                    continue
                seen.add(uid)
                rec["唯一编号"] = uid
                rec["采集时间"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                rec.setdefault("平台", "微博")
                rec["平台组"] = rec.get("平台组") or "微博/热榜"
                rec.setdefault("语言", "中文")
                rec.setdefault("总体态度", "待核实")
                rec.setdefault("是否计入统计", "是")
                note = rec.get("备注") or ""
                prefix = "微博第三方导出文件导入"
                rec["备注"] = f"{prefix}（{fn}）" + (f"；{note}" if note else "")
                out.append(rec)
        return out

    # ---------------- 开放平台 API（需企业/开发者资质） ----------------

    def _access_token(self):
        if config.WEIBO_ACCESS_TOKEN:
            return config.WEIBO_ACCESS_TOKEN
        if self._token:
            return self._token
        body = urllib.parse.urlencode({
            "client_id": config.WEIBO_APP_KEY,
            "client_secret": config.WEIBO_APP_SECRET,
            "grant_type": "client_credentials",
        }).encode()
        req = urllib.request.Request(
            "https://api.weibo.com/oauth2/access_token",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=config.HTTP_TIMEOUT) as resp:
            self._token = json.loads(resp.read().decode("utf-8"))["access_token"]
        return self._token

    def _search_openapi(self, keyword):
        data = http_get_json(
            "https://api.weibo.com/2/search/statuses.json",
            params={"access_token": self._access_token(), "q": keyword, "count": min(config.MAX_RESULTS, 50)},
            timeout=config.HTTP_TIMEOUT,
        )
        if data.get("error_code"):
            raise RuntimeError(f"开放平台 error {data['error_code']}: {data.get('error')}")
        return data.get("statuses") or []

    def _map_status(self, st, keyword):
        user = st.get("user") or {}
        uid = _clean(st.get("mid") or st.get("idstr") or st.get("id"))
        if not uid:
            key = "|".join([str(user.get("id")), st.get("created_at") or "", _strip_html(st.get("text"))[:200]])
            uid = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
        loc = _clean(user.get("location"))
        province = city = region = ""
        if " " in loc:
            province, city = [x.strip() for x in loc.split(" ", 1)]
            region = province
        else:
            region = province = loc
        uid_user = str(user.get("id") or "")
        bid = _clean(st.get("bid"))
        url = f"https://weibo.com/{uid_user}/{bid}" if uid_user and bid else (
            _clean(st.get("url")) or f"https://m.weibo.cn/status/{uid}"
        )
        src = _strip_html(st.get("source"))
        return {
            "唯一编号": f"weibo-api-{uid}",
            "采集时间": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "发布时间": _parse_weibo_time(st.get("created_at")),
            "平台": "微博",
            "平台组": "微博/热榜",
            "具体来源": f"微博开放平台搜索·{keyword}" + (f"（{src}）" if src else ""),
            "账号": _clean(user.get("screen_name")),
            "正文": _strip_html(st.get("text")),
            "原始链接": url,
            "地区": region,
            "省份": province,
            "城市": city,
            "IP属地": "",
            "语言": "中文",
            "总体态度": "待核实",
            "具体问题类别": "-",
            "点赞量": _to_int(st.get("attitudes_count")),
            "评论量": _to_int(st.get("comments_count")),
            "转发量": _to_int(st.get("reposts_count")),
            "是否重点": "否",
            "是否计入统计": "是",
            "备注": "微博开放平台API采集；态度待人工复核",
        }

    def _collect_openapi(self):
        if not (config.WEIBO_ACCESS_TOKEN or (config.WEIBO_APP_KEY and config.WEIBO_APP_SECRET)):
            return []
        out = []
        for keyword in config.SEARCH_KEYWORDS:
            try:
                statuses = self._search_openapi(keyword)
            except Exception as e:
                print(f"[weibo] 开放平台关键词「{keyword}」失败: {e}")
                continue
            for st in statuses:
                rec = self._map_status(st, keyword)
                if rec["正文"]:
                    out.append(rec)
            time.sleep(config.REQUEST_INTERVAL)
        return out

    # ---------------- 移动端搜索（实验，需登录 Cookie） ----------------

    def _search_mobile(self, keyword):
        data = http_get_json(
            "https://m.weibo.cn/api/container/getIndex",
            params={"containerid": f"100103type=1&q={keyword}", "page_type": "searchall"},
            headers={
                "User-Agent": _MOBILE_UA,
                "Referer": "https://m.weibo.cn/",
                "Cookie": config.WEIBO_COOKIE,
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=config.HTTP_TIMEOUT,
        )
        if data.get("ok") != 1:
            raise RuntimeError(f"移动端搜索返回 ok={data.get('ok')}：{data.get('msg') or 'Cookie 可能失效'}")
        cards = (data.get("data") or {}).get("cards") or []
        mblogs = []
        for card in cards:
            if card.get("card_type") == 9 and card.get("mblog"):
                mblogs.append(card["mblog"])
            elif card.get("card_type") == 11:
                status = (card.get("user") or {}).get("status")
                if status:
                    mblogs.append(status)
        return mblogs

    def _map_mblog(self, mb, keyword):
        user = mb.get("user") or {}
        mid = _clean(mb.get("mblogid") or mb.get("id") or mb.get("bid"))
        uid = f"weibo-mobile-{mid}" if mid else (
            "weibo-mobile-" + hashlib.sha1(str(mb.get("created_at")).encode()).hexdigest()[:16]
        )
        region = _clean(mb.get("region_name") or mb.get("ip_location") or user.get("location"))
        src = _strip_html(mb.get("source"))
        return {
            "唯一编号": uid,
            "采集时间": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "发布时间": _parse_weibo_time(mb.get("created_at")),
            "平台": "微博",
            "平台组": "微博/热榜",
            "具体来源": f"微博移动端搜索·{keyword}" + (f"（{src}）" if src else ""),
            "账号": _clean(user.get("screen_name")),
            "正文": _strip_html(mb.get("text")),
            "原始链接": f"https://m.weibo.cn/detail/{mid}" if mid else "",
            "地区": region,
            "省份": region,
            "城市": "",
            "IP属地": _clean(mb.get("ip_location")),
            "语言": "中文",
            "总体态度": "待核实",
            "具体问题类别": "-",
            "点赞量": _to_int(mb.get("attitudes_count")),
            "评论量": _to_int(mb.get("comments_count")),
            "转发量": _to_int(mb.get("reposts_count")),
            "是否重点": "否",
            "是否计入统计": "是",
            "备注": "微博移动端搜索采集（实验通道）；态度待人工复核",
        }

    def _collect_mobile(self):
        if not config.WEIBO_COOKIE:
            return []
        out = []
        for keyword in config.SEARCH_KEYWORDS:
            try:
                mblogs = self._search_mobile(keyword)
            except Exception as e:
                print(f"[weibo] 移动端关键词「{keyword}」失败: {e}")
                continue
            for mb in mblogs:
                rec = self._map_mblog(mb, keyword)
                if rec["正文"]:
                    out.append(rec)
            time.sleep(config.REQUEST_INTERVAL)
        return out

    # ---------------- 统一入口 ----------------

    def collect(self):
        mode = (config.WEIBO_MODE or "auto").lower()
        records = []
        if mode in ("auto", "hot"):
            try:
                records += self._collect_hot()
            except Exception as e:
                print(f"[weibo] 热榜采集失败: {e}")
        if mode in ("auto", "export"):
            records += self._collect_exports()
        if mode in ("auto", "openapi"):
            try:
                records += self._collect_openapi()
            except Exception as e:
                print(f"[weibo] 开放平台采集失败: {e}")
        if mode in ("auto", "mobile"):
            try:
                records += self._collect_mobile()
            except Exception as e:
                print(f"[weibo] 移动端采集失败: {e}")

        # 按唯一编号去重（热榜话题每天只留一条）
        seen = set()
        out = []
        for r in records:
            uid = _clean(r.get("唯一编号") or r.get("uid"))
            if not uid or uid in seen:
                continue
            seen.add(uid)
            out.append(r)
        return out

    def check(self):
        ok = True
        mode = (config.WEIBO_MODE or "auto").lower()
        print("[weibo] 采集模式:", mode)

        print("[weibo] 热榜公开接口:", end=" ")
        try:
            items = self._request_hot()
            kws = config.WEIBO_HOT_KEYWORDS
            matched = [it for it in items if any(
                k in (it.get("word") or "") or k in (it.get("note") or "") for k in kws
            )] if kws else []
            print(f"可达，热榜共 {len(items)} 条，命中关键词 {len(matched)} 条")
            for it in matched[:5]:
                print("   ", it.get("realpos"), it.get("word"), it.get("num"))
            if not kws:
                print("   提示：WEIBO_HOT_KEYWORDS 为空，不会采到热榜内容")
        except Exception as e:
            print("失败:", e)
            ok = False

        export_dir = config.WEIBO_EXPORT_DIR
        if os.path.isdir(export_dir):
            files = [f for f in os.listdir(export_dir)
                     if not f.startswith(".") and not os.path.isdir(os.path.join(export_dir, f))]
            print("[weibo] 第三方导出目录:", export_dir, "（待处理文件", len(files), "个）")
        else:
            print("[weibo] 第三方导出目录:", export_dir, "（目录未创建，可忽略）")

        if config.WEIBO_ACCESS_TOKEN or (config.WEIBO_APP_KEY and config.WEIBO_APP_SECRET):
            print("[weibo] 开放平台密钥已配置:", end=" ")
            try:
                tok = self._access_token()
                print("access_token 获取成功（长度", len(tok), "）")
            except Exception as e:
                print("获取失败:", e)
                ok = False
        else:
            print("[weibo] 开放平台密钥未配置（可选；搜索接口一般需企业资质）")

        if config.WEIBO_COOKIE:
            print("[weibo] 移动端 Cookie 已配置:", end=" ")
            try:
                mblogs = self._search_mobile(config.SEARCH_KEYWORDS[0])
                print(f"搜索成功，返回 {len(mblogs)} 条")
            except Exception as e:
                print("搜索失败:", e)
                ok = False
        else:
            print("[weibo] 移动端 Cookie 未配置（可选；有风控/封号风险，建议低频）")
        return ok

    def sample(self):
        return [
            {
                "发布时间": "2026-08-14 09:47:00",
                "平台": "微博",
                "具体来源": "微博搜索·民族团结法",
                "账号": "@示例用户A",
                "正文": "支持民族团结进步促进法，各民族要像石榴籽一样紧紧抱在一起。",
                "原始链接": "https://weibo.com/demo/0001",
                "地区": "四川",
                "地区组": "四川、甘肃民族地区",
                "省份": "四川",
                "城市": "成都",
                "IP属地": "四川",
                "语言": "中文",
                "总体态度": "支持认可",
                "具体问题类别": "-",
                "点赞量": 328,
                "评论量": 56,
                "转发量": 12,
                "是否重点": "否",
                "是否计入统计": "是",
                "备注": "collect.py --demo 示例记录（编造）",
            },
            {
                "发布时间": "2026-08-14 10:01:00",
                "平台": "微博",
                "具体来源": "微博超话讨论",
                "账号": "@示例用户J",
                "正文": "担心促进法在基层落实不到位，希望能有监督渠道。",
                "原始链接": "https://weibo.com/demo/0010",
                "地区": "甘肃",
                "地区组": "四川、甘肃民族地区",
                "省份": "甘肃",
                "城市": "临夏",
                "IP属地": "甘肃",
                "语言": "中文",
                "总体态度": "担忧影响",
                "具体问题类别": "担忧影响",
                "点赞量": 18,
                "评论量": 7,
                "转发量": 0,
                "是否重点": "否",
                "是否计入统计": "是",
                "备注": "collect.py --demo 示例记录（编造）",
            },
        ]

# -*- coding: utf-8 -*-
"""잰 값에서 양식을 정리한다. AI가 읽을 양을 줄이고, 틀(모든 쪽에 되풀이되는 것)을 자동으로 다시 그릴 수 있게 한다.

쓰는 법:  python style.py <양식 측정 폴더>
만드는 것
  frame.json         틀: 되풀이되는 도형과 그림(그대로 다시 그린다), 쪽마다 글만 바뀌는 자리(제목, 쪽 번호)
  frame/             틀에 쓰는 그림 (원본에서 잘라낸 것)
  rules.draft.json   검사 규칙 초안. 작업/rules.json 으로 복사해서 쓴다
  양식요약.md        글자 단계, 색, 선 굵기, 틀, 쪽별 한 줄 요약
"""
import fitz, json, sys, io, os, re, math, collections, statistics

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
if len(sys.argv) < 2:
    print(__doc__)
    sys.exit(1)
MD = sys.argv[1]
meas = json.load(open(os.path.join(MD, "measure.json"), encoding="utf-8"))
W, H = meas["W"], meas["H"]
pages = meas["pages"]
N = len(pages)
os.makedirs(os.path.join(MD, "frame"), exist_ok=True)
src = fitz.open(meas["source"])


def sk(v):
    return round(v * 2) / 2


def rr(v):
    return int(round(v))


def is_bg(s):
    return s["kind"] == "rect" and s["w"] >= 0.97 * W and s["h"] >= 0.97 * H


# ---------- 1. 되풀이되는 것 ----------
rep = collections.defaultdict(dict)
for pg in pages:
    n = pg["page"]
    for s in pg["shapes"]:
        if is_bg(s):
            continue
        rep[("shape", s["kind"], rr(s["x"]), rr(s["y"]), rr(s["w"]), rr(s["h"]), s["fill"], s["stroke"])].setdefault(n, s)
    for im in pg["images"]:
        rep[("image", rr(im["x"]), rr(im["y"]), rr(im["w"]), rr(im["h"]))].setdefault(n, im)
    for t in pg["texts"]:
        if "base" in t and len(t["t"]) >= 6:
            rep[("text", t["t"], rr(t["ox"]), rr(t["base"]), sk(t["size"]))].setdefault(n, t)
    for l in pg["outline_lines"]:
        if l["w"] > 30:
            rep[("outline", rr(l["x"]), rr(l["y"]), rr(l["w"]), rr(l["h"]))].setdefault(n, l)
need = max(3, math.ceil(0.4 * N))
static = {k: v for k, v in rep.items() if len(v) >= need}

score = collections.Counter()
for k, v in static.items():
    for n in v:
        score[n] += 1
if score:
    top = max(score.values())
    body = sorted(n for n, c in score.items() if c >= 0.6 * top)
else:
    body = [pg["page"] for pg in pages][1:-1] or [pg["page"] for pg in pages]
bodyset = set(body)
P = {pg["page"]: pg for pg in pages}
static = {k: v for k, v in static.items() if len(set(v) & bodyset) >= 0.6 * len(body)}


def n_elems(n):
    pg = P[n]
    return len(pg["texts"]) + len(pg["shapes"]) + len(pg["images"]) + len(pg["outline_lines"])


cands = [n for n in body if all(n in v for v in static.values())] or body
ref_page = min(cands, key=n_elems)

# ---------- 2. 쪽마다 글만 바뀌는 자리 ----------
def cluster(items, keyf, tol):
    items = sorted(items, key=keyf)
    out, cur = [], []
    for it in items:
        if cur and keyf(it) - keyf(cur[-1]) > tol:
            out.append(cur)
            cur = []
        cur.append(it)
    if cur:
        out.append(cur)
    return out


static_text_ids = {id(t) for k, v in static.items() if k[0] == "text" for t in v.values()}
static_outline_ids = {id(t) for k, v in static.items() if k[0] == "outline" for t in v.values()}
var_text = []
groups = collections.defaultdict(list)
for n in body:
    for t in P[n]["texts"]:
        if "base" in t and id(t) not in static_text_ids:
            groups[(t["font"], sk(t["size"]), t["color"])].append((n, t))
for (font, size, color), lst in groups.items():
    for cl in cluster(lst, lambda x: x[1]["base"], 0.45):
        pgs = collections.Counter(n for n, _ in cl)
        if len(pgs) < max(3, 0.35 * len(body)) or max(pgs.values()) > 2:
            continue
        ts = [t for _, t in cl]
        if len({t["t"] for t in ts}) == 1:
            continue
        alts = {"left": [t["ox"] for t in ts], "right": [t["x"] + t["w"] for t in ts], "center": [t["x"] + t["w"] / 2 for t in ts]}
        sd = {k: statistics.pstdev(v) for k, v in alts.items()}
        al = min(sd, key=sd.get)
        if sd[al] > 1.2:
            continue
        numeric = all(re.fullmatch(r"[\s\-–—\d/]+", t["t"]) for t in ts)
        var_text.append({"mode": "live", "font": font, "size": size, "color": color, "bold": ts[0]["bold"], "align": al,
                         "x": round(statistics.median(alts[al]), 2), "base": round(statistics.median(t["base"] for t in ts), 2),
                         "pages": sorted(pgs), "numeric": numeric, "samples": [t["t"] for t in ts][:4],
                         "mixed": any("runs" in t for t in ts), "y_top": min(t["y"] for t in ts), "y_bot": max(t["y"] + t["h"] for t in ts),
                         "x_min": min(t["x"] for t in ts), "x_max": max(t["x"] + t["w"] for t in ts)})
# 윤곽선으로 바뀐 글자 가운데 같은 자리에서 시작하는 것
ogroups = collections.defaultdict(list)
for n in body:
    for l in P[n]["outline_lines"]:
        if id(l) not in static_outline_ids and l["words"] >= 1:
            ogroups[(sk(l["est_size"]), l["color"])].append((n, l))
for (size, color), lst in ogroups.items():
    for cl in cluster(lst, lambda x: x[1]["y"], 1.5):
        pgs = collections.Counter(n for n, _ in cl)
        if len(pgs) < max(3, 0.35 * len(body)) or max(pgs.values()) > 1:
            continue
        ls = [l for _, l in cl]
        alts = {"left": [l["x"] for l in ls], "right": [l["x"] + l["w"] for l in ls], "center": [l["x"] + l["w"] / 2 for l in ls]}
        sd = {k: statistics.pstdev(v) for k, v in alts.items()}
        al = min(sd, key=sd.get)
        if sd[al] > 2.5 or len({(rr(l["w"])) for l in ls}) == 1:
            continue
        var_text.append({"mode": "outline", "est_size": size, "color": color, "align": al, "x": round(statistics.median(alts[al]), 2),
                         "ink_top": round(statistics.median(l["y"] for l in ls), 2), "ink_bottom": round(statistics.median(l["y"] + l["h"] for l in ls), 2),
                         "pages": sorted(pgs), "numeric": all(l["w"] < 3 * l["h"] for l in ls), "samples": [],
                         "y_top": min(l["y"] for l in ls), "y_bot": max(l["y"] + l["h"] for l in ls),
                         "x_min": min(l["x"] for l in ls), "x_max": max(l["x"] + l["w"] for l in ls)})
# 제목: 글꼴이나 크기가 쪽마다 달라도 같은 자리에서 시작하면 제목으로 본다
tc = []
for n in body:
    c = [t for t in P[n]["texts"] if "base" in t and t["y"] + t["h"] < 0.2 * H and sk(t["size"]) >= 14 and id(t) not in static_text_ids]
    if c:
        top = max(sk(t["size"]) for t in c)
        tc.append((n, min((t for t in c if sk(t["size"]) == top), key=lambda t: t["x"])))
live_title = None
if tc:
    cl = max(cluster(tc, lambda x: x[1]["ox"], 6.0), key=len)
    if len(cl) >= max(3, 0.5 * len(body)):
        ts = [t for _, t in cl]
        var = collections.Counter((t["font"], sk(t["size"]), round(t["base"], 1), t["color"], round(t["ox"], 1)) for t in ts)
        (f0, s0, b0, c0, x0t), _ = var.most_common(1)[0]
        var_text = [v for v in var_text if not (v["mode"] == "live" and v["y_bot"] < 0.2 * H and abs(v["x"] - statistics.median(t["ox"] for t in ts)) < 8)]
        live_title = {"mode": "live", "role": "title", "font": f0, "size": s0, "color": c0, "bold": "bold" in f0.lower(), "align": "left",
                      "x": x0t, "base": b0, "pages": sorted(n for n, _ in cl), "numeric": False,
                      "samples": [t["t"] for t in ts if t["font"] == f0 and sk(t["size"]) == s0][:4], "mixed": any("runs" in t for t in ts),
                      "variants": [{"font": f, "size": s, "base": b, "color": c, "x": x, "pages": k, "sample": next(t["t"] for t in ts if t["font"] == f and sk(t["size"]) == s and round(t["base"], 1) == b and round(t["ox"], 1) == x)} for (f, s, b, c, x), k in var.most_common()],
                      "y_top": min(t["y"] for t in ts), "y_bot": max(t["y"] + t["h"] for t in ts), "x_min": min(t["x"] for t in ts), "x_max": max(t["x"] + t["w"] for t in ts),
                      "by_page": {n: t["t"] for n, t in cl}}
        var_text.append(live_title)
# 역할 붙이기
titles = [v for v in var_text if not v["numeric"] and v["y_bot"] < 0.3 * H and "role" not in v]
if titles and not live_title:
    max(titles, key=lambda v: (len(v["pages"]), v.get("size") or v.get("est_size"))).update(role="title")
nums = [v for v in var_text if v["numeric"]]
if nums:
    max(nums, key=lambda v: len(v["pages"])).update(role="pageno")
k = 0
for v in var_text:
    if "role" not in v:
        k += 1
        v["role"] = f"etc{k}"

# ---------- 3. 되풀이되는 도형과 그림을 다시 그릴 수 있게 정리 ----------
static_items = []
chrome_rules = []
allowed_text = []
ci = 0
for key, v in sorted(static.items(), key=lambda kv: -len(kv[1])):
    e = v.get(ref_page) or next(iter(v.values()))
    pg_of = ref_page if ref_page in v else next(iter(v))
    kind = key[0]
    name = None
    if kind == "shape":
        s = e
        if s["kind"] == "rect" and "fill_opacity" not in s and "dash" not in s:
            it = {"draw": "rect", "x": s["x"], "y": s["y"], "w": s["w"], "h": s["h"], "fill": s["fill"], "stroke": s["stroke"], "sw": s["sw"]}
        elif s["kind"] == "line" and "dash" not in s and (s["w"] < 0.05 or s["h"] < 0.05):
            it = {"draw": "line", "x": s["x"], "y": s["y"], "w": s["w"], "h": s["h"], "stroke": s["stroke"] or s["fill"], "sw": s["sw"] or max(min(s["w"], s["h"]), 0.25)}
        else:
            it = {"draw": "crop", "x": s["x"] - s["sw"], "y": s["y"] - s["sw"], "w": s["w"] + 2 * s["sw"], "h": s["h"] + 2 * s["sw"]}
        name = f"되풀이 도형 {s['kind']}"
        box = (s["x"], s["y"], s["w"], s["h"])
    elif kind == "image":
        im = e
        f = im.get("file") or im.get("view")
        it = {"draw": "image", "x": im["x"], "y": im["y"], "w": im["w"], "h": im["h"], "file": f}
        name = "되풀이 그림"
        box = (im["x"], im["y"], im["w"], im["h"])
    elif kind == "text":
        t = e
        it = {"draw": "text", "t": t["t"], "x": t["ox"], "base": t["base"], "font": t["font"], "size": sk(t["size"]), "color": t["color"], "bold": t["bold"]}
        allowed_text.append(t["t"])
        name = f"되풀이 글 '{t['t'][:16]}'"
        box = (t["x"], t["y"], t["w"], t["h"])
    else:  # 윤곽선 글자: 그림으로 잘라 쓴다
        l = e
        it = {"draw": "crop", "x": l["x"] - 0.5, "y": l["y"] - 0.5, "w": l["w"] + 1, "h": l["h"] + 1, "note": "윤곽선으로 바뀐 글. 그림으로 넣는다"}
        name = "되풀이 글(윤곽선)"
        box = (l["x"], l["y"], l["w"], l["h"])
    if it["draw"] == "crop":
        ci += 1
        rect = fitz.Rect(it["x"], it["y"], it["x"] + it["w"], it["y"] + it["h"]) & src[pg_of - 1].rect
        pix = src[pg_of - 1].get_pixmap(matrix=fitz.Matrix(8, 8), clip=rect, alpha=False)
        fn = f"frame/crop{ci:02d}.png"
        pix.save(os.path.join(MD, fn))
        it.update(x=round(rect.x0, 3), y=round(rect.y0, 3), w=round(rect.width, 3), h=round(rect.height, 3), file=fn)
    it["pages"] = sorted(v)
    it["name"] = f"{name} {len(static_items) + 1}"
    static_items.append(it)
    pad = 1.5
    reg = [round(max(0, box[0] - pad), 1), round(max(0, box[1] - pad), 1), round(min(W, box[0] + box[2] + pad), 1), round(min(H, box[1] + box[3] + pad), 1)]
    if it["draw"] in ("rect", "line"):
        chrome_rules.append({"name": it["name"], "kind": "shape", "x": it["x"], "y": it["y"], "w": it["w"], "h": it["h"], "fill": it.get("fill"),
                             "stroke": it.get("stroke"), "sw": it.get("sw"), "tol": 0.3})
    else:
        # 그림으로 넣은 것은 다시 그릴 때 가장자리가 조금 옅어진다. 자리와 모습을 보고 색은 넉넉히 본다
        chrome_rules.append({"name": it["name"], "kind": "pixels", "region": reg, "ref_page": pg_of, "color_tol": 30, "max": 0.3})

for v in var_text:
    nm = {"title": "제목", "pageno": "쪽 번호"}.get(v["role"], "쪽마다 바뀌는 글 " + v["role"])
    reg = [round(max(0, v["x_min"] - 4), 1), round(max(0, v["y_top"] - 3), 1), round(min(W, (W - 10) if v["role"] == "title" else v["x_max"] + 4), 1), round(min(H, v["y_bot"] + 3), 1)]
    if v["role"] not in ("title", "pageno"):
        continue
    if v["mode"] == "live":
        r = {"name": nm, "kind": "base", "region": reg, "base": v["base"], "size": v["size"], "font": v["font"], "color": v["color"], "tol": 0.3}
        if len(v.get("variants", [])) > 1:
            r["alts"] = [{"base": q["base"], "size": q["size"], "font": q["font"], "ox": q["x"]} for q in v["variants"]]
        r[{"left": "ox", "right": "right", "center": "cx"}[v["align"]]] = v["x"]
    else:
        r = {"name": nm, "kind": "ink", "region": reg, "color": v["color"], "top": v["ink_top"], "bottom": v["ink_bottom"]}
        r[{"left": "left", "right": "right", "center": "cx"}[v["align"]]] = v["x"]
    chrome_rules.append(r)

# ---------- 한글 글꼴과 영문·숫자 글꼴의 짝 ----------
# 많은 회사 자료가 한글은 한 글꼴, 영문과 숫자와 빈칸은 다른 글꼴로 찍는다. 그 습관이 있으면 찾아서 적어 둔다.
pair_cnt = collections.defaultdict(collections.Counter)
for pg in pages:
    for t in pg["texts"]:
        sp = t.get("spans", [])
        han = [s for s in sp if re.search(r"[가-힣]", s["t"])]
        if not han:
            continue
        hf = han[0]["font"]
        for s in sp:
            n_lat = len(re.findall(r"[A-Za-z0-9]", s["t"]))
            if n_lat:
                pair_cnt[hf][s["font"]] += n_lat
latin_for = {}
cal_fonts = {}
cp_ = os.path.join(MD, "calib.json")
if os.path.exists(cp_):
    cal_fonts = json.load(open(cp_, encoding="utf-8"))["fonts"]
for hf, c in pair_cnt.items():
    lf, n = c.most_common(1)[0]
    tot = sum(c.values())
    if lf != hf and tot >= 20 and n / tot >= 0.6 and cal_fonts.get(hf, {}).get("ok") and cal_fonts.get(lf, {}).get("ok"):
        a_, b_ = cal_fonts[hf]["face"], cal_fonts[lf]["face"]
        if a_ != b_:
            latin_for[a_] = b_

bg = "FFFFFF"
for s in P[ref_page]["shapes"]:
    if is_bg(s) and s["fill"]:
        bg = s["fill"]
for v in var_text:
    v.pop("by_page", None) if False else None
frame = {"W": W, "H": H, "latin_for": latin_for, "body_pages": body, "ref_page": ref_page, "bg": bg, "static": static_items, "text": var_text}
json.dump(frame, open(os.path.join(MD, "frame.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# ---------- 4. 검사 규칙 초안 ----------
fonts = collections.Counter()
sizes = collections.Counter()
osizes = collections.Counter()
tcol, fcol, scol = collections.Counter(), collections.Counter(), collections.Counter()
for pg in pages:
    for t in pg["texts"]:
        for s in t.get("spans", [t]):
            fonts[re.sub(r"(-?Bold|-?Regular|MT|PS|-?Italic)", "", s["font"].split("+")[-1])] += 1
            sizes[sk(s["size"])] += 1
            tcol[s["color"]] += 1
    for l in pg["outline_lines"]:
        osizes[l["est_size"]] += 1
        for c in l["colors"]:
            if c:
                tcol[c] += 1
    for s in pg["shapes"]:
        if s["fill"]:
            fcol[s["fill"]] += 1
        if s["stroke"]:
            scol[s["stroke"]] += 1
static_ids = {id(x) for v in static.values() for x in v.values()}
xs0, ys0, xs1, ys1 = [], [], [], []
frame_ids = set(static_ids)
for n in body:
    pg = P[n]
    el = [e for e in pg["texts"] + pg["shapes"] + pg["images"] + pg["outline_lines"] if id(e) not in frame_ids and not (e.get("kind") == "rect" and is_bg(e))]
    # 제목과 쪽 번호 자리는 뺀다
    def in_var(e):
        for v in var_text:
            if v["role"] in ("title", "pageno") and e["y"] >= v["y_top"] - 2 and e["y"] + e["h"] <= v["y_bot"] + 2 and (v["role"] == "title" or (e["x"] >= v["x_min"] - 3 and e["x"] + e["w"] <= v["x_max"] + 3)):
                return True
        return False
    el = [e for e in el if not in_var(e) and e["x"] >= -1 and e["y"] >= -1 and e["x"] + e["w"] <= W + 1 and e["y"] + e["h"] <= H + 1]
    if not el:
        continue
    xs0.append(min(e["x"] for e in el)); ys0.append(min(e["y"] for e in el))
    xs1.append(max(e["x"] + e["w"] for e in el)); ys1.append(max(e["y"] + e["h"] for e in el))
safe = {"x0": round(min(xs0) - 0.5, 1), "y0": round(min(ys0) - 0.5, 1), "x1": round(max(xs1) + 0.5, 1), "y1": round(max(ys1) + 0.5, 1)} if xs0 else None


def edge_mode(vals, name):
    c = collections.Counter(round(v) for v in vals)
    if not c:
        return None
    k, n = c.most_common(1)[0]
    near = [v for v in vals if abs(v - k) <= 1.0]
    return {"name": name, "value": round(statistics.median(near), 1), "share": round(len(near) / len(vals), 2)}


edges = [e for e in (edge_mode(xs0, "본문 왼쪽 끝"), edge_mode(xs1, "본문 오른쪽 끝"), edge_mode(ys0, "본문 위 끝"), edge_mode(ys1, "본문 아래 끝")) if e]
pn = next((v for v in var_text if v["role"] == "pageno"), None)
ignore = []
if pn and pn.get("samples"):
    ignore = ["^" + re.sub(r"\\?\d+", r"\\d+", re.escape(pn["samples"][0].strip())) + "$"]
rules = {
    "_note": "style.py가 만든 초안. 값은 모두 원본에서 잰 것이다. 작업/rules.json 으로 복사해서 쓴다. 고치면 이유를 _notes에 적는다.",
    "fonts": [f for f, n in fonts.most_common() if n >= 3],
    "font_evidence": {},
    "sizes": sorted(set(list(sizes) + [s for s, n in osizes.items() if n >= 2])),
    "size_tol": 0.3,
    "colors": {"text": [c for c, _ in tcol.most_common()], "fill": [c for c, _ in fcol.most_common()], "stroke": [c for c, _ in scol.most_common()]},
    "safe": safe,
    "chrome": chrome_rules,
    "guides": [],
    "no_chrome_slides": [],
    "ignore_text": ignore,
    "allowed_text": allowed_text,
    "phrase_check": False,
}
json.dump(rules, open(os.path.join(MD, "rules.draft.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# ---------- 5. 요약 ----------
L = []
A = L.append
A(f"# 양식 요약 (자동으로 만든 것)\n")
A(f"- 장표 크기 {W:g} x {H:g} pt, 모두 {N}쪽")
A(f"- 본문 쪽(틀이 같은 쪽): {body}")
A(f"- 본문이 아닌 쪽(표지, 간지, 맺음 등): {[pg['page'] for pg in pages if pg['page'] not in bodyset]}")
A(f"- 바탕색 {bg}")
cal_path = os.path.join(MD, "calib.json")
if os.path.exists(cal_path):
    cal = json.load(open(cal_path, encoding="utf-8"))
    A("- 글꼴: " + ", ".join(f"{k} = {v['face']}{' 굵게' if v.get('bold') else ''}" if v["ok"] else f"{k} = (이 컴퓨터에 없음)" for k, v in cal["fonts"].items()))
    cs = {k: v["cs"] for k, v in cal["combos"].items() if v["cs"]}
    if cs:
        A(f"- 자간 보정이 들어가는 묶음(textAt이 알아서 넣는다): {cs}")
    A(f"- 글자 위치 보정 확인: {cal.get('verify')}")
if latin_for:
    A("- 영문·숫자 글꼴: " + ", ".join(f"{k} 글 안의 영문과 숫자와 빈칸은 {v}로 찍는다" for k, v in latin_for.items()) + " (저장할 때 도구가 알아서 넣는다. 조각을 나눠 글꼴을 따로 줄 필요가 없다)")
A("\n## 틀 (s.frame()이 그대로 그린다)\n")
A("| 이름 | 종류 | x | y | w | h | 색 | 있는 쪽 수 |")
A("|---|---|---|---|---|---|---|---|")
for it in static_items:
    col = it.get("fill") or it.get("stroke") or it.get("color") or ""
    A(f"| {it['name']} | {it['draw']} | {it['x']} | {it.get('y', it.get('base'))} | {it.get('w', '')} | {it.get('h', '')} | {col} | {len(it['pages'])} |")
A("\n쪽마다 글만 바뀌는 자리\n")
A("| 역할 | 글자 | 맞춤 | x | 기준선 또는 잉크 범위 | 있는 쪽 | 보기 |")
A("|---|---|---|---|---|---|---|")
for v in var_text:
    if v["mode"] == "live":
        A(f"| {v['role']} | {v['font']} {v['size']:g}pt {v['color']}{' (한 줄에 서식이 섞인 쪽 있음)' if v['mixed'] else ''} | {v['align']} | {v['x']} | 기준선 {v['base']} | {len(v['pages'])}쪽 | {' / '.join(v['samples'][:3])} |")
        for q in v.get("variants", [])[1:]:
            A(f"| {v['role']} (다른 꼴) | {q['font']} {q['size']:g}pt {q['color']} | {v['align']} | {q['x']} | 기준선 {q['base']} | {q['pages']}쪽 | {q['sample']} |")
    else:
        A(f"| {v['role']} | 윤곽선 글자, 어림 {v['est_size']:g}pt {v['color']} (글꼴은 peek.py fit으로 찾는다) | {v['align']} | {v['x']} | 잉크 위 {v['ink_top']} 아래 {v['ink_bottom']} | {len(v['pages'])}쪽 | 쪽 그림에서 읽는다 |")
if edges:
    A("\n## 본문 범위\n")
    A(f"- 본문 요소가 놓인 범위(모든 본문 쪽을 합친 것): x {safe['x0']}~{safe['x1']}, y {safe['y0']}~{safe['y1']}")
    for e in edges:
        A(f"- {e['name']}: 가장 흔한 값 {e['value']} (본문 쪽의 {int(e['share'] * 100)}%)")

# 글자 단계
A("\n## 글자 단계 (본문 쪽, 많이 쓰인 순)\n")
A("| 글꼴 | 크기 | 색 | 줄 수 | 쪽 수 | 줄 간격(기준선 사이) | 보기 |")
A("|---|---|---|---|---|---|---|")
st = collections.defaultdict(list)
for n in body:
    for t in P[n]["texts"]:
        if "base" in t:
            st[(t["font"], sk(t["size"]), t["color"])].append((n, t))
rows = []
for k, lst in st.items():
    pitches = []
    byp = collections.defaultdict(list)
    for n, t in lst:
        byp[n].append(t)
    for n, ts in byp.items():
        ts = sorted(ts, key=lambda t: t["base"])
        for a, b in zip(ts, ts[1:]):
            d = b["base"] - a["base"]
            if 0.9 * k[1] < d < 2.6 * k[1] and abs(a["x"] - b["x"]) < 40:
                pitches.append(round(d, 1))
    pc = collections.Counter(pitches).most_common(3)
    smp = sorted({t["t"] for _, t in lst}, key=lambda s: -len(s))[:2]
    rows.append((len(lst), f"| {k[0]} | {k[1]:g} | {k[2]} | {len(lst)} | {len(byp)} | {', '.join(f'{p}({c})' for p, c in pc)} | {' / '.join(s[:28] for s in smp)} |"))
for _, r in sorted(rows, reverse=True)[:40]:
    A(r)
if osizes:
    A("\n윤곽선으로 바뀐 글자의 크기 어림(줄 수): " + ", ".join(f"{k:g}pt({v})" for k, v in sorted(osizes.items()) if v >= 2))

A("\n## 색과 선\n")
def where(colkey, c):
    ps = sorted({pg["page"] for pg in pages for s in pg["shapes"] if s.get(colkey) == c})
    return ps
A("- 채움 색(쓰인 도형 수, 쓰인 쪽): " + "; ".join(f"{c}({n}, {where('fill', c)[:6]})" for c, n in fcol.most_common(24)))
A("- 선 색: " + "; ".join(f"{c}({n})" for c, n in scol.most_common(14)))
sw = collections.Counter(s["sw"] for pg in pages for s in pg["shapes"] if s["stroke"])
A("- 선 굵기 pt: " + ", ".join(f"{k}({v})" for k, v in sorted(sw.items())))
A("- 글자 색: " + "; ".join(f"{c}({n})" for c, n in tcol.most_common(12)))

A("\n## 쪽별 한 줄\n")
tv = next((v for v in var_text if v["role"] == "title"), None)
for pg in pages:
    n = pg["page"]
    title = ""
    if tv and tv["mode"] == "live":
        title = tv.get("by_page", {}).get(n, "")
        if not title:
            c = [t for t in pg["texts"] if "base" in t and abs(t["base"] - tv["base"]) < 0.6 and sk(t["size"]) == tv["size"]]
            if c:
                title = c[0]["t"]
    nums = sum(1 for t in pg["texts"] if re.fullmatch(r"[\s\-+.,%\d()]+", t["t"]))
    hl = sum(1 for s in pg["shapes"] if s["kind"] == "line" and s["w"] > 60)
    bars = sum(1 for s in pg["shapes"] if s["kind"] == "rect" and s["fill"] and s["fill"] != "FFFFFF" and 6 < s["w"] < 60 and s["h"] > 12)
    rnd = sum(1 for s in pg["shapes"] if s["kind"] in ("roundrect", "polygon", "path", "ellipse"))
    guess = []
    if nums >= 30 and hl >= 6:
        guess.append("표")
    if bars >= 4 and nums >= 6:
        guess.append("차트")
    if rnd >= 6:
        guess.append("도식")
    if len(pg["images"]) >= 3:
        guess.append("그림 여러 개")
    if not guess:
        guess.append("글 위주" if len(pg["texts"]) + len(pg["outline_lines"]) > 8 else "간지나 표지")
    A(f"- p{n}{'' if n in bodyset else ' (본문 아님)'}: {title or '(제목은 쪽 그림에서)'} | 글 {len(pg['texts'])}줄, 윤곽선 글 {len(pg['outline_lines'])}줄, 도형 {len(pg['shapes'])}, 그림 {len(pg['images'])} | {'+'.join(guess)}")
A("\n자세한 치수는 dump/pNN.txt 에 있다. 새 장표와 짜임이 가까운 쪽만 골라 읽는다.")
open(os.path.join(MD, "양식요약.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
print("\n".join(L))
print(f"\n틀 {len(static_items)}개, 쪽마다 바뀌는 자리 {len(var_text)}개, 검사 규칙 초안 rules.draft.json, 기준 쪽 p{ref_page}")

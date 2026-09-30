# -*- coding: utf-8 -*-
"""스스로 검사. 파워포인트로 그린 결과(PDF)를 코드로 다시 재서, 회사 양식에서 뽑은 규칙과 자료에 맞는지 확인한다.

쓰는 법:
  python check.py <결과.pdf> <manifest.json> <rules.json> <양식 측정 폴더> <내용.md> [꼬리표]

검사 항목
  규칙의 근거      rules.json의 글꼴·크기·색이 실제로 회사 양식에 있는 값인지 (규칙을 느슨하게 고쳐서 통과하는 것을 막는다)
  양식 밖 글꼴/크기/색   결과에 쓰인 값이 규칙 안에 있는지
  장표 밖, 여백 침범, 세로로 쪼개진 글자, 줄바꿈 넘침, 글 상자 넘침, 글자 겹침, 도형에 덮인 글자
  틀 불일치        제목·쪽 번호·머리 선처럼 모든 쪽에 같은 자리에 있어야 하는 것이 원본과 같은 자리, 같은 모습인지
  출처 없는 숫자, 자료에 없는 문구
  어긋난 정렬      같은 역할의 요소끼리 크기나 간격이 조금씩 다른 경우
  표가 늘어남      글자가 넘쳐 표 줄이 계획보다 커진 경우
  빠진 그림
결과는 report_<꼬리표>.json 에도 적는다. 실패 0건이 될 때까지 고치고 다시 돌린다.
"""
import fitz, json, sys, io, re, os, collections, statistics
from PIL import Image, ImageFilter

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
if len(sys.argv) < 6:
    print(__doc__)
    sys.exit(1)
PDF, MAN, RULES, MDIR, CONTENT = sys.argv[1:6]
TAG = sys.argv[6] if len(sys.argv) > 6 else "check"

def load_json(path):
    s = open(path, encoding="utf-8-sig").read()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        # 정규식의 \d 처럼 역슬래시를 하나만 쓴 경우를 받아 준다
        return json.loads(re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", s))


man = load_json(MAN)
rules = load_json(RULES)
meas = json.load(open(os.path.join(MDIR, "measure.json"), encoding="utf-8"))
content_raw = open(CONTENT, encoding="utf-8").read()
src_pdf = meas.get("source")
ref = fitz.open(src_pdf) if src_pdf and os.path.exists(src_pdf) else None
d = fitz.open(PDF)
W, H = man["W"], man["H"]
fails, info = [], {}


def F(kind, slide, msg, hint=""):
    fails.append({"kind": kind, "slide": slide, "msg": msg, "hint": hint})


def norm(t):
    return re.sub(r"[\s•·⇒➢▪■\-–—]+", "", t)


def loose(t):
    """문구 출처를 견줄 때 쓰는 느슨한 정규화: 띄어쓰기, 글머리표, 문장 부호의 차이는 보지 않는다."""
    return re.sub(r"[\s•·⇒➢▪■\-–—,.;:'\"‘’“”()\[\]/*|ㅣ│]+", "", t)


def hexi(c):
    return f"{c:06X}"


def hexf(c):
    if c is None:
        return None
    return "".join(f"{max(0, min(255, int(round(x * 255)))):02X}" for x in c[:3])


def rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def cnear(a, b, tol=8):
    return all(abs(p - q) <= tol for p, q in zip(rgb(a), rgb(b)))


def fkey(name):
    return re.sub(r"[^a-z0-9가-힣]", "", name.lower())


def flat(im):
    return list(im.get_flattened_data() if hasattr(im, "get_flattened_data") else im.getdata())


# ---------------- 결과 다시 재기 ----------------
pages, rects = [], []
for p in d:
    lines = []
    for b in p.get_text("dict")["blocks"]:
        if b["type"] != 0:
            continue
        for l in b["lines"]:
            t = "".join(s["text"] for s in l["spans"])
            if not t.strip():
                continue
            s0 = max(l["spans"], key=lambda s: len(s["text"].strip()))
            lines.append({"t": t.strip(), "n": norm(t), "x": l["bbox"][0], "y": l["bbox"][1], "x2": l["bbox"][2], "y2": l["bbox"][3],
                          "size": s0["size"], "color": hexi(s0["color"]), "font": s0["font"],
                          "spans": [(s["text"], s["size"], hexi(s["color"]), s["font"]) for s in l["spans"] if s["text"].strip()]})
    pages.append(lines)
    rs = []
    for g in p.get_drawings():
        r = g["rect"]
        fill = None if g.get("fill_opacity") == 0 else hexf(g.get("fill"))
        stroke = None if g.get("stroke_opacity") == 0 else hexf(g.get("color"))
        if fill is None and stroke is None:
            continue
        rs.append({"x": r.x0, "y": r.y0, "w": r.width, "h": r.height, "fill": fill, "stroke": stroke, "sw": g.get("width") or 0})
    rects.append(rs)
NS = len(pages)

# textAt, paraAt 으로 놓은 글은 글 상자가 넉넉하게 잡혀 있다. 검사는 글 상자가 아니라 실제로 그려진 글자의 범위로 한다.
for m in man["texts"]:
    w_ = m.get("want")
    if not w_ or m["slide"] > NS:
        continue
    S_ = norm(m["str"])
    c_ = [l for l in pages[m["slide"] - 1] if l["n"] and l["n"] in S_ and l["x"] >= m["x"] - 3 and l["x2"] <= m["x"] + m["w"] + 3
          and l["y"] >= m["y"] - 6 and l["y2"] <= m["y"] + m["h"] + 6]
    m["ax"], m["ay"] = w_["x"], w_["base"]   # 정렬을 볼 때는 바란 자리(시작점과 기준선)로 견준다
    if c_:
        x0_, y0_ = min(l["x"] for l in c_), min(l["y"] for l in c_)
        x1_, y1_ = max(l["x2"] for l in c_), max(l["y2"] for l in c_)
        m["box"] = [m["x"], m["y"], m["w"], m["h"]]
        m["x"], m["y"], m["w"], m["h"] = x0_, y0_, x1_ - x0_, y1_ - y0_
if NS != len(man["slides"]):
    F("쪽 수 불일치", 0, f"그린 결과 {NS}쪽, 만든 기록 {len(man['slides'])}쪽")

no_chrome = set(rules.get("no_chrome_slides", []))
ignore_pat = [re.compile(p) for p in rules.get("ignore_text", [])]
allowed_text = [norm(t) for t in rules.get("allowed_text", [])]


def ignored(t):
    return any(p.search(t) for p in ignore_pat)


# ---------------- 0) 규칙의 근거 ----------------
m_fonts = set()
m_sizes, m_osizes, m_colors = set(), set(), set()
for pg in meas["pages"]:
    for t in pg["texts"]:
        m_fonts.add(fkey(t["font"]))
        for s_ in t.get("spans", []):
            m_fonts.add(fkey(s_["font"]))
            m_sizes.add(round(s_["size"], 1))
            m_colors.add(s_["color"])
        m_sizes.add(round(t["size"], 1))
        m_colors.add(t["color"])
        for r in t.get("runs", []):
            m_sizes.add(round(r["size"], 1))
            m_colors.add(r["color"])
    for l in pg["outline_lines"]:
        m_osizes.add(l["est_size"])
        for c in l["colors"]:
            if c:
                m_colors.add(c)
    for s in pg["shapes"]:
        for c in (s["fill"], s["stroke"]):
            if c:
                m_colors.add(c)
_pixcache = {}


def color_in_pixels(c):
    """측정값에 없는 색은 원본 쪽 그림에 실제로 나오는 색인지 픽셀로 확인한다."""
    if ref is None:
        return False
    if "sets" not in _pixcache:
        sets = []
        for p in ref:
            pix = p.get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
            im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            sets.append(collections.Counter(flat(im)))
        _pixcache["sets"] = sets
    t = rgb(c)
    for cnt in _pixcache["sets"]:
        n = sum(v for k, v in cnt.items() if all(abs(a - b) <= 4 for a, b in zip(k, t)))
        if n >= 40:
            return True
    return False


for f in rules.get("fonts", []):
    k = fkey(f)
    if m_fonts and not any(mf.startswith(k) or k.startswith(mf) for mf in m_fonts) and f not in rules.get("font_evidence", {}):
        F("규칙의 근거", 0, f"글꼴 {f}: 회사 양식의 살아 있는 글자에 없는 글꼴", "윤곽선 글자에서 알아낸 글꼴이면 rules.json의 font_evidence에 peek.py fit 결과를 적는다")
for s in rules.get("sizes", []):
    ok = any(abs(s - v) <= 0.6 for v in m_sizes) or any(abs(s - v) <= 1.0 for v in m_osizes)
    if not ok:
        F("규칙의 근거", 0, f"글자 크기 {s}pt: 회사 양식에서 잰 크기와 맞는 것이 없음")
for grp in ("text", "fill", "stroke"):
    for c in rules.get("colors", {}).get(grp, []):
        if not (any(cnear(c, m, 6) for m in m_colors) or color_in_pixels(c)):
            F("규칙의 근거", 0, f"{grp} 색 {c}: 회사 양식에 없는 색")

# ---------------- 1) 양식 밖 글꼴, 크기, 색 ----------------
rf = [fkey(f) for f in rules.get("fonts", [])]
rs_ = rules.get("sizes", [])
stol = rules.get("size_tol", 0.3)
rc = rules.get("colors", {})
seen = set()
for pi, lines in enumerate(pages):
    for l in lines:
        for (t, size, color, font) in l["spans"]:
            fk = fkey(font)
            if rf and not any(fk.startswith(k) for k in rf):
                key = ("f", pi, font)
                if key not in seen:
                    seen.add(key)
                    F("양식 밖 글꼴", pi + 1, f"{font} '{t.strip()[:20]}'")
            if rs_ and not any(abs(size - v) <= stol for v in rs_):
                key = ("s", pi, round(size, 1))
                if key not in seen:
                    seen.add(key)
                    F("양식 밖 글자 크기", pi + 1, f"{size:.1f}pt '{t.strip()[:20]}'", f"규칙의 크기: {rs_}")
            if rc.get("text") and not any(cnear(color, v) for v in rc["text"]):
                key = ("c", pi, color)
                if key not in seen:
                    seen.add(key)
                    F("양식 밖 글자 색", pi + 1, f"{color} '{t.strip()[:20]}'")
for pi, rs in enumerate(rects):
    for r in rs:
        if r["w"] * r["h"] < 4 and max(r["w"], r["h"]) < 20:
            continue
        if r["fill"] and rc.get("fill") and not any(cnear(r["fill"], v) for v in rc["fill"]):
            key = ("fc", pi, r["fill"])
            if key not in seen:
                seen.add(key)
                F("양식 밖 채움 색", pi + 1, f"{r['fill']} (x={r['x']:.0f} y={r['y']:.0f} w={r['w']:.0f} h={r['h']:.0f})")
        if r["stroke"] and rc.get("stroke") and not any(cnear(r["stroke"], v) for v in rc["stroke"]):
            key = ("sc", pi, r["stroke"])
            if key not in seen:
                seen.add(key)
                F("양식 밖 선 색", pi + 1, f"{r['stroke']} (x={r['x']:.0f} y={r['y']:.0f} w={r['w']:.0f} h={r['h']:.0f})")

# ---------------- 2) 장표 밖, 여백 침범, 쪼개진 글자 ----------------
for pi, lines in enumerate(pages):
    for l in lines:
        if l["x"] < -0.5 or l["x2"] > W + 0.5 or l["y"] < -0.5 or l["y2"] > H + 0.5:
            F("장표 밖", pi + 1, l["t"][:30])
    singles = [l for l in lines if len(l["n"]) == 1 and not l["n"].isdigit()]
    for x, c in collections.Counter(round(l["x"] / 8) for l in singles).items():
        if c >= 3:
            F("세로로 쪼개진 글자", pi + 1, f"x={x * 8}pt 근처에 한 글자짜리 줄 {c}개", "칸이나 글 상자가 너무 좁다")
safe = rules.get("safe")
if safe:
    for grp in ("texts", "shapes", "images", "tables", "charts"):
        for m in man[grp]:
            if m.get("chrome") or m.get("bleed"):
                continue
            ex = []
            if m["x"] < safe["x0"] - 0.5:
                ex.append(f"왼쪽 {safe['x0'] - m['x']:.1f}pt")
            if m["x"] + m["w"] > safe["x1"] + 0.5:
                ex.append(f"오른쪽 {m['x'] + m['w'] - safe['x1']:.1f}pt")
            if m["y"] < safe["y0"] - 0.5:
                ex.append(f"위 {safe['y0'] - m['y']:.1f}pt")
            if m["y"] + m["h"] > safe["y1"] + 0.5:
                ex.append(f"아래 {m['y'] + m['h'] - safe['y1']:.1f}pt")
            if ex:
                F("여백 침범", m["slide"], f"{grp[:-1]} '{(m.get('str') or m.get('role') or m.get('file') or '')[:24]}' " + ", ".join(ex),
                  "양식에서 장표 끝까지 닿는 요소라면 bleed: true 로 표시한다")

# ---------------- 3) 줄바꿈 넘침, 글 상자 넘침 ----------------
for m in man["texts"]:
    if m["slide"] > NS:
        continue
    lines = pages[m["slide"] - 1]
    S = norm(m["str"])
    if len(S) < 2:
        continue
    cand = [l for l in lines if l["n"] and l["n"] in S and m["x"] - 3 <= l["x"] and l["x2"] <= m["x"] + m["w"] + 3 + (W if m["align"] != "left" else 0)
            and m["y"] - 14 <= l["y"] and l["y2"] <= m["y"] + m["h"] + 60]
    cand = [l for l in cand if l["x2"] >= m["x"] - 3 and l["x"] <= m["x"] + m["w"] + 3]
    if not cand:
        continue
    if not m["multi"]:
        if any(l["n"] == S for l in cand):
            continue
        ys = sorted({round(l["y"]) for l in cand if len(l["n"]) >= 2})
        rows = []
        for y in ys:
            if not rows or y - rows[-1] > 4:
                rows.append(y)
        if len(rows) >= 2 and "\n" not in m["str"]:
            F("줄바꿈 넘침", m["slide"], f"'{m['str'][:30]}' 한 줄이어야 하는데 {len(rows)}줄로 나옴", "글 상자를 넓히거나 글자 크기·글을 양식 안에서 조정")
    else:
        bot = max(l["y2"] for l in cand)
        top = min(l["y"] for l in cand)
        lh = statistics.median(l["y2"] - l["y"] for l in cand)
        slack = 0.22 * lh  # 줄 상자에는 글자 위아래 빈 곳이 들어 있다
        if bot - slack > m["y"] + m["h"] + 1.0:
            F("글 상자 넘침", m["slide"], f"'{m['str'][:24]}' 아래로 {bot - slack - m['y'] - m['h']:.1f}pt 넘침")
        if top + slack < m["y"] - 1.0:
            F("글 상자 넘침", m["slide"], f"'{m['str'][:24]}' 위로 {m['y'] - top - slack:.1f}pt 넘침")

# ---------------- 4) 글자 겹침 ----------------
for pi, lines in enumerate(pages):
    L = [l for l in lines if len(l["n"]) >= 2]
    for i in range(len(L)):
        for j in range(i + 1, len(L)):
            a, b = L[i], L[j]
            ix = min(a["x2"], b["x2"]) - max(a["x"], b["x"])
            iy = min(a["y2"], b["y2"]) - max(a["y"], b["y"])
            hmin = min(a["y2"] - a["y"], b["y2"] - b["y"])
            if ix > 2 and iy > 0.4 * hmin:
                F("글자 겹침", pi + 1, f"'{a['t'][:18]}' <-> '{b['t'][:18]}'")

# ---------------- 5) 도형에 덮인 글자 ----------------
for m in man["texts"]:
    for sh in man["shapes"] + man["images"]:
        if sh["slide"] != m["slide"] or sh["order"] <= m["order"]:
            continue
        if sh.get("kind") in ("line", "bar", "cellfill") or (sh.get("kind") and not sh.get("fill")):
            continue
        ix = min(m["x"] + m["w"], sh["x"] + sh["w"]) - max(m["x"], sh["x"])
        iy = min(m["y"] + m["h"], sh["y"] + sh["h"]) - max(m["y"], sh["y"])
        if ix > 0 and iy > 0 and ix * iy / max(1e-6, m["w"] * m["h"]) > 0.3:
            F("도형에 덮인 글자", m["slide"], f"'{m['str'][:30]}' 위에 나중에 그린 {sh.get('kind', '그림')}({sh.get('role', '')})", "면을 먼저 그리고 글자를 나중에 그린다")
            break


# ---------------- 6) 틀 일치 ----------------
def region_img(doc, idx, reg, sc=3):
    p = doc[idx]
    rr = fitz.Rect(*reg) & p.rect
    pix = p.get_pixmap(matrix=fitz.Matrix(sc, sc), clip=rr, alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


_bgcache = {}


def page_bg(doc, idx):
    """쪽의 바탕색: 쪽 전체에서 가장 많이 나오는 색."""
    key = (id(doc), idx)
    if key not in _bgcache:
        pix = doc[idx].get_pixmap(matrix=fitz.Matrix(0.5, 0.5), alpha=False)
        im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        _bgcache[key] = collections.Counter(flat(im)).most_common(1)[0][0]
    return _bgcache[key]


def mismatch(a, b, bg):
    """두 그림의 잉크가 얼마나 어긋났는지. 0이면 같고 1이면 전혀 다르다."""
    w, h = min(a.width, b.width), min(a.height, b.height)
    a = a.crop((0, 0, w, h)).filter(ImageFilter.GaussianBlur(1.2))
    b = b.crop((0, 0, w, h)).filter(ImageFilter.GaussianBlur(1.2))
    da, db = flat(a), flat(b)
    num = den = 0
    for p, q in zip(da, db):
        num += sum(abs(x - y) for x, y in zip(p, q))
        den += sum(abs(x - y) for x, y in zip(p, bg)) + sum(abs(x - y) for x, y in zip(q, bg))
    return num / den if den > 2000 else (0.0 if num < 2000 else 1.0)


def blob(im, reg, sc, bg):
    """영역 안에서 바탕이 아닌 부분의 범위(pt)와 평균색."""
    data = flat(im)
    x0 = y0 = 10 ** 9
    x1 = y1 = -1
    acc = [0, 0, 0]
    n = 0
    for i_, px in enumerate(data):
        if sum(abs(a - b) for a, b in zip(px, bg)) > 90:
            i, j = i_ % im.width, i_ // im.width
            x0 = min(x0, i); x1 = max(x1, i); y0 = min(y0, j); y1 = max(y1, j)
            acc[0] += px[0]; acc[1] += px[1]; acc[2] += px[2]
            n += 1
    if n == 0:
        return None
    return {"left": reg[0] + x0 / sc, "top": reg[1] + y0 / sc, "right": reg[0] + (x1 + 1) / sc, "bottom": reg[1] + (y1 + 1) / sc,
            "color": [round(v / n) for v in acc]}


def ink(doc, idx, reg, color, sc=8):
    im = region_img(doc, idx, reg, sc)
    data = flat(im)
    bg = collections.Counter(data).most_common(1)[0][0]
    tc = rgb(color)
    v = [a - b for a, b in zip(tc, bg)]
    vv = sum(c * c for c in v) or 1
    x0 = y0 = 10 ** 9
    x1 = y1 = -1
    for i_, px in enumerate(data):
        if px == bg:
            continue
        u = [a - b for a, b in zip(px, bg)]
        t = sum(a * b for a, b in zip(u, v)) / vv
        if t <= 0.5:
            continue
        res = sum((a - t * b) ** 2 for a, b in zip(u, v)) ** 0.5
        if res < 40:
            i, j = i_ % im.width, i_ // im.width
            x0 = min(x0, i); x1 = max(x1, i); y0 = min(y0, j); y1 = max(y1, j)
    if x1 < 0:
        return None
    return {"left": reg[0] + x0 / sc, "top": reg[1] + y0 / sc, "right": reg[0] + (x1 + 1) / sc, "bottom": reg[1] + (y1 + 1) / sc,
            "cx": reg[0] + (x0 + x1 + 1) / 2 / sc}


chrome_ok = chrome_total = 0
for si in range(NS):
    if (si + 1) in no_chrome:
        continue
    for c in rules.get("chrome", []):
        chrome_total += 1
        tol = c.get("tol", 0.6)
        if c["kind"] == "pixels":
            if ref is None:
                continue
            A, B = region_img(ref, c["ref_page"] - 1, c["region"], 4), region_img(d, si, c["region"], 4)
            bga = rgb(c["bg"]) if c.get("bg") else page_bg(ref, c["ref_page"] - 1)
            bgb = rgb(c["bg"]) if c.get("bg") else page_bg(d, si)
            mm = mismatch(A, B, bga)
            bad = []
            ba, bb = blob(A, c["region"], 4, bga), blob(B, c["region"], 4, bgb)
            if ba and not bb:
                bad.append("그 자리에 아무것도 없음")
            elif ba and bb:
                ptol = c.get("tol", 0.4)
                for k, nm in (("left", "왼쪽 끝"), ("top", "위 끝"), ("right", "오른쪽 끝"), ("bottom", "아래 끝")):
                    if abs(ba[k] - bb[k]) > ptol:
                        bad.append(f"{nm} {bb[k]:.2f} (원본 {ba[k]:.2f}, {ba[k] - bb[k]:+.2f}pt)")
                if max(abs(p - q) for p, q in zip(ba["color"], bb["color"])) > c.get("color_tol", 14):
                    bad.append("색이 다름: 결과 %02X%02X%02X, 원본 %02X%02X%02X (잉크 부분의 평균색)" % (tuple(bb["color"]) + tuple(ba["color"])))
            if mm > c.get("max", 0.22):
                bad.append(f"모습이 다름 (어긋남 {mm:.2f}, 허용 {c.get('max', 0.22)})")
            if bad:
                F("틀 불일치", si + 1, f"{c['name']}: 원본 {c['ref_page']}쪽의 같은 자리와 다름. " + "; ".join(bad),
                  f"peek.py crop으로 원본과 결과의 {c['region']} 영역을 크게 잘라 나란히 본다")
            else:
                chrome_ok += 1
        elif c["kind"] == "shape":
            # 되풀이되는 도형: 그린 결과에 같은 자리, 같은 크기, 같은 색의 도형이 있는지 본다
            hit = None
            for r in rects[si]:
                if abs(r["x"] - c["x"]) <= tol and abs(r["y"] - c["y"]) <= tol and abs(r["w"] - c["w"]) <= tol and abs(r["h"] - c["h"]) <= tol:
                    hit = r
                    col = r["fill"] if c.get("fill") else r["stroke"]
                    want = c.get("fill") or c.get("stroke")
                    if col and want and cnear(col, want, 6) and (not c.get("sw") or c.get("fill") or abs(r["sw"] - c["sw"]) <= 0.1):
                        hit = "ok"
                        break
            if hit == "ok":
                chrome_ok += 1
            elif hit:
                F("틀 불일치", si + 1, f"{c['name']}: 자리는 맞는데 색이나 선 굵기가 다름 (기준 {c.get('fill') or c.get('stroke')} {c.get('sw', '')}pt)")
            else:
                F("틀 불일치", si + 1, f"{c['name']}: x={c['x']} y={c['y']} w={c['w']} h={c['h']} 자리에 같은 도형이 없음", "s.frame()을 불렀는지 본다")
        elif c["kind"] == "base":
            # 그린 결과에서 그 자리의 글자를 찾아 기준선, 시작점, 크기, 글꼴을 견준다 (글자 모양에 흔들리지 않는다)
            R = c["region"]
            sp = []
            for b_ in d[si].get_text("dict")["blocks"]:
                if b_["type"] != 0:
                    continue
                for l_ in b_["lines"]:
                    ss = [s_ for s_ in l_["spans"] if s_["text"].strip()]
                    if not ss:
                        continue
                    x0_, y0_, x1_, y1_ = l_["bbox"]
                    if x0_ >= R[0] - 1 and y0_ >= R[1] - 1 and x1_ <= R[2] + 1 and y1_ <= R[3] + 1:
                        s0_ = max(ss, key=lambda s_: len(s_["text"].strip()))
                        sp.append({"ox": ss[0]["origin"][0], "base": ss[0]["origin"][1], "right": x1_, "cx": (x0_ + x1_) / 2, "size": s0_["size"], "font": s0_["font"], "t": "".join(s_["text"] for s_ in ss)})
            if not sp:
                F("틀 불일치", si + 1, f"{c['name']}: 그 자리({R})에 글자가 없음", "s.frame()에 제목과 쪽 번호를 넘겼는지 본다")
                continue
            alts = c.get("alts") or [{"base": c["base"], "size": c["size"], "font": c["font"]}]
            if "ox" in c:   # 같은 줄에 다른 글(오른쪽 작은 제목 등)이 있을 수 있다. 시작점이 가까운 것을 제목으로 본다
                xs_ = [a_.get("ox", c["ox"]) for a_ in alts]
                near_ = [q for q in sp if min(abs(q["ox"] - x_) for x_ in xs_) <= 12]
                sp = near_ or sp
            g = min(sp, key=lambda q: abs(q["base"] - c["base"]))
            bad = None
            for a_ in alts:
                b2 = []
                if abs(g["base"] - a_["base"]) > tol:
                    b2.append(f"기준선 {g['base']:.2f} (기준 {a_['base']:.2f})")
                if abs(g["size"] - a_["size"]) > 0.3:
                    b2.append(f"크기 {g['size']:.1f} (기준 {a_['size']})")
                if fkey(g["font"].split("+")[-1])[:6] != fkey(a_["font"].split("+")[-1])[:6]:
                    b2.append(f"글꼴 {g['font']} (기준 {a_['font']})")
                for k in ("ox", "right", "cx"):
                    want_ = a_.get(k, c.get(k)) if k == "ox" else c.get(k)
                    if want_ is not None and abs(g[k] - want_) > max(tol, 0.5 if k != "ox" else tol):
                        b2.append(f"{k} {g[k]:.2f} (기준 {want_:.2f})")
                if bad is None or len(b2) < len(bad):
                    bad = b2
            if bad:
                F("틀 불일치", si + 1, f"{c['name']} '{g['t'][:20]}': " + "; ".join(bad), "s.frame() 또는 s.textAt()으로 원본에서 잰 기준선 자리에 놓는다")
            else:
                chrome_ok += 1
        elif c["kind"] == "ink":
            got = ink(d, si, c["region"], c["color"])
            if not got:
                F("틀 불일치", si + 1, f"{c['name']}: 그 자리에 {c['color']} 색 글자가 없음")
                continue
            bad = []
            for k in ("left", "top", "right", "bottom", "cx"):
                if k in c and abs(got[k] - c[k]) > tol:
                    delta = c[k] - got[k]
                    axis = "x" if k in ("left", "right", "cx") else "y"
                    bad.append(f"{k} {got[k]:.1f} (기준 {c[k]:.1f}, {axis}를 {delta:+.1f}pt)")
            if "top" in c and "bottom" in c:
                hh, hr = got["bottom"] - got["top"], c["bottom"] - c["top"]
                if abs(hh - hr) > max(0.8, 0.06 * hr):
                    bad.append(f"잉크 높이 {hh:.1f} (기준 {hr:.1f}, 글자 크기를 {hr / hh:.3f}배)")
            if bad:
                F("틀 불일치", si + 1, f"{c['name']}: " + "; ".join(bad))
            else:
                chrome_ok += 1
info["틀 일치"] = f"{chrome_ok}/{chrome_total}"

# ---------------- 7) 숫자 출처, 문구 출처 ----------------
NUM = re.compile(r"\d[\d,]*\.?\d*")
cnums = set()
for tok in NUM.findall(content_raw):
    k = tok.rstrip(".")
    cnums.add(k)
    cnums.add(k.replace(",", ""))
cnorm = loose(content_raw)
allowed_loose = [loose(t) for t in rules.get("allowed_text", [])]
calc_texts = [norm(m["str"]) for m in man["texts"] if m.get("source")]
calc_list = [(m["slide"], m["str"], m["source"]) for m in man["texts"] if m.get("source")]
for pi, lines in enumerate(pages):
    for l in lines:
        if ignored(l["t"]):
            continue
        is_calc = any(l["n"] and (l["n"] in c or c in l["n"]) for c in calc_texts)
        if not is_calc:
            for tok in NUM.findall(l["t"]):
                k = tok.rstrip(".")
                if k in cnums or k.replace(",", "") in cnums:
                    continue
                F("출처 없는 숫자", pi + 1, f"{tok} ('{l['t'][:30]}')", "자료에 있는 숫자만 쓴다. 계산한 값이면 text()에 source: '계산식'을 적는다")
        n = loose(l["t"])
        if len(n) >= 3 and re.search(r"[가-힣A-Za-z]", n) and not is_calc:
            if n in cnorm or any(n in a or a in n for a in allowed_loose if a):
                continue
            # 한 줄에 여러 글 상자가 이어 붙은 경우: 앞에서부터 자료에 있는 조각으로 덮이는지
            rest, okc = n, True
            while rest:
                k = 0
                for L in range(len(rest), 1, -1):
                    if rest[:L] in cnorm or any(rest[:L] == a for a in allowed_loose):
                        k = L
                        break
                if k == 0:
                    okc = False
                    break
                rest = rest[k:]
            if not okc and rules.get("phrase_check", True):
                F("자료에 없는 문구", pi + 1, f"'{l['t'][:40]}'", "자료의 문구를 그대로 쓴다. 양식에 늘 있는 표기라면 rules.json의 allowed_text에 넣고 이유를 남긴다")
info["계산으로 만든 숫자"] = [f"{s}쪽 '{t[:20]}' = {src}" for s, t, src in calc_list][:40]

# ---------------- 8) 어긋난 정렬 ----------------
def near_miss(vals, lo=0.25, hi=3.0):
    vals = sorted(vals)
    out = []
    for a, b in zip(vals, vals[1:]):
        if lo < b - a <= hi:
            out.append((a, b))
    return out


for si in range(1, NS + 1):
    groups = collections.defaultdict(list)
    for grp in ("shapes", "texts", "images"):
        for m in man[grp]:
            if m["slide"] == si and m.get("role") and not m.get("chrome") and m.get("kind") not in ("bar", "line", "cellfill", "marker"):
                groups[(grp, m["role"])].append(m)
    for (grp, role), ms in groups.items():
        if len(ms) < 2:
            continue
        if grp != "texts":
            for dim, name in (("w", "너비"), ("h", "높이")):
                nm = near_miss([round(m[dim], 2) for m in ms])
                if nm:
                    F("어긋난 정렬", si, f"역할 '{role}' {name}가 조금씩 다름: {nm[:3]}", "같은 역할이면 크기를 똑같이 맞춘다")
        for dim, name in (("x", "왼쪽"), ("y", "위쪽")):
            nm = near_miss(sorted({round(m.get("a" + dim, m[dim]), 2) for m in ms}))
            if nm:
                F("어긋난 정렬", si, f"역할 '{role}' {name} 위치가 조금씩 어긋남: {nm[:3]}", "같은 줄이나 같은 열이면 좌표를 똑같이 맞춘다")
        if grp != "texts":
            rows = collections.defaultdict(list)
            for m in ms:
                rows[round(m["y"])].append(m)
            for y, row in rows.items():
                row.sort(key=lambda m: m["x"])
                gaps = [round(b["x"] - (a["x"] + a["w"]), 2) for a, b in zip(row, row[1:])]
                if len(gaps) >= 2 and max(gaps) - min(gaps) > 0.25 and max(gaps) - min(gaps) <= 4:
                    F("어긋난 정렬", si, f"역할 '{role}' 가로 간격이 고르지 않음: {gaps}")
            colsd = collections.defaultdict(list)
            for m in ms:
                colsd[round(m["x"])].append(m)
            for x, col in colsd.items():
                col.sort(key=lambda m: m["y"])
                gaps = [round(b["y"] - (a["y"] + a["h"]), 2) for a, b in zip(col, col[1:])]
                if len(gaps) >= 2 and max(gaps) - min(gaps) > 0.25 and max(gaps) - min(gaps) <= 4:
                    F("어긋난 정렬", si, f"역할 '{role}' 세로 간격이 고르지 않음: {gaps}")

# ---------------- 8-2) 기준선: 원본 본문 쪽들이 함께 지키는 끝선 ----------------
# rules.json 의 guides 예: {"name": "본문 아래 끝", "edge": "bottom", "value": 496.8, "tol": 1.0, "skip_roles": ["note"]}
for g in rules.get("guides", []):
    skip = set(g.get("skip_roles", []))
    for si in range(1, NS + 1):
        if si in set(g.get("skip_slides", [])):
            continue
        body = [m for grp in ("shapes", "images", "tables", "charts", "texts") for m in man[grp]
                if m["slide"] == si and not m.get("chrome") and m.get("role") not in skip and not (g.get("shapes_only") and grp == "texts")]
        if not body:
            continue
        e = g["edge"]
        got = {"left": min(m["x"] for m in body), "right": max(m["x"] + m["w"] for m in body),
               "top": min(m["y"] for m in body), "bottom": max(m["y"] + m["h"] for m in body)}[e]
        if abs(got - g["value"]) > g.get("tol", 1.0):
            F("기준선 어긋남", si, f"{g['name']}: 본문의 {e} 끝이 {got:.1f} (원본 쪽들은 {g['value']:.1f})",
              "원본 본문 쪽들이 함께 지키는 끝선에 맞춘다. 이 쪽의 성격상 맞지 않으면 skip_slides에 넣고 이유를 보고에 적는다")

# ---------------- 8-3) 빈 상자: 상자는 큰데 내용이 위쪽에만 몰려 아래가 비는 경우 ----------------
allow_empty = set(rules.get("allow_empty_roles", []))
for si in range(1, NS + 1):
    items = [m for grp in ("texts", "images", "tables", "charts", "shapes") for m in man[grp] if m["slide"] == si and not m.get("chrome")]
    for c in man["shapes"]:
        if c["slide"] != si or c.get("chrome") or c.get("bleed") or c["kind"] not in ("rect", "roundrect") or c["w"] < 120 or c["h"] < 80:
            continue
        if c.get("role") in allow_empty:
            continue
        inside = [m for m in items if m is not c and m["order"] > c["order"] and m["x"] >= c["x"] - 1 and m["y"] >= c["y"] - 1
                  and m["x"] + m["w"] <= c["x"] + c["w"] + 1 and m["y"] + m["h"] <= c["y"] + c["h"] + 1 and m["w"] * m["h"] < 0.9 * c["w"] * c["h"]]
        if len(inside) < 2:
            continue
        bottom = max(m["y"] + m["h"] - (0.2 * m.get("size", 0) if "str" in m else 0) for m in inside)
        empty = (c["y"] + c["h"] - bottom) / c["h"]
        if empty > 0.33:
            F("빈 상자", si, f"역할 '{c.get('role', '')}' 상자(x={c['x']:.0f} y={c['y']:.0f} w={c['w']:.0f} h={c['h']:.0f})의 아래 {empty * 100:.0f}%가 비어 있음",
              "상자 크기를 내용에 맞추거나 배치를 바꾼다. 원본도 같은 부품을 이렇게 비워 쓰면 rules.json의 allow_empty_roles에 넣고 이유를 보고에 적는다")

# ---------------- 9) 표가 늘어남 ----------------
for t in man["tables"]:
    if t["slide"] > NS:
        continue
    hl = [r for r in rects[t["slide"] - 1] if r["h"] < 2.5 and r["w"] > 8 and r["x"] >= t["x"] - 2 and r["x"] + r["w"] <= t["x"] + t["w"] + 2
          and r["y"] >= t["y"] - 2]
    if not hl:
        continue
    bottom = max(r["y"] + r["h"] / 2 for r in hl if r["y"] <= t["y"] + t["h"] + 80)
    if bottom - (t["y"] + t["h"]) > 1.5:
        F("표가 늘어남", t["slide"], f"계획한 아래 끝 {t['y'] + t['h']:.1f}pt, 실제 {bottom:.1f}pt", "글자가 칸에 안 들어가 줄이 커졌다. 칸 여백·너비를 조정")

# ---------------- 10) 그림 ----------------
for f in man.get("missing", []):
    F("빠진 그림", 0, f)
rep_dirs = {os.path.dirname(m["file"]) for m in man["images"]}
for rd in rep_dirs:
    rp = os.path.join(rd, "_report.json")
    if os.path.exists(rp):
        rep = json.load(open(rp, encoding="utf-8"))
        used = {os.path.basename(m["file"]) for m in man["images"]}
        for name, v in rep.items():
            if name in used and not v.get("ok", True):
                F("불량 그림", 0, name + " " + json.dumps(v, ensure_ascii=False))

# ---------------- 참고: 채움 정도 ----------------
for si in range(1, NS + 1):
    body = [m for grp in ("texts", "shapes", "images", "tables", "charts") for m in man[grp] if m["slide"] == si and not m.get("chrome")]
    if body:
        info[f"{si}쪽 본문 범위"] = f"x {min(m['x'] for m in body):.0f}~{max(m['x'] + m['w'] for m in body):.0f}, y {min(m['y'] for m in body):.0f}~{max(m['y'] + m['h'] for m in body):.0f}"

json.dump({"fails": fails, "info": info}, open(f"report_{TAG}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
cnt = collections.Counter(f["kind"] for f in fails)
print(f"[{TAG}] 실패 {len(fails)}건", dict(cnt))
for k, v in info.items():
    print("  참고", k, ":", v)
for f in fails[:80]:
    print(f"  - {f['slide']}쪽 [{f['kind']}] {f['msg']}" + (f"  → {f['hint']}" if f["hint"] else ""))
if len(fails) > 80:
    print(f"  ... 그 밖에 {len(fails) - 80}건 (report_{TAG}.json)")

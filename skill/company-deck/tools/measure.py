# -*- coding: utf-8 -*-
"""발표 자료 PDF를 코드로 잰다.

쓰는 법:  python measure.py <회사양식.pdf> <결과폴더>

만드는 것
  measure.json      쪽마다 글자 줄, 윤곽선으로 바뀐 글자 줄, 도형, 그림 (단위 pt, 왼쪽 위가 0,0)
  dump/pNN.txt      사람이 읽기 쉬운 쪽별 목록 (위에서 아래 순서)
  pages/pNN.png     쪽 그림 (가로 1920)
  images/           PDF 안에 들어 있던 그림 파일
  overview.jpg      전체 쪽 한눈에 보기
  summary.txt       글꼴, 글자 크기, 색, 선 굵기 통계와 여러 쪽에 되풀이되는 요소(틀 후보)
"""
import fitz, json, sys, io, os, collections, statistics, re
from PIL import Image, ImageDraw

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
if len(sys.argv) < 3:
    print(__doc__)
    sys.exit(1)
SRC, OUT = sys.argv[1], sys.argv[2]
for d in ("", "dump", "pages", "images"):
    os.makedirs(os.path.join(OUT, d), exist_ok=True)

doc = fitz.open(SRC)
W, H = doc[0].rect.width, doc[0].rect.height
HANGUL = re.compile(r"[가-힣]")


def hexc(c):
    if c is None:
        return None
    if isinstance(c, int):
        return f"{c:06X}"
    return "".join(f"{max(0, min(255, int(round(x * 255)))):02X}" for x in c[:3])


def r1(v):  # 소수 둘째 자리까지 (0.1pt 단위로 줄이면 틀이 어긋난다)
    return round(float(v), 2)


def near(c1, c2, tol):
    return all(abs(a - b) <= tol for a, b in zip(c1, c2))


def rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


SC = 2.0  # 쪽을 그려 놓고 픽셀로 확인할 때 쓰는 배율


def page_pix(p):
    pix = p.get_pixmap(matrix=fitz.Matrix(SC, SC), alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def cover_ratio(img, x, y, w, h, color):
    """도형 상자 안에서 그 도형 색으로 보이는 픽셀의 비율. 글자 윤곽선은 낮고 면 도형은 높다."""
    x0, y0 = max(0, int(x * SC)), max(0, int(y * SC))
    x1, y1 = min(img.width, int((x + w) * SC) + 1), min(img.height, int((y + h) * SC) + 1)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    crop = img.crop((x0, y0, x1, y1))
    px = list(crop.get_flattened_data() if hasattr(crop, "get_flattened_data") else crop.getdata())
    c = rgb(color)
    hit = sum(1 for p in px if near(p, c, 48))
    return hit / max(1, len(px))


def ink_box(img, x, y, w, h, color=None):
    """상자 안에서 글자 잉크가 차지하는 범위 (pt). color를 주면 그 색에 가까운 픽셀만 잉크로 본다."""
    x0, y0 = max(0, int(x * SC)), max(0, int(y * SC))
    x1, y1 = min(img.width, int((x + w) * SC) + 1), min(img.height, int((y + h) * SC) + 1)
    if x1 <= x0 or y1 <= y0:
        return None
    crop = img.crop((x0, y0, x1, y1))
    px = crop.load()
    cnt = collections.Counter(crop.get_flattened_data() if hasattr(crop, "get_flattened_data") else crop.getdata())
    bg = cnt.most_common(1)[0][0]
    tc = rgb(color) if color else None
    xs, ys = [], []
    for j in range(crop.height):
        for i in range(crop.width):
            p = px[i, j]
            if near(p, bg, 60):
                continue
            if tc is not None:
                dt = sum(abs(a - b) for a, b in zip(p, tc))
                db = sum(abs(a - b) for a, b in zip(p, bg))
                if dt > db:
                    continue
            xs.append(i)
            ys.append(j)
    if not xs:
        return None
    return (x0 + min(xs)) / SC, (y0 + min(ys)) / SC, (max(xs) - min(xs) + 1) / SC, (max(ys) - min(ys) + 1) / SC


def ink_box_hi(p, x, y, w, h, color, scale=8):
    """글자 줄 하나를 크게 그려서 잉크 범위를 잰다 (pt). 반 넘게 글자 색인 픽셀만 잉크로 센다."""
    rr = fitz.Rect(x, y, x + w, y + h) & p.rect
    if rr.is_empty:
        return None
    pix = p.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=rr, alpha=False)
    im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    data = list(im.get_flattened_data() if hasattr(im, "get_flattened_data") else im.getdata())
    bg = collections.Counter(data).most_common(1)[0][0]
    tc = rgb(color)
    v = [a - b for a, b in zip(tc, bg)]
    vv = sum(c * c for c in v)
    if vv < 60 * 60:
        return None
    Wp = im.width
    xs0 = ys0 = 10 ** 9
    xs1 = ys1 = -1
    for idx, px in enumerate(data):
        if px == bg:
            continue
        u = [a - b for a, b in zip(px, bg)]
        t = sum(a * b for a, b in zip(u, v)) / vv
        if t <= 0.5:
            continue
        res = sum((a - t * b) ** 2 for a, b in zip(u, v)) ** 0.5
        if res < 40:
            i, j = idx % Wp, idx // Wp
            if i < xs0: xs0 = i
            if i > xs1: xs1 = i
            if j < ys0: ys0 = j
            if j > ys1: ys1 = j
    if xs1 < 0:
        return None
    return rr.x0 + xs0 / scale, rr.y0 + ys0 / scale, (xs1 - xs0 + 1) / scale, (ys1 - ys0 + 1) / scale


def classify(g, img):
    items = g["items"]
    kinds = collections.Counter(it[0] for it in items)
    r = g["rect"]
    n = len(items)
    fill, stroke = g.get("fill"), g.get("color")
    if n == 1 and (kinds.get("re") or kinds.get("qu")):
        return "rect" if (r.width >= 1.5 and r.height >= 1.5) else "line"
    if (r.width < 1.5 or r.height < 1.5) and n <= 6:
        return "line"
    if fill is None and stroke is not None:
        return "stroke-path"
    if fill is None:
        return "path"
    cov = cover_ratio(img, r.x0, r.y0, r.width, r.height, hexc(fill))
    only_c = set(kinds) <= {"c"}
    only_l = set(kinds) <= {"l"}
    small = max(r.width, r.height) <= 6
    if only_c and n <= 8 and abs(r.width - r.height) <= 0.2 * max(r.width, r.height):
        return "dot" if small else ("ellipse" if cov > 0.55 else "glyph")
    if r.height <= 90 and cov < 0.62 and n >= 3:
        return "glyph"
    if small:
        return "glyph"
    if only_l:
        return "polygon"
    if set(kinds) <= {"l", "c", "re"} and kinds.get("c", 0) <= 8:
        return "roundrect"
    return "path"


def group_lines(glyphs):
    lines = []
    for g in sorted(glyphs, key=lambda g: (g["x"], g["y"])):
        cy = g["y"] + g["h"] / 2
        best = None
        for ln in lines:
            ly0, ly1 = ln["y"], ln["y"] + ln["h"]
            ov = min(ly1, g["y"] + g["h"]) - max(ly0, g["y"])
            inside = ly0 - 1 <= cy <= ly1 + 1
            if ov > 0.45 * min(ln["h"], g["h"]) or (g["h"] < 0.6 * ln["h"] and inside):
                gap = g["x"] - (ln["x"] + ln["w"])
                if -3 <= gap <= 0.75 * max(ln["h"], 6):
                    if best is None or gap < best[1]:
                        best = (ln, gap)
        if best:
            ln = best[0]
            x0 = min(ln["x"], g["x"])
            y0 = min(ln["y"], g["y"])
            x1 = max(ln["x"] + ln["w"], g["x"] + g["w"])
            y1 = max(ln["y"] + ln["h"], g["y"] + g["h"])
            ln.update(x=x0, y=y0, w=x1 - x0, h=y1 - y0)
            ln["words"].append(g)
        else:
            lines.append({"x": g["x"], "y": g["y"], "w": g["w"], "h": g["h"], "words": [g]})
    return lines


# ---------- 1차: 쪽마다 재기 ----------
pages = []
ratios = []  # 글자 크기 대비 한글 잉크 높이 (윤곽선 글자의 크기를 어림하는 데 쓴다)
for pi, p in enumerate(doc):
    img = page_pix(p)
    pn = pi + 1
    big = p.get_pixmap(matrix=fitz.Matrix(1920 / W, 1920 / W), alpha=False)
    big.save(os.path.join(OUT, "pages", f"p{pn:02d}.png"))

    texts = []
    for b in p.get_text("rawdict")["blocks"]:
        if b["type"] != 0:
            continue
        for l in b["lines"]:
            # 글자 하나하나의 자리를 보고 낱말 사이 띄어쓰기를 되살린다 (PDF에 빈칸 글자가 없는 경우가 있다)
            prev_end = None
            for s in l["spans"]:
                txt = ""
                for ch in s.get("chars", []):
                    gap = ch["origin"][0] - prev_end if prev_end is not None else 0
                    if prev_end is not None and gap > 0.22 * s["size"] and not txt.endswith(" ") and ch["c"] != " ":
                        txt += " "
                    txt += ch["c"]
                    prev_end = ch["bbox"][2]
                s["text"] = txt
                s["gapped"] = " " in txt.strip()
            runs = [s for s in l["spans"] if s["text"].strip()]
            if not runs:
                continue
            t = "".join(s["text"] for s in l["spans"]).strip()
            s0 = max(runs, key=lambda s: len(s["text"]))
            x0, y0, x1, y1 = l["bbox"]
            item = {"t": t, "x": r1(x0), "y": r1(y0), "w": r1(x1 - x0), "h": r1(y1 - y0), "size": round(s0["size"], 2),
                    "font": s0["font"], "color": hexc(s0["color"]),
                    "bold": bool(s0["flags"] & 16) or "bold" in s0["font"].lower()}
            # 기준선(글자가 놓이는 선)과 시작점. 글 상자 자리를 계산할 때 쓴다
            item["ox"] = round(runs[0]["origin"][0], 2)
            item["base"] = round(runs[0]["origin"][1], 2)
            item["spans"] = [{"t": s["text"], "ox": round(s["origin"][0], 2), "base": round(s["origin"][1], 2), "w": round(s["bbox"][2] - s["bbox"][0], 2), "spaced": bool(s.get("gapped")),
                              "font": s["font"], "size": round(s["size"], 2), "color": hexc(s["color"]),
                              "bold": bool(s["flags"] & 16) or "bold" in s["font"].lower()} for s in runs]
            if len({(s["font"], round(s["size"], 1), s["color"]) for s in runs}) > 1:
                item["runs"] = [{"t": s["text"], "font": s["font"], "size": round(s["size"], 2), "color": hexc(s["color"]),
                                 "bold": bool(s["flags"] & 16) or "bold" in s["font"].lower()} for s in runs]
            ib = ink_box_hi(p, x0, y0, x1 - x0, y1 - y0, hexc(s0["color"]))
            if ib:
                item["ink"] = [round(v, 2) for v in ib]
                if HANGUL.search(t) and s0["size"] >= 9 and len(t) >= 2 and re.fullmatch(r"[가-힣A-Za-z0-9 ]+", t):
                    ratios.append(ib[3] / s0["size"])
            texts.append(item)

    shapes, glyphs = [], []
    for zi, g in enumerate(p.get_drawings()):
        r = g["rect"]
        if r.width < 0.3 and r.height < 0.3:
            continue
        if g.get("fill_opacity") == 0:
            g["fill"] = None
        if g.get("stroke_opacity") == 0:
            g["color"] = None
        if g.get("fill") is None and g.get("color") is None:
            continue  # 보이지 않는 도형
        kind = classify(g, img)
        kinds = collections.Counter(it[0] for it in g["items"])
        rec = {"z": zi, "kind": kind, "x": r1(r.x0), "y": r1(r.y0), "w": r1(r.width), "h": r1(r.height), "fill": hexc(g.get("fill")),
               "stroke": hexc(g.get("color")), "sw": round(g.get("width") or 0, 2)}
        fo, so = g.get("fill_opacity"), g.get("stroke_opacity")
        if fo is not None and fo < 0.999 and g.get("fill") is not None:
            rec["fill_opacity"] = round(fo, 3)
        if so is not None and so < 0.999 and g.get("color") is not None:
            rec["stroke_opacity"] = round(so, 3)
        if g.get("dashes") and g["dashes"] not in ("[] 0", ""):
            rec["dash"] = g["dashes"]
        if kind in ("roundrect", "polygon", "path", "stroke-path", "ellipse"):
            rec["items"] = dict(kinds)
        if kind == "glyph":
            glyphs.append(rec)
        else:
            shapes.append(rec)

    images = []
    k = 0
    for im in p.get_image_info(xrefs=True):
        rr = fitz.Rect(im["bbox"])
        k += 1
        rec = {"x": r1(rr.x0), "y": r1(rr.y0), "w": r1(rr.width), "h": r1(rr.height), "px": [im["width"], im["height"]]}
        fn = f"p{pn:02d}_{k:02d}.png"
        try:
            if im["xref"]:
                pix = fitz.Pixmap(doc, im["xref"])
                info = doc.extract_image(im["xref"])
                if info.get("smask"):
                    mask = fitz.Pixmap(doc, info["smask"])
                    if pix.alpha:
                        pix = fitz.Pixmap(pix, 0)
                    pix = fitz.Pixmap(pix, mask)
                if pix.n - pix.alpha >= 4:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                pix.save(os.path.join(OUT, "images", fn))
                rec["file"] = "images/" + fn
            # 쪽에 그려진 모습 그대로 잘라 둔 것 (배경 포함)
            clip = p.get_pixmap(matrix=fitz.Matrix(6, 6), clip=rr, alpha=False)
            vf = f"p{pn:02d}_{k:02d}_view.png"
            clip.save(os.path.join(OUT, "images", vf))
            rec["view"] = "images/" + vf
        except Exception as e:  # 못 뽑는 그림은 위치만 적는다
            rec["error"] = str(e)[:80]
        images.append(rec)

    pages.append({"page": pn, "texts": texts, "glyph_words": glyphs, "shapes": shapes, "images": images})

RATIO = statistics.median(ratios) if len(ratios) >= 5 else 0.875

# ---------- 2차: 윤곽선 글자를 줄로 묶고 크기를 어림 ----------
for pg in pages:
    lines = group_lines(pg["glyph_words"])
    out = []
    for ln in lines:
        hs = sorted(w["h"] for w in ln["words"] if w["h"] >= 0.5 * ln["h"])
        if not hs:
            hs = [ln["h"]]
        top = hs[-1] if len(hs) < 4 else hs[int(0.75 * (len(hs) - 1))]
        cols = collections.Counter()
        for w in ln["words"]:
            cols[w["fill"]] += w["w"]
        out.append({"x": r1(ln["x"]), "y": r1(ln["y"]), "w": r1(ln["w"]), "h": r1(ln["h"]), "words": len(ln["words"]),
                    "color": cols.most_common(1)[0][0], "colors": list(cols), "est_size": round(top / RATIO * 2) / 2,
                    "word_boxes": [[w["x"], w["y"], w["w"], w["h"], w["fill"]] for w in sorted(ln["words"], key=lambda w: w["x"])]})
    out.sort(key=lambda l: (l["y"], l["x"]))
    pg["outline_lines"] = out
    del pg["glyph_words"]

json.dump({"W": W, "H": H, "source": os.path.abspath(SRC).replace(os.sep, "/"), "ink_ratio": round(RATIO, 4), "pages": pages}, open(os.path.join(OUT, "measure.json"), "w", encoding="utf-8"),
          ensure_ascii=False)

# ---------- 쪽별 목록 ----------
for pg in pages:
    rows = []
    for t in pg["texts"]:
        extra = ""
        if "runs" in t:
            extra = " | 섞인 서식: " + " / ".join(f"'{r['t']}' {r['size']}pt{' 굵게' if r['bold'] else ''} {r['color']}" for r in t["runs"])
        ink = f" 잉크[{t['ink'][0]},{t['ink'][1]},{t['ink'][2]},{t['ink'][3]}]" if "ink" in t else ""
        ink += f" 기준선 {t['base']} 시작 {t['ox']}" if "base" in t else ""
        rows.append((t["y"], t["x"], f"글자   x={t['x']} y={t['y']} w={t['w']} h={t['h']}{ink} | {t['font']} {t['size']}pt{' 굵게' if t['bold'] else ''} {t['color']} | \"{t['t']}\"{extra}"))
    for l in pg["outline_lines"]:
        rows.append((l["y"], l["x"], f"윤곽선글자 x={l['x']} y={l['y']} w={l['w']} h={l['h']} (이 상자가 곧 잉크 범위) | 낱말 {l['words']}개 어림 {l['est_size']}pt 색 {'/'.join(str(c) for c in l['colors'])} | 내용은 쪽 그림에서 읽을 것"))
    for s in pg["shapes"]:
        o = f" 불투명도 {s['fill_opacity']}" if "fill_opacity" in s else ""
        d = f" 점선 {s['dash']}" if "dash" in s else ""
        it = f" 구성 {s['items']}" if "items" in s else ""
        rows.append((s["y"], s["x"], f"도형   x={s['x']} y={s['y']} w={s['w']} h={s['h']} | {s['kind']} 채움 {s['fill']} 선 {s['stroke']} {s['sw']}pt{o}{d}{it} | 순서 {s['z']}"))
    for im in pg["images"]:
        rows.append((im["y"], im["x"], f"그림   x={im['x']} y={im['y']} w={im['w']} h={im['h']} | 원본 {im['px'][0]}x{im['px'][1]}px | {im.get('file', '(파일 없음)')} , {im.get('view', '')}"))
    rows.sort(key=lambda r: (r[0], r[1]))
    with open(os.path.join(OUT, "dump", f"p{pg['page']:02d}.txt"), "w", encoding="utf-8") as f:
        f.write(f"# {pg['page']}쪽  (장표 {W}x{H}pt, 단위 pt, 왼쪽 위가 0,0)\n")
        f.write(f"# 글자 {len(pg['texts'])}줄, 윤곽선 글자 {len(pg['outline_lines'])}줄, 도형 {len(pg['shapes'])}개, 그림 {len(pg['images'])}개\n")
        for r in rows:
            f.write(r[2] + "\n")

# ---------- 전체 보기 ----------
thumbs = [Image.open(os.path.join(OUT, "pages", f"p{i + 1:02d}.png")).convert("RGB") for i in range(len(pages))]
cols = 3
tw = 640
th = int(tw * H / W)
rowsn = (len(thumbs) + cols - 1) // cols
sheet = Image.new("RGB", (cols * tw, rowsn * (th + 24)), "white")
dr = ImageDraw.Draw(sheet)
for i, im in enumerate(thumbs):
    cx, cy = (i % cols) * tw, (i // cols) * (th + 24)
    dr.text((cx + 4, cy + 4), f"p{i + 1}", fill="black")
    sheet.paste(im.resize((tw, th), Image.LANCZOS), (cx, cy + 24))
sheet.save(os.path.join(OUT, "overview.jpg"), quality=85)

# ---------- 통계와 틀 후보 ----------
fonts = collections.Counter()
tsize = collections.Counter()
osize = collections.Counter()
tcol = collections.Counter()
fills = collections.Counter()
strokes = collections.Counter()
widths = collections.Counter()
rep = collections.defaultdict(set)
for pg in pages:
    for t in pg["texts"]:
        fonts[t["font"]] += len(t["t"])
        tsize[round(t["size"] * 2) / 2] += 1
        tcol[t["color"]] += len(t["t"])
        rep[("글자", round(t["x"]), round(t["y"]), round(t["size"]), t["t"] if len(t["t"]) > 14 else "*")].add(pg["page"])
    for l in pg["outline_lines"]:
        osize[l["est_size"]] += 1
        tcol[l["color"]] += l["words"] * 2
        rep[("윤곽선글자 시작점", round(l["x"]), round(l["y"]), round(l["h"]))].add(pg["page"])
    for s in pg["shapes"]:
        if s["fill"]:
            fills[s["fill"]] += s["w"] * s["h"]
        if s["stroke"]:
            strokes[s["stroke"]] += 1
            widths[s["sw"]] += 1
        rep[("도형", s["kind"], round(s["x"]), round(s["y"]), round(s["w"]), round(s["h"]), s["fill"], s["stroke"])].add(pg["page"])
    for im in pg["images"]:
        rep[("그림", round(im["x"]), round(im["y"]), round(im["w"]), round(im["h"]))].add(pg["page"])
with open(os.path.join(OUT, "summary.txt"), "w", encoding="utf-8") as f:
    def P(*a):
        f.write(" ".join(str(x) for x in a) + "\n")
    P(f"장표 크기 {W}x{H}pt, {len(pages)}쪽")
    P(f"한글 잉크 높이 / 글자 크기 = {RATIO:.3f} (글자가 살아 있는 줄 {len(ratios)}개로 계산, 5개 미만이면 0.875 가정)")
    P("\n[글꼴] (글자 수)")
    for k, v in fonts.most_common(12):
        P("  ", k, v)
    P("\n[글자 크기 pt] 글자가 살아 있는 줄 (줄 수)")
    for k, v in sorted(tsize.items()):
        P("  ", k, v)
    P("\n[글자 크기 pt] 윤곽선 글자 어림값 (줄 수). 어림이므로 0.5~1pt 틀릴 수 있다")
    for k, v in sorted(osize.items()):
        P("  ", k, v)
    P("\n[글자 색]")
    for k, v in tcol.most_common(14):
        P("  ", k, v)
    P("\n[채움 색] (넓이 합)")
    for k, v in fills.most_common(24):
        P("  ", k, round(v))
    P("\n[선 색] (개수)")
    for k, v in strokes.most_common(14):
        P("  ", k, v)
    P("\n[선 굵기 pt] (개수)")
    for k, v in sorted(widths.items()):
        P("  ", k, v)
    P("\n[여러 쪽에 같은 자리로 되풀이되는 요소: 틀 후보]")
    need = max(3, int(0.35 * len(pages)))
    for k, v in sorted(rep.items(), key=lambda kv: -len(kv[1])):
        if len(v) >= need:
            P("  ", len(v), "쪽:", k, "| 쪽", sorted(v))
    P("\n[쪽별 요소 수]")
    for pg in pages:
        P(f"  p{pg['page']}: 글자 {len(pg['texts'])}, 윤곽선 글자 {len(pg['outline_lines'])}, 도형 {len(pg['shapes'])}, 그림 {len(pg['images'])}")
print(open(os.path.join(OUT, "summary.txt"), encoding="utf-8").read())

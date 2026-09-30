# -*- coding: utf-8 -*-
"""글자 위치 보정값을 자동으로 구한다.

원본에서 글자 조각을 골라 같은 글꼴과 크기로 파워포인트에 다시 그려 보고,
글 상자 자리와 실제 글자가 놓인 기준선의 차이를 잰다. 결과는 calib.json 에 적는다.
lib.js 의 textAt / paraAt 이 이 값을 읽어, 원본에서 잰 기준선 자리에 글자를 정확히 놓는다.

쓰는 법:  python calib.py <양식 측정 폴더>
만드는 것: <폴더>/calib.json, <폴더>/calib/ (시험 장표와 그린 결과)
"""
import fitz, json, sys, io, os, re, glob, subprocess, collections, statistics

if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))


def nrm(s):
    return re.sub(r"[^a-z0-9가-힣]", "", s.lower())


def font_index():
    """설치된 글꼴의 이름표. {정규화한 이름: 글꼴 이름}"""
    from PIL import ImageFont
    idx = {}
    from fontdirs import FONT_DIRS
    for d in FONT_DIRS:
        for f in glob.glob(os.path.join(d, "*")):
            if not f.lower().endswith((".ttf", ".ttc", ".otf")):
                continue
            for i in range(8 if f.lower().endswith(".ttc") else 1):
                try:
                    fam, sty = ImageFont.truetype(f, 10, index=i).getname()
                except Exception:
                    break
                idx.setdefault(nrm(fam), fam)
    return idx


def map_font(pdf_name, idx):
    """PDF에 적힌 글꼴 이름을 설치된 글꼴 이름으로 바꾼다. 없으면 None."""
    n = nrm(pdf_name.split("+")[-1])
    best = None
    for k, fam in idx.items():
        if n.startswith(k) and (best is None or len(k) > len(best[0])):
            best = (k, fam)
    if not best:
        return None
    rest = n[len(best[0]):]
    return {"face": best[1], "bold": "bold" in rest or "heavy" in rest, "italic": "italic" in rest or "oblique" in rest}


def size_key(v):
    return round(v * 2) / 2


def spans_of(pdf):
    d = fitz.open(pdf)
    out = []
    for pi, p in enumerate(d):
        for b in p.get_text("dict")["blocks"]:
            if b["type"] != 0:
                continue
            for l in b["lines"]:
                for s in l["spans"]:
                    if s["text"].strip():
                        out.append({"slide": pi + 1, "t": s["text"], "ox": s["origin"][0], "base": s["origin"][1], "w": s["bbox"][2] - s["bbox"][0],
                                    "font": s["font"], "size": s["size"]})
    return out


def run(cmd):
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        print((r.stdout + r.stderr).decode("utf-8", "replace")[-800:])
        sys.exit(2)


def build_and_render(spec, work, tag):
    sp = os.path.join(work, tag + ".json")
    json.dump(spec, open(sp, "w", encoding="utf-8"), ensure_ascii=False)
    px = os.path.join(work, tag + ".pptx")
    run(["node", os.path.join(HERE, "calib_build.js"), sp, px])
    run([sys.executable, os.path.join(HERE, "render.py"), px, work, tag])
    return os.path.join(work, tag + ".pdf")


def match(rend, slide, text, ox, base=None, size=12):
    """그린 결과에서 같은 글을 찾는다. 같은 글이 여러 번 나오면 자리가 가장 가까운 것을 고르고, 너무 멀면 버린다."""
    c = [r for r in rend if r["slide"] == slide and nrm(r["t"]) == nrm(text) and abs(r["ox"] - ox) <= 4
         and (base is None or abs(r["base"] - base) <= 1.2 * size)]
    if not c:
        return None
    return min(c, key=lambda r: abs(r["ox"] - ox) + (abs(r["base"] - base) if base is not None else 0))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    MD = sys.argv[1]
    meas = json.load(open(os.path.join(MD, "measure.json"), encoding="utf-8"))
    W, H = meas["W"], meas["H"]
    work = os.path.join(MD, "calib")
    os.makedirs(work, exist_ok=True)
    idx = font_index()

    # 1. 원본에 쓰인 글꼴과 크기 묶음
    use = collections.Counter()
    samples = collections.defaultdict(list)
    for pg in meas["pages"]:
        for t in pg["texts"]:
            for s in t.get("spans", []):
                txt = s["t"]
                key = (s["font"], size_key(s["size"]))
                use[key] += len(txt.strip())
                if len(txt.strip()) >= 2 and txt == txt.strip() and s["w"] > 4 and not s.get("spaced"):
                    samples[key].append({"page": pg["page"], **s})
    fonts = {}
    for (f, _), n in use.items():
        if f not in fonts:
            m = map_font(f, idx)
            fonts[f] = dict(m, ok=True) if m else {"face": None, "ok": False}
    missing = [f for f, v in fonts.items() if not v["ok"]]

    # 2. 시험 장표: 원본 글자 조각을 기준선에 상자 가운데를 맞춰 그린다
    slides = collections.defaultdict(list)
    picked = []
    for key, lst in samples.items():
        if not fonts[key[0]]["ok"]:
            continue
        lst = sorted(lst, key=lambda s: -len(s["t"]))
        seen_pages = set()
        k = 0
        for s in lst:
            if k >= 4:
                break
            if s["page"] in seen_pages and len(lst) > 4:
                continue
            seen_pages.add(s["page"])
            size = key[1]
            h = size * 2
            item = {"kind": "box", "t": s["t"], "x": s["ox"], "y": s["base"] - h / 2, "w": s["w"] * 1.4 + 40, "h": h, "size": size,
                    "face": fonts[key[0]]["face"], "bold": fonts[key[0]]["bold"]}
            # 같은 쪽에서 자리가 겹치면 건너뛴다
            if any(abs(o["y"] - item["y"]) < h and not (o["x"] + o["w"] < item["x"] or item["x"] + item["w"] < o["x"]) for o in slides[s["page"]]):
                continue
            slides[s["page"]].append(item)
            picked.append((key, s, item))
            k += 1
    # 여러 줄 글: 줄 간격을 pt로 고정했을 때 첫 줄 기준선이 상자 위에서 얼마나 내려오는지
    para_keys = [k for k, _ in use.most_common() if fonts[k[0]]["ok"] and k[1] >= 7][:14]
    para_items = []
    y = 20
    ps = []
    for key in para_keys:
        for mul in (1.2, 1.7):
            pitch = round(key[1] * mul, 1)
            hh = pitch * 2 + key[1]
            if y + hh > H - 10:
                ps.append(para_items)
                para_items = []
                y = 20
            it = {"kind": "para", "lines": ["가나다라Agx", "마바사아Bgy"], "x": 40, "y": y, "w": 300, "h": hh, "size": key[1], "pitch": pitch,
                  "face": fonts[key[0]]["face"], "bold": fonts[key[0]]["bold"], "key": f"{key[0]}|{key[1]:g}"}
            para_items.append(it)
            y += hh + 8
    if para_items:
        ps.append(para_items)
    order = sorted(slides)
    spec = {"W": W, "H": H, "slides": [{"name": f"p{p}", "items": slides[p]} for p in order] + [{"name": "para", "items": x} for x in ps]}
    pdf = build_and_render(spec, work, "pass1")
    rend = spans_of(pdf)

    combos = collections.defaultdict(list)
    wrong_font = collections.Counter()
    for key, s, item in picked:
        sl = order.index(s["page"]) + 1
        r = match(rend, sl, s["t"], s["ox"], s["base"], key[1])
        if not r:
            continue
        if nrm(r["font"].split("+")[-1]) != nrm(key[0].split("+")[-1]):
            wrong_font[key[0]] += 1
        n = max(1, len(s["t"]))
        combos[key].append({"dy": r["base"] - s["base"], "dx": r["ox"] - s["ox"], "cs": (s["w"] - r["w"]) / n, "size_err": r["size"] - s["size"]})
    para = {}
    for pi, items in enumerate(ps):
        sl = len(order) + pi + 1
        for it in items:
            a = match(rend, sl, it["lines"][0], it["x"])
            c = [r for r in rend if r["slide"] == sl and nrm(r["t"]) == nrm(it["lines"][0]) and abs(r["base"] - it["y"]) < it["h"]]
            if c:
                a = min(c, key=lambda r: abs(r["base"] - it["y"] - it["pitch"]))
            c2 = [r for r in rend if r["slide"] == sl and nrm(r["t"]) == nrm(it["lines"][1]) and 0 < r["base"] - it["y"] < it["h"] + it["pitch"]]
            if not a or not c2:
                continue
            b = min(c2, key=lambda r: abs(r["base"] - a["base"] - it["pitch"]))
            para.setdefault(it["key"], []).append({"pitch": it["pitch"], "first": a["base"] - it["y"], "got_pitch": b["base"] - a["base"]})

    out = {"W": W, "H": H, "fonts": fonts, "combos": {}, "para": {}, "note": "dy: 상자 가운데에서 기준선까지 거리(pt). cs: 글자 사이 보정(pt). para: 첫 줄 기준선 = 상자 위 + p*줄간격 + q"}
    for key, v in combos.items():
        if not v:
            continue
        cs = statistics.median(x["cs"] for x in v)
        if len(v) < 2 or not all((x["cs"] > 0.05) == (cs > 0.05) and (x["cs"] < -0.05) == (cs < -0.05) for x in v):
            cs = 0  # 조각이 하나뿐이거나 방향이 엇갈리면 자간 보정을 하지 않는다
        out["combos"][f"{key[0]}|{key[1]:g}"] = {"dy": round(statistics.median(x["dy"] for x in v), 3), "dx": round(statistics.median(x["dx"] for x in v), 3),
                                                 "cs": round(cs, 2) if abs(cs) >= 0.08 else 0, "n": len(v)}
    # 글꼴마다 크기에 비례하는 식도 남긴다 (재 보지 않은 크기에 쓴다)
    by_font = collections.defaultdict(list)
    for k, v in out["combos"].items():
        f, sz = k.split("|")
        by_font[f].append((float(sz), v["dy"]))
    out["per_font"] = {f: {"dy_per_pt": round(statistics.median(d / s for s, d in v), 4)} for f, v in by_font.items()}
    for k, v in para.items():
        if len(v) >= 2 and abs(v[0]["pitch"] - v[1]["pitch"]) > 0.1:
            p = (v[1]["first"] - v[0]["first"]) / (v[1]["pitch"] - v[0]["pitch"])
            q = v[0]["first"] - p * v[0]["pitch"]
            out["para"][k] = {"p": round(p, 4), "q": round(q, 3)}
    out_path = os.path.join(MD, "calib.json")
    json.dump(out, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # 3. 보정값을 넣어 다시 그려 확인한다
    vslides = collections.defaultdict(list)
    for key, s, item in picked:
        vslides[s["page"]].append({"kind": "at", "t": s["t"], "ox": s["ox"], "base": s["base"], "size": key[1], "font": key[0]})
    pitems = []
    yb = 40
    for k in list(out["para"])[:10]:
        f, sz = k.split("|")
        sz = float(sz)
        pitch = round(sz * 1.45, 1)
        pitems.append({"kind": "paraAt", "lines": ["가나다라Agx", "마바사아Bgy"], "ox": 40, "base": yb, "pitch": pitch, "w": 300, "size": sz, "font": f})
        yb += pitch * 2 + 14
        if yb > H - 40:
            break
    spec2 = {"W": W, "H": H, "calib": out_path, "slides": [{"name": f"p{p}", "items": vslides[p]} for p in order] + [{"name": "para", "items": pitems}]}
    pdf2 = build_and_render(spec2, work, "pass2")
    rend2 = spans_of(pdf2)
    eb, ex, ew = [], [], []
    for key, s, item in picked:
        r = match(rend2, order.index(s["page"]) + 1, s["t"], s["ox"], s["base"], key[1])
        if r:
            eb.append(abs(r["base"] - s["base"]))
            ex.append(abs(r["ox"] - s["ox"]))
            ew.append(abs(r["w"] - s["w"]))
    ep = []
    for it in pitems:
        c = [r for r in rend2 if r["slide"] == len(order) + 1 and nrm(r["t"]) == nrm(it["lines"][0])]
        if c:
            ep.append(min(abs(r["base"] - it["base"]) for r in c))
    res = {"기준선 오차 최대": round(max(eb), 3) if eb else None, "시작점 오차 최대": round(max(ex), 3) if ex else None,
           "너비 오차 가운데값": round(statistics.median(ew), 3) if ew else None, "너비 오차 최대": round(max(ew), 3) if ew else None, "여러 줄 첫 기준선 오차 최대": round(max(ep), 3) if ep else None, "견준 조각": len(eb)}
    out["verify"] = res
    out["wrong_font"] = dict(wrong_font)
    json.dump(out, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"보정값 {len(out['combos'])}묶음, 여러 줄 {len(out['para'])}묶음 -> {out_path}")
    print("확인(보정값을 넣어 다시 그린 결과, pt):", json.dumps(res, ensure_ascii=False))
    for f, v in fonts.items():
        print(f"  글꼴 {f} -> {v['face'] if v['ok'] else '이 컴퓨터에 없음'}{' 굵게' if v.get('bold') else ''}")
    if missing:
        print("!! 이 컴퓨터에 없는 글꼴:", ", ".join(missing), "| 같은 모양을 내려면 글꼴을 설치해야 한다. 없으면 가장 가까운 글꼴을 골라 보고에 적는다.")
    if wrong_font:
        print("!! 그려 보니 다른 글꼴로 바뀐 것:", dict(wrong_font))
    cs = {k: v["cs"] for k, v in out["combos"].items() if v["cs"]}
    if cs:
        print("글자 사이 보정(자간)이 필요한 묶음:", json.dumps(cs, ensure_ascii=False))


if __name__ == "__main__":
    main()

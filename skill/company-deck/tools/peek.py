# -*- coding: utf-8 -*-
"""쪽의 일부를 자세히 들여다보는 도구. PDF면 원본이든 내가 만든 결과든 똑같이 쓴다. 좌표 단위는 pt.

  python peek.py crop   <pdf> <쪽> <x0> <y0> <x1> <y1> <저장.png> [배율=4]   그 영역을 크게 잘라 저장
  python peek.py colors <pdf> <쪽> <x0> <y0> <x1> <y1>                       그 영역에 많이 나오는 색 순서대로
  python peek.py line   <pdf> <쪽> <x0> <y0> <x1> <y1> [점수=9]              두 점 사이를 따라가며 색을 읽는다 (그라데이션 확인용)
  python peek.py ink    <pdf> <쪽> <x0> <y0> <x1> <y1> [색 RRGGBB]           그 영역 안 글자 잉크의 범위 (왼쪽, 위, 너비, 높이)
  python peek.py fit    <글꼴파일들 쉼표로> <잉크너비> <잉크높이> <글>       윤곽선 글자의 글꼴과 크기 알아내기
  python peek.py fonts  [찾을말]                                             설치된 글꼴 파일 찾기
  python peek.py fit-frame <양식 측정 폴더> <title|pageno> <쪽> "<그 쪽에 적힌 글>" [글꼴 이름들 쉼표로]   틀의 글자가 윤곽선일 때 글꼴, 크기, 기준선을 찾아 frame.json에 적는다
  python peek.py gradient <저장.png> <너비px> <높이px> <색1> <색2> [h|v] [색3 ...]   그라데이션 그림 만들기
  python peek.py pair   <pdf A> <쪽> <pdf B> <쪽> <저장.jpg>                  두 쪽을 위아래로 붙여 비교
"""
import fitz, sys, io, os, collections, glob
from PIL import Image

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


def rgb(h):
    h = h.strip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def hx(c):
    return "%02X%02X%02X" % tuple(c[:3])


def flat(im):
    return list(im.get_flattened_data() if hasattr(im, "get_flattened_data") else im.getdata())


def clip_img(pdf, page, x0, y0, x1, y1, scale):
    d = fitz.open(pdf)
    p = d[int(page) - 1]
    rr = fitz.Rect(float(x0), float(y0), float(x1), float(y1)) & p.rect
    pix = p.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=rr, alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples), rr


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return
    cmd = a[0]
    if cmd == "crop":
        sc = float(a[8]) if len(a) > 8 else 4
        im, rr = clip_img(a[1], a[2], a[3], a[4], a[5], a[6], sc)
        im.save(a[7])
        print("저장", a[7], im.size)
    elif cmd == "colors":
        im, rr = clip_img(a[1], a[2], a[3], a[4], a[5], a[6], 3)
        c = collections.Counter(flat(im))
        tot = sum(c.values())
        for k, v in c.most_common(12):
            print(hx(k), f"{v / tot * 100:.1f}%")
    elif cmd == "line":
        n = int(a[7]) if len(a) > 7 else 9
        d = fitz.open(a[1])
        p = d[int(a[2]) - 1]
        pix = p.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
        im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        x0, y0, x1, y1 = map(float, a[3:7])
        for i in range(n):
            t = i / max(1, n - 1)
            x, y = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
            px = im.getpixel((min(im.width - 1, int(x * 3)), min(im.height - 1, int(y * 3))))
            print(f"x={x:.1f} y={y:.1f} {hx(px)}")
    elif cmd == "ink":
        sc = 8
        im, rr = clip_img(a[1], a[2], a[3], a[4], a[5], a[6], sc)
        data = flat(im)
        bg = collections.Counter(data).most_common(1)[0][0]
        tc = rgb(a[7]) if len(a) > 7 else None
        xs0 = ys0 = 10 ** 9
        xs1 = ys1 = -1
        if tc is not None:
            v = [p - q for p, q in zip(tc, bg)]
            vv = sum(c * c for c in v) or 1
        for idx, px in enumerate(data):
            if tc is not None:
                u = [p - q for p, q in zip(px, bg)]
                t = sum(p * q for p, q in zip(u, v)) / vv
                res = sum((p - t * q) ** 2 for p, q in zip(u, v)) ** 0.5
                hit = t > 0.5 and res < 40
            else:
                hit = sum(abs(p - q) for p, q in zip(px, bg)) > 150
            if hit:
                i, j = idx % im.width, idx // im.width
                xs0 = min(xs0, i); xs1 = max(xs1, i); ys0 = min(ys0, j); ys1 = max(ys1, j)
        if xs1 < 0:
            print("잉크 없음 (바탕색", hx(bg), ")")
        else:
            print(f"잉크 왼쪽 {rr.x0 + xs0 / sc:.2f} 위 {rr.y0 + ys0 / sc:.2f} 너비 {(xs1 - xs0 + 1) / sc:.2f} 높이 {(ys1 - ys0 + 1) / sc:.2f} 오른쪽 {rr.x0 + (xs1 + 1) / sc:.2f} 아래 {rr.y0 + (ys1 + 1) / sc:.2f} (바탕색 {hx(bg)})")
    elif cmd == "fit":
        from PIL import ImageFont
        files = a[1].split(",")
        w, h, text = float(a[2]), float(a[3]), a[4]
        rows = []
        for fn in files:
            from fontdirs import find_font
            path = find_font(fn)
            f = ImageFont.truetype(path, 1000)
            b = f.getbbox(text)
            w0, h0 = b[2] - b[0], b[3] - b[1]
            sh, sw = h / h0 * 1000, w / w0 * 1000
            rows.append((abs(sh - sw) / sh, fn, sh, sw))
        rows.sort()
        for err, fn, sh, sw in rows:
            print(f"{fn}: 높이로 본 크기 {sh:.2f}pt, 너비로 본 크기 {sw:.2f}pt, 둘의 차이 {err * 100:.1f}%")
        print("둘의 차이가 가장 작은 글꼴이 답에 가깝다. 크기는 높이로 본 값을 0.5pt 단위로 맞춰 쓰되, 글에 괄호나 쉼표처럼 위아래로 튀는 글자가 있으면 너비로 본 값을 믿는다.")
    elif cmd == "fonts":
        key = a[1].lower() if len(a) > 1 else ""
        from PIL import ImageFont
        from fontdirs import FONT_DIRS
        for d in FONT_DIRS:
            for p in sorted(glob.glob(os.path.join(d, "*.tt[fc]")) + glob.glob(os.path.join(d, "*.otf"))):
                try:
                    nm = ImageFont.truetype(p, 20).getname()
                except Exception:
                    continue
                if key in (nm[0] + " " + nm[1] + " " + os.path.basename(p)).lower():
                    print(os.path.basename(p), "|", nm[0], "|", nm[1])
    elif cmd == "gradient":
        out, w, h = a[1], int(a[2]), int(a[3])
        rest = a[4:]
        direction = "h"
        cols = []
        for t in rest:
            if t in ("h", "v"):
                direction = t
            else:
                cols.append(rgb(t))
        im = Image.new("RGB", (w, h))
        px = im.load()
        n = w if direction == "h" else h
        for i in range(n):
            t = i / max(1, n - 1) * (len(cols) - 1)
            k = min(len(cols) - 2, int(t))
            f = t - k
            c = tuple(int(round(cols[k][j] + (cols[k + 1][j] - cols[k][j]) * f)) for j in range(3))
            if direction == "h":
                for y in range(h):
                    px[i, y] = c
            else:
                for x in range(w):
                    px[x, i] = c
        im.save(out)
        print("저장", out)
    elif cmd == "pair":
        A, _ = clip_img(a[1], a[2], 0, 0, 10 ** 5, 10 ** 5, 1.5)
        B, _ = clip_img(a[3], a[4], 0, 0, 10 ** 5, 10 ** 5, 1.5)
        s = Image.new("RGB", (max(A.width, B.width), A.height + B.height + 8), "black")
        s.paste(A, (0, 0))
        s.paste(B, (0, A.height + 8))
        s.save(a[5], quality=90)
        print("저장", a[5])
    elif cmd == "fit-frame":
        # 틀의 글자(제목, 쪽 번호)가 원본에서 윤곽선으로 바뀌어 있을 때, 글꼴과 크기와 기준선을 찾아 frame.json 과 rules.draft.json 에 적는다
        import json
        from PIL import ImageFont
        md, role, page, text = a[1], a[2], int(a[3]), a[4]
        fr = json.load(open(os.path.join(md, "frame.json"), encoding="utf-8"))
        meas = json.load(open(os.path.join(md, "measure.json"), encoding="utf-8"))
        v = next((q for q in fr["text"] if q["role"] == role), None)
        if v is None:
            print("frame.json 에 그런 역할이 없다:", role, "| 있는 역할:", [q["role"] for q in fr["text"]])
            return
        pg = meas["pages"][page - 1]
        c = [l for l in pg["outline_lines"] if abs(l["y"] - v["ink_top"]) < 4 and l["x"] >= v["x_min"] - 6 and l["x"] + l["w"] <= v["x_max"] + 6]
        if not c:
            print(f"{page}쪽의 그 자리에 윤곽선 글자가 없다. 다른 쪽으로 해 본다. 있는 쪽: {v['pages']}")
            return
        x0 = min(l["x"] for l in c); y0 = min(l["y"] for l in c)
        x1 = max(l["x"] + l["w"] for l in c); y1 = max(l["y"] + l["h"] for l in c)
        w, h = x1 - x0, y1 - y0
        files = {}
        from fontdirs import FONT_DIRS
        for d in FONT_DIRS:
            for p in glob.glob(os.path.join(d, "*")):
                if not p.lower().endswith((".ttf", ".ttc", ".otf")):
                    continue
                for i in range(6 if p.lower().endswith(".ttc") else 1):
                    try:
                        f = ImageFont.truetype(p, 1000, index=i)
                    except Exception:
                        break
                    files[f.getname()] = (p, i)
        want = a[5].split(",") if len(a) > 5 else None
        cal_p = os.path.join(md, "calib.json")
        fams = set()
        styles = None
        if want:
            fams = {w_.strip().lower() for w_ in want}
        elif os.path.exists(cal_p):
            # 이 자료의 살아 있는 글자에 실제로 쓰인 글꼴과 굵기만 견준다
            cf = [q for q in json.load(open(cal_p, encoding="utf-8"))["fonts"].values() if q.get("ok")]
            fams = {q["face"].lower() for q in cf}
            styles = {(q["face"].lower(), "bold" if q.get("bold") else "regular") for q in cf}
        # 원본 잉크가 글자 상자를 얼마나 채우는지 (굵기를 가리는 데 쓴다)
        den0 = None
        try:
            src = fitz.open(meas["source"])
            pix = src[page - 1].get_pixmap(matrix=fitz.Matrix(8, 8), clip=fitz.Rect(x0, y0, x1, y1), alpha=False)
            im0 = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("L")
            d0 = flat(im0)
            bgv = collections.Counter(d0).most_common(1)[0][0]
            den0 = sum(abs(p_ - bgv) for p_ in d0) / (255.0 * len(d0))
        except Exception:
            pass
        rows = []
        for (fam, sty), (p, i) in files.items():
            if fams and fam.lower() not in fams:
                continue
            if sty.lower() not in ("regular", "bold", "semibold", "light", "medium", "semilight"):
                continue
            if styles is not None and (fam.lower(), sty.lower()) not in styles:
                continue
            f = ImageFont.truetype(p, 1000, index=i)
            try:
                b = f.getbbox(text, anchor="ls")
            except Exception:
                continue
            w0, h0 = b[2] - b[0], b[3] - b[1]
            if w0 <= 0 or h0 <= 0:
                continue
            sh, sw_ = h / h0 * 1000, w / w0 * 1000
            err = abs(sh - sw_) / sh
            if den0 is not None:
                from PIL import ImageDraw
                f2 = ImageFont.truetype(p, 200, index=i)
                b2 = f2.getbbox(text, anchor="ls")
                im1 = Image.new("L", (b2[2] - b2[0] + 2, b2[3] - b2[1] + 2), 0)
                ImageDraw.Draw(im1).text((-b2[0] + 1, -b2[1] + 1), text, font=f2, fill=255, anchor="ls")
                d1 = flat(im1)
                den1 = sum(d1) / (255.0 * len(d1))
                err += abs(den1 - den0) / max(den0, 1e-6)
            rows.append((err, fam, sty, sh, sw_, b))
        rows.sort()
        for err, fam, sty, sh, sw_, b in rows[:6]:
            print(f"{fam} {sty}: 높이로 본 크기 {sh:.2f}pt, 너비로 본 크기 {sw_:.2f}pt, 어긋남 점수 {err * 100:.1f} (작을수록 가깝다. 크기 차이와 굵기 차이를 더한 값)")
        if not rows:
            print("견줄 글꼴이 없다. 글꼴 이름을 쉼표로 이어 마지막에 준다.")
            return
        err, fam, sty, sh, sw_, b = rows[0]
        size = round(sh * 2) / 2
        n = max(1, len(text) - 1)
        cs = (w - (b[2] - b[0]) * size / 1000) / n
        base = y0 - b[1] * size / 1000
        ox = x0 - b[0] * size / 1000
        bold = sty.lower() in ("bold", "semibold")
        # 다른 쪽에서도 같은 기준선이 나오도록, 글자 위 끝이 아니라 기준선을 적는다
        v.update(font=fam, size=size, bold=bold, base=round(base, 2), fit={"page": page, "text": text, "style": sty, "err": round(err, 3)})
        if abs(cs) > 0.15:
            v["charSpacing"] = round(cs, 2)
        if v["align"] == "left":
            v["x"] = round(ox, 2)
        json.dump(fr, open(os.path.join(md, "frame.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        rp = os.path.join(md, "rules.draft.json")
        if os.path.exists(rp):
            ru = json.load(open(rp, encoding="utf-8"))
            nm = {"title": "제목", "pageno": "쪽 번호"}.get(role)
            for r in ru["chrome"]:
                if r["name"] == nm:
                    r.clear()
                    r.update({"name": nm, "kind": "base", "region": [round(max(0, v["x_min"] - 6), 1), round(max(0, v["y_top"] - 8), 1), fr["W"] - 10 if role == "title" else round(v["x_max"] + 6, 1), round(v["y_bot"] + 8, 1)],
                              "base": v["base"], "size": size, "font": fam, "color": v["color"], "tol": 0.4})
                    r[{"left": "ox", "right": "right", "center": "cx"}[v["align"]]] = v["x"]
            ru.setdefault("font_evidence", {})[fam] = f"{role} {page}쪽 '{text}' 에 맞춰 봄: {sty}, 높이로 본 크기 {sh:.2f}, 너비로 본 크기 {sw_:.2f}"
            if fam.replace(" ", "") not in [x.replace(" ", "") for x in ru["fonts"]]:
                ru["fonts"].append(fam)
            if not any(abs(size - s) <= 0.3 for s in ru["sizes"]):
                ru["sizes"].append(size)
            json.dump(ru, open(rp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"정함: {fam} {sty} {size}pt, 기준선 {base:.2f}, 시작 {ox:.2f}, 자간 {cs:+.2f} -> frame.json 과 rules.draft.json 에 적음")
        print("이미 작업/rules.json 을 만들었다면 그쪽의 틀 규칙도 같게 고친다.")
    else:
        print(__doc__)


main()

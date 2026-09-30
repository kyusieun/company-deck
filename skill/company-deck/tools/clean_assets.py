# -*- coding: utf-8 -*-
"""만든 그림(아이콘, 로고)을 다듬고 검사한다.

쓰는 법:
  python clean_assets.py <만든 그림 폴더> <다듬은 그림 폴더> [--ref 원본에서 잘라낸 같은 종류 그림...] [--size 512] [--keep-ratio] [--transparent]

하는 일
  흰 바탕에 올리고, 둘레 빈 곳을 잘라내고, 크기를 맞춰 저장한다. --transparent 를 주면 흰 바탕을 투명하게 바꾼다.
  검사 1: 그림이 비어 있거나 너무 옅지 않은가
  검사 2: --ref 를 주면, 참고 그림에 없는 색이 많이 섞이지 않았는가 (양식과 결이 다른 그림을 걸러낸다)
  검사 3: 얼룩. 주된 색 몇 가지에서 벗어난 픽셀이 많은가
결과는 <다듬은 그림 폴더>/_report.json 에 적는다. 불량은 다시 만든다.
"""
import glob, os, sys, io, json, argparse, collections
from PIL import Image

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ap = argparse.ArgumentParser()
ap.add_argument("src")
ap.add_argument("dst")
ap.add_argument("--ref", nargs="*", default=[])
ap.add_argument("--size", type=int, default=512)
ap.add_argument("--keep-ratio", action="store_true")
ap.add_argument("--transparent", action="store_true")
ap.add_argument("--max-off", type=float, default=0.10)
a = ap.parse_args()
os.makedirs(a.dst, exist_ok=True)


def flat(im):
    return list(im.get_flattened_data() if hasattr(im, "get_flattened_data") else im.getdata())


def on_white(path):
    im = Image.open(path).convert("RGBA")
    bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
    bg.alpha_composite(im)
    return bg.convert("RGB")


Q = 32
palette = collections.Counter()
for r in a.ref:
    for p in flat(on_white(r).resize((96, 96))):
        if min(p) < 235:
            palette[(p[0] // Q, p[1] // Q, p[2] // Q)] += 1
pal = [k for k, v in palette.items() if v >= 3]

report = {}
for f in sorted(glob.glob(os.path.join(a.src, "*.png"))):
    name = os.path.basename(f)
    rgb = on_white(f)
    mask = rgb.convert("L").point(lambda v: 255 if v < 245 else 0)
    bb = mask.getbbox()
    if not bb:
        report[name] = {"ok": False, "why": "빈 그림"}
        continue
    w, h = bb[2] - bb[0], bb[3] - bb[1]
    if a.keep_ratio:
        pad = int(max(w, h) * 0.03)
        box = (max(0, bb[0] - pad), max(0, bb[1] - pad), min(rgb.width, bb[2] + pad), min(rgb.height, bb[3] + pad))
        out = rgb.crop(box)
        sc = a.size / max(out.size)
        out = out.resize((max(1, int(out.width * sc)), max(1, int(out.height * sc))), Image.LANCZOS)
    else:
        side = int(max(w, h) * 1.06)
        cx, cy = (bb[0] + bb[2]) // 2, (bb[1] + bb[3]) // 2
        canvas = Image.new("RGB", (side, side), "white")
        canvas.paste(rgb.crop((cx - side // 2, cy - side // 2, cx - side // 2 + side, cy - side // 2 + side)), (0, 0))
        out = canvas.resize((a.size, a.size), Image.LANCZOS)
    small = out.resize((128, max(1, int(128 * out.height / out.width))))
    px = flat(small)
    ink = [p for p in px if min(p) < 235]
    fill = len(ink) / max(1, len(px))
    off = 0.0
    if pal and ink:
        bad = 0
        for p in ink:
            k = (p[0] // Q, p[1] // Q, p[2] // Q)
            if min(abs(k[0] - q[0]) + abs(k[1] - q[1]) + abs(k[2] - q[2]) for q in pal) > 2:
                bad += 1
        off = bad / len(ink)
    cnt = collections.Counter((p[0] // 24, p[1] // 24, p[2] // 24) for p in px)
    main = [c for c, n in cnt.most_common(5) if n / len(px) > 0.02]
    smear = sum(1 for p in px if min(abs(p[0] // 24 - m[0]) + abs(p[1] // 24 - m[1]) + abs(p[2] // 24 - m[2]) for m in main) > 3) / len(px)
    ok = fill > 0.02 and off <= a.max_off
    why = []
    if fill <= 0.02:
        why.append("너무 옅거나 비어 있음")
    if off > a.max_off:
        why.append("참고 그림에 없는 색이 많음")
    if a.transparent:
        rgba = out.convert("RGBA")
        data = []
        for (r, g, b, _) in flat(rgba):
            al = 255 - min(r, g, b)
            if al <= 6:
                data.append((255, 255, 255, 0))
            else:
                f_ = al / 255
                data.append((max(0, min(255, int((r - 255 * (1 - f_)) / f_))), max(0, min(255, int((g - 255 * (1 - f_)) / f_))),
                             max(0, min(255, int((b - 255 * (1 - f_)) / f_))), al))
        rgba.putdata(data)
        out = rgba
    out.save(os.path.join(a.dst, name))
    report[name] = {"ok": ok, "채움 비율": round(fill, 3), "참고에 없는 색 비율": round(off, 3), "얼룩 비율": round(smear, 3), "why": ", ".join(why)}
json.dump(report, open(os.path.join(a.dst, "_report.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for k, v in report.items():
    print("OK  " if v["ok"] else "불량", k, v)

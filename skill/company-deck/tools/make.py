# -*- coding: utf-8 -*-
"""만들기, 그리기, 글자 자리 미세 보정, 검사를 한 번에 한다.

쓰는 법 (작업 폴더에서):  python make.py <꼬리표>
    예) python T/make.py v1
기본 경로: 작업/build.js, 결과/새장표.pptx, 작업/그림결과/, 작업/rules.json, 작업/양식/, 작업/재료.md (gather.py가 만든 재료 모음)
다르면: --build, --pptx, --out, --rules, --style, --content 로 준다.

하는 일
  1. node 작업/build.js
  2. 파워포인트로 그린다 (PDF와 쪽 그림)
  3. textAt, paraAt 으로 놓은 글자가 바란 자리에 왔는지 그린 결과에서 다시 잰다.
     0.12pt 넘게 어긋난 것은 작업/nudge.json 에 적고 다시 만들어 그린다 (두 번까지). build.js 는 고칠 필요가 없다.
  4. check.py 로 검사하고 결과를 보여준다.
"""
import sys, io, os, re, json, subprocess, argparse
import fitz

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument("tag")
ap.add_argument("--build", default="작업/build.js")
ap.add_argument("--pptx", default="결과/새장표.pptx")
ap.add_argument("--out", default="작업/그림결과")
ap.add_argument("--rules", default="작업/rules.json")
ap.add_argument("--style", default="작업/양식")
ap.add_argument("--content", default="작업/재료.md")
ap.add_argument("--nudge", default="작업/nudge.json")
a = ap.parse_args()
if not os.path.exists(a.content) and os.path.exists("자료/내용.md"):
    a.content = "자료/내용.md"
env = dict(os.environ, PYTHONIOENCODING="utf-8", DECK_NUDGE=os.path.abspath(a.nudge))


def run(cmd, show=True):
    r = subprocess.run(cmd, capture_output=True, env=env)
    txt = (r.stdout + r.stderr).decode("utf-8", "replace").strip()
    if r.returncode != 0:
        print("실패:", " ".join(cmd[:3]))
        print(txt[-3000:])
        sys.exit(2)
    if show and txt:
        print(txt)
    return txt


def nrm(s):
    return re.sub(r"\s+", "", s)


def rendered_lines(pdf):
    d = fitz.open(pdf)
    out = []
    for pi, p in enumerate(d):
        lines = []
        for b in p.get_text("dict")["blocks"]:
            if b["type"] != 0:
                continue
            for l in b["lines"]:
                ss = [s for s in l["spans"] if s["text"].strip()]
                if not ss:
                    continue
                lines.append({"t": nrm("".join(s["text"] for s in l["spans"])), "ox": ss[0]["origin"][0], "base": ss[0]["origin"][1],
                              "x0": l["bbox"][0], "x1": l["bbox"][2]})
        out.append(lines)
    return out


man_path = re.sub(r"\.pptx$", "", a.pptx) + ".manifest.json"
pdf = os.path.join(a.out, a.tag + ".pdf")
nudge = json.load(open(a.nudge, encoding="utf-8")) if os.path.exists(a.nudge) else {}
for rnd in range(3):
    run(["node", a.build], show=(rnd == 0))
    run([sys.executable, os.path.join(HERE, "render.py"), a.pptx, a.out, a.tag], show=False)
    man = json.load(open(man_path, encoding="utf-8"))
    lines = rendered_lines(pdf)
    changed, worst, n = 0, 0.0, 0
    for m in man["texts"]:
        w = m.get("want")
        if not w or m["slide"] > len(lines):
            continue
        key = nrm(w["line"])[:40]
        if not key:
            continue
        c = [l for l in lines[m["slide"] - 1] if l["t"].startswith(key[:12]) or key.startswith(l["t"][:12])]
        if not c:
            continue
        gx = lambda l: l["ox"] if w["align"] == "left" else (l["x1"] if w["align"] == "right" else (l["x0"] + l["x1"]) / 2)
        l = min(c, key=lambda l: abs(l["base"] - w["base"]) + abs(gx(l) - w["x"]))
        dx, dy = w["x"] - gx(l), w["base"] - l["base"]
        if abs(dx) > 8 or abs(dy) > 8:
            continue  # 다른 글을 잘못 짝지은 것
        n += 1
        worst = max(worst, abs(dx), abs(dy))
        if abs(dx) > 0.12 or abs(dy) > 0.12:
            old = nudge.get(w["key"], {"dx": 0, "dy": 0})
            nudge[w["key"]] = {"dx": round(old["dx"] + (dx if abs(dx) > 0.12 else 0), 3), "dy": round(old["dy"] + (dy if abs(dy) > 0.12 else 0), 3)}
            changed += 1
    print(f"글자 자리 확인 {rnd + 1}회: 견준 글 {n}개, 가장 큰 어긋남 {worst:.2f}pt, 보정한 글 {changed}개")
    if not changed or rnd == 2:
        break
    os.makedirs(os.path.dirname(os.path.abspath(a.nudge)), exist_ok=True)
    json.dump(nudge, open(a.nudge, "w", encoding="utf-8"), ensure_ascii=False)

r = subprocess.run([sys.executable, os.path.join(HERE, "check.py"), pdf, man_path, a.rules, a.style, a.content, a.tag], capture_output=True, env=env)
print((r.stdout + r.stderr).decode("utf-8", "replace").strip())
print(f"\n쪽 그림: {a.out}/{a.tag}_sNN.png , 모아 보기: {a.out}/{a.tag}_sheet.jpg")

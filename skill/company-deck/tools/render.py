# -*- coding: utf-8 -*-
"""PPTX를 파워포인트로 그려서 PDF와 쪽 그림을 만든다. (설치된 파워포인트를 쓴다. 이미 열려 있던 파워포인트는 닫지 않는다.)

쓰는 법:  python render.py <장표.pptx> <결과폴더> [꼬리표]
만드는 것: <결과폴더>/<꼬리표>.pdf, <결과폴더>/<꼬리표>_s01.png ... (가로 1920), <결과폴더>/<꼬리표>_sheet.jpg
"""
import sys, io, os, subprocess, time
import fitz
from PIL import Image

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
if len(sys.argv) < 3:
    print(__doc__)
    sys.exit(1)
pptx = os.path.abspath(sys.argv[1])
out = os.path.abspath(sys.argv[2])
tag = sys.argv[3] if len(sys.argv) > 3 else "render"
os.makedirs(out, exist_ok=True)
pdf = os.path.join(out, tag + ".pdf")
ps1 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "render.ps1")
if os.path.exists(pdf):
    os.remove(pdf)
MAC_SCRIPT = """on run argv
  set src to POSIX file (item 1 of argv)
  set dst to (item 2 of argv)
  tell application "Microsoft PowerPoint"
    open src
    set p to active presentation
    save p in dst as save as PDF
    close p saving no
  end tell
end run"""
last = ""
for attempt in range(3):
    if sys.platform == "darwin":
        # 맥: 파워포인트를 AppleScript로 부린다. 처음 한 번 파일 접근 허용 창이 뜰 수 있다.
        r = subprocess.run(["osascript", "-e", MAC_SCRIPT, pptx, pdf], capture_output=True)
        last = (r.stdout + r.stderr).decode("utf-8", "replace")
    else:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1, "-pptx", pptx, "-pdf", pdf], capture_output=True)
        last = (r.stdout + r.stderr).decode("cp949", "replace")
    if os.path.exists(pdf):
        break
    time.sleep(3)
if not os.path.exists(pdf):
    print("그리기 실패:", last[-600:])
    sys.exit(2)
d = fitz.open(pdf)
ims = []
for i, p in enumerate(d):
    z = 1920 / p.rect.width
    pix = p.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False)
    fn = os.path.join(out, f"{tag}_s{i + 1:02d}.png")
    pix.save(fn)
    ims.append(Image.open(fn).convert("RGB"))
tw = 960
th = int(tw * ims[0].height / ims[0].width)
cols = 2 if len(ims) > 1 else 1
rows = (len(ims) + cols - 1) // cols
sheet = Image.new("RGB", (cols * tw, rows * th), "white")
for i, im in enumerate(ims):
    sheet.paste(im.resize((tw, th), Image.LANCZOS), ((i % cols) * tw, (i // cols) * th))
sheet.save(os.path.join(out, tag + "_sheet.jpg"), quality=88)
print(f"그림 {len(ims)}쪽: {pdf}")

# -*- coding: utf-8 -*-
"""양식 준비를 한 번에 한다: 재기(measure) -> 글자 위치 보정(calib) -> 양식 정리(style).

쓰는 법:  python prepare.py <회사양식.pdf> <양식 측정 폴더>
끝나면 <폴더>/양식요약.md 를 읽는다. 이 단계는 AI가 생각할 것이 없는 기계 작업이다. 2~3분 걸린다.
"""
import sys, io, os, subprocess, time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
if len(sys.argv) < 3:
    print(__doc__)
    sys.exit(1)
pdf, out = sys.argv[1], sys.argv[2]
here = os.path.dirname(os.path.abspath(__file__))
env = dict(os.environ, PYTHONIOENCODING="utf-8")
t0 = time.time()
for name, args, show in (("measure.py", [pdf, out], False), ("calib.py", [out], True), ("style.py", [out], False)):
    r = subprocess.run([sys.executable, os.path.join(here, name)] + args, capture_output=True, env=env)
    txt = (r.stdout + r.stderr).decode("utf-8", "replace")
    if r.returncode != 0:
        print(f"[{name}] 실패\n" + txt[-1500:])
        sys.exit(2)
    if show:
        print(f"[{name}]\n" + txt.strip())
    else:
        print(f"[{name}] 끝")
print(f"\n양식 준비 끝 ({time.time() - t0:.0f}초). 다음 파일을 읽는다: {os.path.join(out, '양식요약.md')} , {os.path.join(out, 'overview.jpg')}")

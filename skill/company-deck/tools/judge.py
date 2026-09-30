# -*- coding: utf-8 -*-
"""감별 시험. 이 작업을 전혀 모르는 새 AI에게 쪽 그림만 보여주고, 어느 쪽이 AI가 만든 것인지 가려내게 한다.

줄 세우기 (만드는 중에 쓰는 시험):
  python judge.py lineup --originals <원본 쪽 그림 폴더> --pages 4,5,7,10 --new <새 쪽 그림...> [--judge claude|codex] [--rounds 2] [--out judge.json]
    --pages 는 비교에 쓸 원본 쪽 번호(표지나 간지처럼 성격이 다른 쪽은 뺀다)
    원본 몇 쪽은 '원본'이라고 알려주고, 나머지 원본과 새 쪽을 섞어 이름을 가린 뒤 하나씩 판정하게 한다.
    통과 기준: 새 쪽이 AI로 지목된 비율이 원본이 AI로 지목된 비율보다 높지 않을 것.

짝 고르기 (정답이 있을 때 쓰는 시험):
  python judge.py pair --originals <폴더> --pages ... --real <진짜 쪽 그림> --ours <만든 쪽 그림> [--rounds 4] ...
    둘 중 어느 쪽이 원본인지 고르게 한다. 맞힌 비율이 절반 근처면 구별하지 못한 것이다.

감별사는 그림 파일만 있는 빈 폴더에서 실행되며, 만든 과정이나 자료는 볼 수 없다.
기본은 사람처럼 눈으로만 보는 감별이다. --forensic 을 주면 감별사가 코드로 픽셀까지 잴 수 있다(사람 눈보다 훨씬 엄격하며,
원본 PDF와 파워포인트가 그림을 그리는 방식의 차이까지 잡아낸다). 통과 기준은 눈으로 보는 감별이고, 포렌식 감별은 고칠 점을 찾는 데 쓴다.
"""
import sys, io, os, json, random, shutil, subprocess, tempfile, re, argparse, time, glob
from PIL import Image

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

LINEUP_PROMPT = """당신은 기업 발표 자료의 만듦새를 감정하는 전문가입니다.

이 폴더에는 그림 파일이 있습니다.
- {refs}: 한 회사가 실제로 만든 발표 자료의 쪽입니다. 이 회사의 양식을 익히는 데 쓰세요.
- {cands}: 판정할 후보입니다. 후보 중에는 같은 자료의 진짜 쪽도 있고, 나중에 AI가 같은 양식을 흉내 내어 만든 쪽도 있을 수 있습니다. 몇 개가 AI인지는 알려주지 않습니다. 하나도 없을 수도 있고 전부일 수도 있습니다.

모든 그림 파일을 하나씩 열어서 자세히 보세요. 내용이 무엇인지는 판정 근거가 아닙니다. 만듦새만 보세요:
글자 크기와 굵기의 단계, 줄 간격, 여백, 정렬, 색, 선 굵기, 도형 모양과 모서리, 그림과 아이콘의 품질, 빽빽함의 정도, 제목과 쪽 번호 같은 틀의 위치.
{how}

후보마다 판정하고, 아래 JSON만 출력하세요. 다른 말은 쓰지 마세요.
{{"verdicts":[{{"page":"A","verdict":"원본 또는 AI","confidence":0에서 100,"reasons":["눈에 띈 점을 구체적으로"]}}]}}
"""

PAIR_PROMPT = """당신은 기업 발표 자료의 만듦새를 감정하는 전문가입니다.

이 폴더에는 그림 파일이 있습니다.
- {refs}: 한 회사가 실제로 만든 발표 자료의 쪽입니다. 이 회사의 양식을 익히는 데 쓰세요.
- 후보_X.jpg, 후보_Y.jpg: 같은 내용을 담은 두 쪽입니다. 하나는 그 회사가 만든 진짜 쪽이고, 다른 하나는 AI가 같은 양식을 흉내 내어 만든 쪽입니다.

모든 그림 파일을 하나씩 열어서 자세히 보세요. 어느 쪽이 그 회사가 만든 진짜인지 고르세요.
{how}
아래 JSON만 출력하세요. 다른 말은 쓰지 마세요.
{{"original":"X 또는 Y","confidence":0에서 100,"reasons":["판단 근거를 구체적으로"],"tells_in_fake":["AI가 만든 쪽에서 티가 난 부분"]}}
"""


HOW_EYE = "발표 자료를 화면으로 넘겨 보는 사람처럼 눈으로만 판단하세요. 코드를 실행하거나 픽셀 값, 파일 크기를 재지 마세요."
HOW_FORENSIC = "눈으로 보는 것에 더해, 필요하면 코드를 실행해 위치와 색을 픽셀 단위로 재도 됩니다."


def save_norm(src, dst, width=1600):
    im = Image.open(src).convert("RGB")
    h = int(im.height * width / im.width)
    im.resize((width, h), Image.LANCZOS).save(dst, quality=92)


COST = {"usd": 0.0, "calls": 0}


def ask(judge, workdir, prompt, files, model=None, timeout=900, forensic=False):
    t0 = time.time()
    # 감별 모델을 따로 정하고 싶으면 환경 변수로 준다 (claude: DECK_JUDGE_MODEL, codex: DECK_JUDGE_MODEL_CODEX)
    model = model or os.environ.get("DECK_JUDGE_MODEL_CODEX" if judge == "codex" else "DECK_JUDGE_MODEL") or None
    COST["calls"] += 1
    if shutil.which(judge) is None:
        print(f"감별사 '{judge}' 명령이 이 컴퓨터에 없다. 다른 감별사로 하거나, 절차서의 '명령줄 감별사가 없을 때'를 따른다.")
        sys.exit(3)
    if judge == "codex":
        exe = shutil.which("codex")
        out = os.path.join(workdir, "_answer.txt")
        # 사용자 설정의 추론 강도가 이 모델에서 안 받는 값일 수 있어, 이번 실행에만 값을 정해 준다 (설정 파일은 건드리지 않는다)
        cmd = [exe, "exec", "--skip-git-repo-check", "-s", "read-only", "-m", model or "gpt-5.5", "-c", 'model_reasoning_effort="high"', "-C", workdir, "-o", out]
        for f in files:
            cmd += ["-i", os.path.join(workdir, f)]
        cmd += ["-"]
        r = subprocess.run(cmd, input=prompt.encode("utf-8"), capture_output=True, timeout=timeout, shell=False, cwd=workdir)
        txt = open(out, encoding="utf-8").read() if os.path.exists(out) else (r.stdout + r.stderr).decode("utf-8", "replace")
        if os.path.exists(out):
            os.remove(out)
    else:
        exe = shutil.which("claude")
        cmd = [exe, "-p", "--permission-mode", "bypassPermissions", "--output-format", "json"]
        if model:
            cmd += ["--model", model]
        if not forensic:
            cmd += ["--tools", "Read"]  # 그림을 여는 도구만 준다
        r = subprocess.run(cmd, input=prompt.encode("utf-8"), capture_output=True, timeout=timeout, cwd=workdir)
        raw = r.stdout.decode("utf-8", "replace")
        try:
            jr = json.loads(raw)
            txt = jr.get("result", "")
            COST["usd"] += jr.get("total_cost_usd") or 0
        except Exception:
            txt = raw + r.stderr.decode("utf-8", "replace")
    return txt, time.time() - t0


def parse_json(txt, key):
    best = None
    for m in re.finditer(r"\{", txt):
        depth = 0
        for j in range(m.start(), len(txt)):
            if txt[j] == "{":
                depth += 1
            elif txt[j] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        o = json.loads(txt[m.start():j + 1])
                        if key in o:
                            return o
                        best = best or o
                    except Exception:
                        pass
                    break
    return best


def pick_originals(folder, pages):
    files = sorted(glob.glob(os.path.join(folder, "*.png")))
    if pages:
        want = {int(p) for p in pages.split(",")}
        files = [f for f in files if int(re.findall(r"(\d+)", os.path.basename(f))[-1]) in want]
    return files


DECK_PROMPT = """당신은 기업 발표 자료의 만듦새를 감정하는 전문가입니다.

이 폴더의 그림 {n}장(쪽_01.jpg 부터 쪽_{n:02d}.jpg)은 한 회사의 발표 자료를 순서대로 담은 것입니다. 첨부로 함께 주어졌을 수도 있습니다.
이 가운데 정확히 {k}쪽은 그 회사가 만든 것이 아니라, 나중에 AI가 같은 양식을 흉내 내어 새로 만들어 끼워 넣은 쪽입니다.
모든 그림 파일을 하나씩 열어서 자세히 보고, AI가 만든 {k}쪽을 고르세요.
{how}

아래 JSON만 출력하세요. 다른 말은 쓰지 마세요.
{{"ai_pages":[쪽 번호 {k}개],"reasons":{{"쪽 번호":"그렇게 본 이유"}}}}
"""


def run_deck(a, rnd):
    """끼워 넣기 시험: 원본 전체에 새 쪽을 끼워 넣어 통째로 보여주고, 새 쪽을 찾게 한다."""
    origs = sorted(glob.glob(os.path.join(a.originals, "*.png")))
    k = len(a.new)
    n = len(origs) + k
    if a.at:
        at = [int(x) for x in a.at.split(",")]
    else:
        at = sorted(rnd.sample(range(4, n), k))
    seq, oi, ni = [], 0, 0
    for pos in range(1, n + 1):
        if pos in at and ni < k:
            seq.append((a.new[at.index(pos)], "AI"))
            ni += 1
        else:
            seq.append((origs[oi], "원본"))
            oi += 1
    result = {"mode": "deck", "judge": a.judge, "forensic": a.forensic, "at": at, "rounds": []}
    found = {p: 0 for p in at}
    if a.pack:
        # 명령줄 감별사가 없을 때: 시험지만 만들어 두고, 이 작업을 모르는 하위 에이전트에게 풀게 한다
        os.makedirs(a.pack, exist_ok=True)
        for i, (f, _) in enumerate(seq):
            save_norm(f, os.path.join(a.pack, f"쪽_{i + 1:02d}.jpg"))
        open(os.path.join(a.pack, "문제.txt"), "w", encoding="utf-8").write(DECK_PROMPT.format(n=n, k=k, how=HOW_EYE))
        result["pack"] = True
        json.dump(result, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"시험지를 만들었다: {a.pack} (그림 {n}장, 문제.txt). 정답은 {a.out} 에 있다. 감별하는 쪽에는 정답 파일을 보여주지 않는다.")
        print(f"하위 에이전트에게 이렇게만 시킨다: '{a.pack} 폴더의 문제.txt를 읽고 그대로 해 줘. 그 폴더 밖의 파일은 열지 마.'")
        print(f"답을 받으면: python judge.py score --originals . --out {a.out} --picks <고른 쪽 번호들 쉼표로>")
        return
    for rno in range(1, a.rounds + 1):
        wd = tempfile.mkdtemp(prefix="deck_")
        names = []
        for i, (f, _) in enumerate(seq):
            nm = f"쪽_{i + 1:02d}.jpg"
            save_norm(f, os.path.join(wd, nm))
            names.append(nm)
        prompt = DECK_PROMPT.format(n=n, k=k, how=HOW_FORENSIC if a.forensic else HOW_EYE)
        txt, sec = ask(a.judge, wd, prompt, names, a.model, timeout=1500, forensic=a.forensic)
        shutil.rmtree(wd, ignore_errors=True)
        o = parse_json(txt, "ai_pages") or {}
        picks = []
        for v in o.get("ai_pages", []):
            m = re.findall(r"\d+", str(v))
            if m:
                picks.append(int(m[0]))
        hits = sorted(set(picks) & set(at))
        for h in hits:
            found[h] += 1
        reasons = {str(kk): vv for kk, vv in (o.get("reasons") or {}).items()}
        result["rounds"].append({"round": rno, "seconds": round(sec), "picks": picks, "hits": hits, "reasons": reasons, "raw": "" if picks else txt[-1500:]})
        print(f"{rno}회: 감별사가 고른 쪽 {picks} → 그 가운데 새 쪽 {hits} ({len(hits)}/{k})")
        for p in picks:
            tag = "새 쪽" if p in at else "원본인데 지목됨"
            why = reasons.get(str(p)) or reasons.get(f"{p:02d}") or ""
            print(f"     {p}쪽 ({tag}): {str(why)[:260]}")
        if not picks:
            print("     감별사의 답을 읽지 못했다. raw 확인")
    body = max(1, n - 5)
    result["summary"] = {"회차": a.rounds, "새 쪽별 찾아진 횟수": {str(p): c for p, c in found.items()}, "찍었을 때 한 쪽이 찾아질 확률(어림)": round(k / body, 2)}
    print("새 쪽별 찾아진 횟수:", {f"{p}쪽": f"{c}/{a.rounds}" for p, c in found.items()}, "| 찍어도 찾아질 확률 어림", round(k / body, 2))
    result["cost_usd"] = round(COST["usd"], 4); result["calls"] = COST["calls"]
    json.dump(result, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["lineup", "pair", "deck", "score"])
    ap.add_argument("--pack", default=None, help="deck: 감별사를 부르지 않고 시험지(그림과 문제.txt)만 이 폴더에 만든다")
    ap.add_argument("--picks", default="", help="score: 감별한 쪽이 고른 쪽 번호들")
    ap.add_argument("--at", default="", help="deck: 새 쪽을 끼워 넣을 자리(끼워 넣은 뒤의 쪽 번호). 예: 3,5")
    ap.add_argument("--originals", required=True)
    ap.add_argument("--pages", default="")
    ap.add_argument("--new", nargs="*", default=[])
    ap.add_argument("--real")
    ap.add_argument("--ours")
    ap.add_argument("--judge", default="claude")
    ap.add_argument("--model", default=None)
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--refs", type=int, default=5)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--out", default="judge.json")
    ap.add_argument("--keep", default=None, help="시험지 그림을 남길 폴더")
    ap.add_argument("--forensic", action="store_true", help="감별사가 코드로 픽셀까지 재는 것을 허용 (사람 눈보다 훨씬 엄격)")
    a = ap.parse_args()
    rnd = random.Random(a.seed)
    if a.mode == "deck":
        run_deck(a, rnd)
        return
    if a.mode == "score":
        res = json.load(open(a.out, encoding="utf-8"))
        picks = [int(x) for x in re.findall(r"\d+", a.picks)]
        hits = sorted(set(picks) & set(res["at"]))
        res["rounds"].append({"round": len(res["rounds"]) + 1, "picks": picks, "hits": hits})
        json.dump(res, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"감별한 쪽이 고른 쪽 {picks} → 그 가운데 새 쪽 {hits} ({len(hits)}/{len(res['at'])}). 새 쪽 자리는 {res['at']}")
        return
    origs = pick_originals(a.originals, a.pages)
    if len(origs) < 3:
        print("원본 쪽이 너무 적다")
        sys.exit(1)
    result = {"mode": a.mode, "judge": a.judge, "model": a.model, "forensic": a.forensic, "rounds": []}

    for rno in range(1, a.rounds + 1):
        wd = tempfile.mkdtemp(prefix="lineup_")
        pool = origs[:]
        rnd.shuffle(pool)
        if a.mode == "lineup":
            nd = max(1, min(len(a.new), len(pool) - 2))
            decoys = pool[:nd]
            refs = pool[nd:nd + a.refs]
            cands = [(f, "원본") for f in decoys] + [(f, "AI") for f in a.new]
            rnd.shuffle(cands)
            names = []
            for i, f in enumerate(refs):
                save_norm(f, os.path.join(wd, f"원본_{i + 1}.jpg"))
            keymap = {}
            for i, (f, truth) in enumerate(cands):
                lab = chr(ord("A") + i)
                save_norm(f, os.path.join(wd, f"후보_{lab}.jpg"))
                keymap[lab] = {"file": os.path.basename(f), "truth": truth}
                names.append(f"후보_{lab}.jpg")
            refnames = [f"원본_{i + 1}.jpg" for i in range(len(refs))]
            prompt = LINEUP_PROMPT.format(refs=", ".join(refnames), cands=", ".join(names), how=HOW_FORENSIC if a.forensic else HOW_EYE)
            txt, sec = ask(a.judge, wd, prompt, refnames + names, a.model, forensic=a.forensic)
            o = parse_json(txt, "verdicts") or {}
            rows = []
            for v in o.get("verdicts", []):
                lab = str(v.get("page", "")).strip().replace("후보_", "").replace(".jpg", "")[:1].upper()
                if lab in keymap:
                    said = "AI" if "AI" in str(v.get("verdict", "")).upper() else "원본"
                    rows.append({"label": lab, "file": keymap[lab]["file"], "truth": keymap[lab]["truth"], "said": said,
                                 "confidence": v.get("confidence"), "reasons": v.get("reasons", [])})
            result["rounds"].append({"round": rno, "seconds": round(sec), "refs": [os.path.basename(f) for f in refs], "rows": rows,
                                     "raw": txt if not rows else ""})
        else:
            refs = [f for f in pool if os.path.abspath(f) != os.path.abspath(a.real)][:a.refs]
            for i, f in enumerate(refs):
                save_norm(f, os.path.join(wd, f"원본_{i + 1}.jpg"))
            real_is = rnd.choice(["X", "Y"])
            save_norm(a.real, os.path.join(wd, f"후보_{real_is}.jpg"))
            save_norm(a.ours, os.path.join(wd, f"후보_{'Y' if real_is == 'X' else 'X'}.jpg"))
            refnames = [f"원본_{i + 1}.jpg" for i in range(len(refs))]
            prompt = PAIR_PROMPT.format(refs=", ".join(refnames), how=HOW_FORENSIC if a.forensic else HOW_EYE)
            txt, sec = ask(a.judge, wd, prompt, refnames + ["후보_X.jpg", "후보_Y.jpg"], a.model, forensic=a.forensic)
            o = parse_json(txt, "original") or {}
            said = str(o.get("original", "")).strip().upper()[:1]
            result["rounds"].append({"round": rno, "seconds": round(sec), "real_is": real_is, "said": said, "correct": said == real_is,
                                     "confidence": o.get("confidence"), "reasons": o.get("reasons", []), "tells_in_fake": o.get("tells_in_fake", []),
                                     "raw": txt if said not in ("X", "Y") else ""})
        if a.keep:
            dst = os.path.join(a.keep, f"round{rno}")
            shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(wd, dst)
        shutil.rmtree(wd, ignore_errors=True)

    if a.mode == "lineup":
        rows = [r for rd in result["rounds"] for r in rd["rows"]]
        new = [r for r in rows if r["truth"] == "AI"]
        org = [r for r in rows if r["truth"] == "원본"]
        nf = sum(1 for r in new if r["said"] == "AI")
        of = sum(1 for r in org if r["said"] == "AI")
        result["summary"] = {"새 쪽 판정 수": len(new), "새 쪽이 AI로 지목됨": nf, "원본 판정 수": len(org), "원본이 AI로 지목됨": of,
                             "통과": bool(new) and (nf / max(1, len(new)) <= of / max(1, len(org)))}
        print(f"새 쪽 {len(new)}번 중 {nf}번 AI로 지목, 원본 {len(org)}번 중 {of}번 AI로 지목 → {'통과' if result['summary']['통과'] else '미통과'}")
        per = {}
        for r in new:
            per.setdefault(r["file"], []).append(r)
        for f, rs in per.items():
            print(f"  {f}: AI로 지목 {sum(1 for r in rs if r['said'] == 'AI')}/{len(rs)}")
            for r in rs:
                if r["said"] == "AI":
                    for why in r["reasons"][:6]:
                        print(f"     - ({r['confidence']}) {why}")
        if not rows:
            print("감별사의 답을 읽지 못했다. judge.json의 raw를 확인")
    else:
        ok = sum(1 for r in result["rounds"] if r["correct"])
        n = len(result["rounds"])
        result["summary"] = {"시험 수": n, "진짜를 맞힘": ok}
        print(f"{n}번 중 {ok}번 진짜를 맞힘 (절반 근처면 구별하지 못한 것)")
        for r in result["rounds"]:
            print(f"  {r['round']}회: 진짜는 {r['real_is']}, 답 {r['said']} ({r['confidence']}) {'맞힘' if r['correct'] else '틀림'}")
            for why in (r.get("tells_in_fake") or [])[:5]:
                print(f"     - {why}")
    result["cost_usd"] = round(COST["usd"], 4); result["calls"] = COST["calls"]
    json.dump(result, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


main()

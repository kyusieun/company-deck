// lib.js — pptxgenjs 위에 얹은 얇은 도우미.
// 좌표와 크기는 모두 pt (원본 PDF를 잰 값과 같은 단위, 왼쪽 위가 0,0). 글자 크기도 pt.
// 그린 것을 순서대로 manifest에 적어 두고, 검사기(check.py)가 그것을 읽어 넘침·가림·정렬을 확인한다.
//
//   const L = require("<tools 경로>/lib.js");
//   const deck = L.newDeck({ widthPt: 960, heightPt: 540, title: "...", font: "맑은 고딕" });
//   const s = deck.slide({ bg: "FFFFFF", name: "새 장표 1" });
//   s.rect(0, 0, 100, 50, { fill: "006DFF", role: "title_mark", chrome: true });
//   s.text("제목", 80, 10, 600, 40, { size: 28, bold: true, role: "title", chrome: true });
//   await deck.save("결과/새장표.pptx");   // 옆에 새장표.manifest.json 도 쓴다. 둥근 점선이 필요하면 save(파일, { roundDots: true })
//
// 양식을 읽어 쓰는 법 (권장):
//   deck.useStyle("작업/양식");                       // calib.json(글자 위치 보정)과 frame.json(틀)을 읽는다
//   s.frame({ title: "제목", pageNo: 7 });            // 틀을 원본과 같은 자리에 그린다
//   s.textAt("글", x, 기준선y, { font: "MalgunGothicBold", size: 14, color: "000000", align: "left" });   // 한 줄
//   s.paraAt(["첫 줄", "둘째 줄"], x, 첫줄기준선y, 줄간격, 너비, { font: "MalgunGothic", size: 12 });        // 여러 줄 (글 상자 하나)
//   x, 기준선, 줄 간격은 dump/pNN.txt 에 적힌 "시작", "기준선" 값을 그대로 쓴다. 글 상자 자리는 알아서 계산된다.
// 글자 상자 규칙: 안쪽 여백 0, 세로 가운데 맞춤이 기본. 한 줄짜리는 multi를 주지 않는다(줄이 넘어가면 검사에서 걸린다).
const path = require("path");
const fs = require("fs");
const pptxgen = require(path.join(__dirname, "node_modules", "pptxgenjs"));

function newDeck({ widthPt, heightPt, title, font }) {
  const pres = new pptxgen();
  pres.defineLayout({ name: "REF", width: widthPt / 72, height: heightPt / 72 });
  pres.layout = "REF";
  if (title) pres.title = title;
  const FONT = font || "맑은 고딕";
  const man = { W: widthPt, H: heightPt, slides: [], texts: [], shapes: [], images: [], tables: [], charts: [], missing: [] };
  let cur = 0, ord = 0;
  const I = (v) => +(v / 72).toFixed(6);
  let CAL = null, FRAME = null, STYLE_DIR = null;
  // 미세 보정: make.py가 그린 결과를 다시 재서 적어 둔 값. 섞인 글꼴이나 여러 줄 글에서 남는 0.1~0.7pt 차이를 없앤다.
  let NUDGE = {};
  const nudgeFile = process.env.DECK_NUDGE || path.join(process.cwd(), "작업", "nudge.json");
  if (fs.existsSync(nudgeFile)) { try { NUDGE = JSON.parse(fs.readFileSync(nudgeFile, "utf8")); } catch (e) { NUDGE = {}; } }
  const nkey = (slide, str, x, base) => `${slide}|${plainOf(str).replace(/\s+/g, "").slice(0, 40)}|${Math.round(x * 10) / 10}|${Math.round(base * 10) / 10}`;

  // calib.json(글자 위치 보정값)을 읽는다. 읽고 나면 textAt, paraAt 이 원본에서 잰 기준선 자리에 글자를 놓는다.
  function useCalib(file) { CAL = JSON.parse(fs.readFileSync(file, "utf8")); return CAL; }
  // 양식 측정 폴더를 통째로 읽는다: calib.json 과 frame.json(틀)
  function useStyle(dir) {
    STYLE_DIR = dir;
    const c = path.join(dir, "calib.json"), f = path.join(dir, "frame.json");
    if (fs.existsSync(c)) useCalib(c);
    if (fs.existsSync(f)) FRAME = JSON.parse(fs.readFileSync(f, "utf8"));
    return { calib: CAL, frame: FRAME };
  }
  // 글꼴 이름(PDF에 적힌 이름 또는 설치된 글꼴 이름)과 크기로 보정값을 찾는다
  function cal(o) {
    const size = o.size || 12;
    let face = o.font || FONT, bold = !!o.bold, key = null;
    if (CAL && CAL.fonts[o.font] && CAL.fonts[o.font].ok) {
      key = o.font; face = CAL.fonts[key].face;
      if (o.bold === undefined) bold = !!CAL.fonts[key].bold;
    } else if (CAL) {
      for (const [k, v] of Object.entries(CAL.fonts)) if (v.ok && v.face.toLowerCase() === String(face).toLowerCase() && !!v.bold === bold) key = k;
    }
    const sk = String(Math.round(size * 2) / 2);
    const c = CAL && key ? CAL.combos[`${key}|${sk}`] : null;
    let dy = 0.36 * size, dx = 0, cs = 0, known = false;
    if (c) { dy = c.dy; dx = c.dx; cs = c.cs; known = true; }
    else if (CAL && key && CAL.per_font && CAL.per_font[key]) { dy = CAL.per_font[key].dy_per_pt * size; known = true; }
    let para = CAL && key ? CAL.para[`${key}|${sk}`] : null;
    if (!para && CAL && key) {
      // 같은 글꼴의 가장 가까운 크기 것을 크기 비례로 쓴다
      let best = null;
      for (const [k, v] of Object.entries(CAL.para)) {
        const [f, s] = k.split("|");
        if (f === key && (!best || Math.abs(+s - size) < Math.abs(best.s - size))) best = { s: +s, v };
      }
      if (best) para = { p: best.v.p, q: best.v.q * (size / best.s) };
    }
    return { face, bold, dy, dx, cs, para, known };
  }
  const plainOf = (str) => (typeof str === "string" ? str : str.map((r) => r.text).join(""));
  const estW = (str, size) => {
    let n = 0;
    for (const ch of plainOf(str)) n += ch.charCodeAt(0) >= 0x1100 ? 1 : 0.62; // 한글과 한자는 넓게, 영문과 숫자는 좁게 잡는다
    return Math.ceil((n * size * 1.05 + 24) / 10) * 10;
  };

  function slide(opt = {}) {
    const s = pres.addSlide();
    cur += 1;
    const no = cur;
    s.background = { color: opt.bg || "FFFFFF" };
    man.slides.push({ slide: no, name: opt.name || "", bg: opt.bg || "FFFFFF" });

    function lineOpt(o) {
      if (!o.stroke) return { type: "none" };
      const l = { color: o.stroke, width: o.sw || 0.75, dashType: o.dash || "solid" };
      if (o.strokeTransparency) l.transparency = o.strokeTransparency;
      return l;
    }
    function fillOpt(o) {
      if (!o.fill) return { type: "none" };
      const f = { color: o.fill };
      if (o.transparency) f.transparency = o.transparency; // 0~100
      return f;
    }
    function logShape(kind, x, y, w, h, o) {
      man.shapes.push({ order: ++ord, slide: no, kind, x, y, w, h, fill: o.fill || null, stroke: o.stroke || null, sw: o.stroke ? (o.sw || 0.75) : 0,
        transparency: o.transparency || 0, role: o.role || "", chrome: !!o.chrome, bleed: !!o.bleed });
    }

    const api = {
      raw: s, no, pres,

      // 글자. str은 문자열 또는 [{text, bold, color, size, font, breakLine}] 배열
      text(str, x, y, w, h, o = {}) {
        const rf = (r) => {   // 조각의 글꼴 이름이 PDF에 적힌 이름이면 설치된 글꼴 이름과 굵기로 바꾼다
          const m = CAL && r.font && CAL.fonts[r.font] && CAL.fonts[r.font].ok ? CAL.fonts[r.font] : null;
          return m ? Object.assign({}, r, { font: m.face, bold: r.bold !== undefined ? r.bold : !!m.bold }) : r;
        };
        if (typeof str !== "string") str = str.map(rf).map((r) => Object.assign({}, r, { bold: r.bold !== undefined ? r.bold : !!o.bold }));
        const boxBold = typeof str === "string" ? !!o.bold : false;   // 조각마다 굵기를 따로 적으므로 상자 굵기는 끈다
        const runs = typeof str === "string" ? null : str.map((r) => ({ text: r.text, options: Object.assign({},
          r.bold !== undefined ? { bold: r.bold } : {}, r.color ? { color: r.color } : {}, r.size ? { fontSize: r.size } : {},
          r.font ? { fontFace: r.font } : {}, r.italic ? { italic: true } : {}, r.breakLine ? { breakLine: true } : {},
          r.superscript ? { superscript: true } : {}) }));
        const plain = typeof str === "string" ? str : str.map((r) => r.text + (r.breakLine ? "\n" : "")).join("");
        man.texts.push({ order: ++ord, slide: no, str: plain, x, y, w, h, size: o.size || 12, font: o.font || FONT, color: o.color || "000000",
          bold: !!o.bold, align: o.align || "left", valign: o.valign || "middle", multi: !!o.multi, role: o.role || "", chrome: !!o.chrome,
          source: o.source || "", want: o._want || null });
        const opt = { x: I(x), y: I(y), w: I(w), h: I(h), fontFace: o.font || FONT, fontSize: o.size || 12, color: o.color || "000000", bold: boxBold,
          italic: !!o.italic, align: o.align || "left", valign: o.valign || "middle", margin: 0, isTextBox: true, fit: "none" };
        if (o.lineSpacingMultiple) opt.lineSpacingMultiple = o.lineSpacingMultiple;
        if (o.lineSpacing) opt.lineSpacing = o.lineSpacing; // 줄 간격을 pt로 고정
        if (o.charSpacing) opt.charSpacing = o.charSpacing;
        if (o.paraSpaceAfter) opt.paraSpaceAfter = o.paraSpaceAfter;
        if (o.paraSpaceBefore) opt.paraSpaceBefore = o.paraSpaceBefore;
        if (o.rotate) opt.rotate = o.rotate;
        if (o.transparency) opt.transparency = o.transparency; // 글자 투명도 0~100
        if (o.wrap === false) opt.wrap = false;
        s.addText(runs || str, Object.assign(opt, o.extra || {}));
      },

      // 한 줄 글자를 원본에서 잰 자리에 놓는다. base: 기준선 y. x: 왼쪽 맞춤이면 시작점, 가운데 맞춤이면 가운데, 오른쪽 맞춤이면 오른쪽 끝.
      // o.font 에는 PDF에 적힌 글꼴 이름(예: dump의 글꼴 이름)을 그대로 써도 된다. 굵기는 그 이름에서 따라온다.
      textAt(str, x, base, o = {}) {
        const c = cal(o), size = o.size || 12, align = o.align || "left";
        const w = o.w || estW(str, size), h = o.h || Math.ceil(size * 2);
        const bx = align === "center" ? x - w / 2 : align === "right" ? x - w : x - c.dx;
        const k = nkey(no, str, x, base), nd = NUDGE[k] || { dx: 0, dy: 0 };
        const oo = Object.assign({}, o, { font: c.face, bold: c.bold, size, align, valign: "middle", wrap: false, _want: { key: k, x, base, align, line: plainOf(str) } });
        if (o.charSpacing === undefined && c.cs) oo.charSpacing = c.cs;
        api.text(str, bx + nd.dx, base - c.dy - h / 2 + nd.dy, w, h, oo);
      },

      // 여러 줄 글. lines: 줄마다 문자열 또는 [{text,bold,color,...}] 배열. base: 첫 줄 기준선, pitch: 줄 간격(pt, 기준선에서 기준선), w: 글 상자 너비
      // 글 상자 하나로 만들어지므로 파워포인트에서 문단째 고칠 수 있다.
      paraAt(lines, x, base, pitch, w, o = {}) {
        const c = cal(o), size = o.size || 12, align = o.align || "left";
        const pq = c.para || { p: 0.8, q: 0.05 * size };
        const runs = [];
        lines.forEach((ln, i) => {
          const rs = typeof ln === "string" ? [{ text: ln }] : ln.map((r) => Object.assign({}, r));
          if (i < lines.length - 1) rs[rs.length - 1].breakLine = true;
          runs.push(...rs);
        });
        const h = o.h || pitch * lines.length + size * 0.6;
        const bx = align === "center" ? x - w / 2 : align === "right" ? x - w : x;
        const first = typeof lines[0] === "string" ? lines[0] : lines[0].map((r) => r.text).join("");
        const k = nkey(no, first, x, base), nd = NUDGE[k] || { dx: 0, dy: 0 };
        const oo = Object.assign({}, o, { font: c.face, bold: c.bold, size, align, valign: "top", lineSpacing: pitch, multi: true, _want: { key: k, x, base, align, line: first } });
        if (o.charSpacing === undefined && c.cs) oo.charSpacing = c.cs;
        api.text(runs, bx + nd.dx, base - (pq.p * pitch + pq.q) + nd.dy, w, h, oo);
      },

      // 틀을 그린다: 되풀이되는 도형과 그림, 제목, 쪽 번호. frame.json(style.py가 만든 것)을 읽어서 원본과 같은 자리에 놓는다.
      //   s.frame({ title: "제목", pageNo: 7 })
      //   title 은 문자열 또는 [{text,bold,font,size,color}] 배열. titleStyle: {font,size,base,color} 로 다른 꼴을 고를 수 있다(양식요약의 '다른 꼴').
      //   pageNo 는 숫자나 문자열. 숫자를 주면 원본의 쪽 번호 모양(예: "- 4 -")에 맞춘다.
      frame(o = {}) {
        if (!FRAME) throw new Error("틀을 모른다. 먼저 deck.useStyle(<양식 측정 폴더>)를 부른다.");
        for (const it of FRAME.static) {
          const c = { chrome: true, role: "frame" };
          if (it.draw === "rect") api.rect(it.x, it.y, it.w, it.h, Object.assign(c, { fill: it.fill, stroke: it.stroke, sw: it.sw }));
          else if (it.draw === "line") api.line(it.x, it.y, it.x + it.w, it.y + it.h, Object.assign(c, { color: it.stroke, width: it.sw }));
          else if (it.draw === "image" || it.draw === "crop") {
            const sw = o.swap && o.swap[it.name];
            if (!sw) { api.image(path.join(STYLE_DIR, it.file), it.x, it.y, it.w, it.h, c); continue; }
            // 바꿔 넣는 그림: 원래 상자 안에 비율을 지켜 넣고, 상자가 있던 쪽 가장자리에 붙인다
            let w = it.w, h = it.h, x = it.x, y = it.y;
            try {
              const b = fs.readFileSync(sw);
              const pw = b.readUInt32BE(16), ph = b.readUInt32BE(20);
              const r = Math.min(it.w / pw, it.h / ph);
              w = pw * r; h = ph * r;
              x = it.x + it.w / 2 > FRAME.W / 2 ? it.x + it.w - w : it.x;
              y = it.y + (it.h - h) / 2;
            } catch (e) { /* 크기를 못 읽으면 원래 상자에 그대로 넣는다 */ }
            api.image(sw, x, y, w, h, c);
          }
          else if (it.draw === "text") api.textAt(it.t, it.x, it.base, Object.assign(c, { font: it.font, size: it.size, color: it.color }));
        }
        for (const v of FRAME.text) {
          const val = v.role === "title" ? o.title : v.role === "pageno" ? o.pageNo : (o[v.role]);
          if (val === undefined || val === null) continue;
          // titleStyle: 양식요약의 '다른 꼴' 가운데 하나를 고를 때 { font, size, base, x } 를 넘긴다
          const st = Object.assign({}, v, v.role === "title" ? (o.titleStyle || {}) : {});
          if (!st.font || st.base === undefined) {
            throw new Error(`틀의 ${v.role} 자리는 원본에서 윤곽선 글자라 글꼴을 모른다. python peek.py fit-frame <양식 측정 폴더> ${v.role} <쪽> "<그 쪽에 적힌 글>" 을 먼저 돌린다.`);
          }
          let str = val;
          if (v.role === "pageno" && typeof val === "number") {
            const smp = (v.samples && v.samples[0]) || v.pattern || "1";
            str = /\d/.test(smp) ? smp.replace(/\d+/, String(val)) : String(val);
          }
          const known = CAL && CAL.fonts[st.font] && CAL.fonts[st.font].ok;   // PDF에 적힌 이름이면 굵기는 이름에서 따라온다
          api.textAt(str, st.x, st.base, { font: st.font, bold: known ? undefined : !!st.bold, size: st.size, color: st.color, align: st.align, chrome: true, role: v.role,
            charSpacing: st.charSpacing, w: v.role === "title" ? (o.titleW || FRAME.W - st.x - 20) : undefined });
        }
      },

      rect(x, y, w, h, o = {}) {
        logShape(o.radius ? "roundrect" : "rect", x, y, w, h, o);
        const opt = { x: I(x), y: I(y), w: I(w), h: I(h), fill: fillOpt(o), line: lineOpt(o) };
        if (o.radius) opt.rectRadius = I(o.radius); // 모서리 반지름 pt
        if (o.shadow) opt.shadow = o.shadow;
        s.addShape(o.radius ? pres.shapes.ROUNDED_RECTANGLE : pres.shapes.RECTANGLE, opt);
      },

      oval(x, y, w, h, o = {}) {
        logShape("oval", x, y, w, h, o);
        s.addShape(pres.shapes.OVAL, { x: I(x), y: I(y), w: I(w), h: I(h), fill: fillOpt(o), line: lineOpt(o) });
      },

      // name: pptxgenjs 도형 이름. 예) "chevron", "homePlate"(오각형 화살표), "rightArrow", "triangle", "parallelogram" ...
      shape(name, x, y, w, h, o = {}) {
        logShape(name, x, y, w, h, o);
        const opt = { x: I(x), y: I(y), w: I(w), h: I(h), fill: fillOpt(o), line: lineOpt(o) };
        if (o.rotate) opt.rotate = o.rotate;
        if (o.flipH) opt.flipH = true;
        if (o.flipV) opt.flipV = true;
        s.addShape(name, opt);
      },

      // 직선. 두 점을 준다
      line(x1, y1, x2, y2, o = {}) {
        const x = Math.min(x1, x2), y = Math.min(y1, y2), w = Math.abs(x2 - x1), h = Math.abs(y2 - y1);
        man.shapes.push({ order: ++ord, slide: no, kind: "line", x, y, w, h, fill: null, stroke: o.color || "000000", sw: o.width || 0.75, role: o.role || "", chrome: !!o.chrome, bleed: !!o.bleed });
        const opt = { x: I(x), y: I(y), w: I(w), h: I(h), line: { color: o.color || "000000", width: o.width || 0.75, dashType: o.dash || "solid" } };
        if ((x2 - x1) * (y2 - y1) < 0) opt.flipV = true;
        if (o.endArrow) opt.line.endArrowType = o.endArrow;
        if (o.beginArrow) opt.line.beginArrowType = o.beginArrow;
        s.addShape(pres.shapes.LINE, opt);
      },

      // 꺾은선과 점. points: [[x,y], ...]
      polyline(points, o = {}) {
        for (let i = 0; i < points.length - 1; i++) api.line(points[i][0], points[i][1], points[i + 1][0], points[i + 1][1], { color: o.color, width: o.width, dash: o.dash, role: o.role || "polyline" });
        if (o.marker) points.forEach(([px, py]) => api.oval(px - o.marker / 2, py - o.marker / 2, o.marker, o.marker, { fill: o.markerFill || o.color, role: "marker" }));
      },

      // 자유 도형. segs: [{x,y,move:true}, {x,y}, {x,y,c1:[x,y],c2:[x,y]}(3차 곡선), {close:true}] 좌표는 장표 기준 pt
      freeform(segs, o = {}) {
        const xs = [], ys = [];
        segs.forEach((g) => { if (g.x !== undefined) { xs.push(g.x); ys.push(g.y); } if (g.c1) { xs.push(g.c1[0], g.c2[0]); ys.push(g.c1[1], g.c2[1]); } });
        const x0 = Math.min(...xs), y0 = Math.min(...ys), w = Math.max(...xs) - x0 || 0.01, h = Math.max(...ys) - y0 || 0.01;
        logShape("freeform", x0, y0, w, h, o);
        const pts = segs.map((g) => {
          if (g.close) return { close: true };
          const p = { x: I(g.x - x0), y: I(g.y - y0) };
          if (g.move) p.moveTo = true;
          if (g.c1) p.curve = { type: "cubic", x1: I(g.c1[0] - x0), y1: I(g.c1[1] - y0), x2: I(g.c2[0] - x0), y2: I(g.c2[1] - y0) };
          return p;
        });
        s.addShape(pres.shapes.CUSTOM_GEOMETRY, { x: I(x0), y: I(y0), w: I(w), h: I(h), fill: fillOpt(o), line: lineOpt(o), points: pts });
      },

      image(file, x, y, w, h, o = {}) {
        if (!fs.existsSync(file)) { man.missing.push(file); return; }
        man.images.push({ order: ++ord, slide: no, file, x, y, w, h, role: o.role || "", chrome: !!o.chrome, bleed: !!o.bleed });
        const opt = { path: file, x: I(x), y: I(y), w: I(w), h: I(h) };
        if (o.transparency) opt.transparency = o.transparency;
        s.addImage(opt);
      },

      // 표. rows: 줄마다 칸 배열. 칸 = {t, bold, size, color, fill, align, valign, font, colspan, rowspan, margin:[위,오른,아래,왼] pt,
      //                                border:[위,오른,아래,왼] 각각 {pt,color} 또는 null(선 없음)}
      // colW, rowH: pt 배열
      table(rows, x, y, colW, rowH, o = {}) {
        const defB = o.border || { pt: 0.5, color: "BFBFBF" };
        const bd = (b) => (b === null ? { type: "none" } : { type: "solid", pt: (b || defB).pt, color: (b || defB).color });
        const out = [];
        const occupied = rows.map(() => []);
        rows.forEach((row, ri) => {
          let ci = 0;
          const r = [];
          row.forEach((c) => {
            while (occupied[ri][ci]) ci++;
            const cs = c.colspan || 1, rs = c.rowspan || 1;
            for (let a = 0; a < rs; a++) for (let b = 0; b < cs; b++) if (occupied[ri + a]) occupied[ri + a][ci + b] = true;
            const cx = x + colW.slice(0, ci).reduce((p, q) => p + q, 0), cy = y + rowH.slice(0, ri).reduce((p, q) => p + q, 0);
            const cw = colW.slice(ci, ci + cs).reduce((p, q) => p + q, 0), ch = rowH.slice(ri, ri + rs).reduce((p, q) => p + q, 0);
            const m = c.margin || o.margin || [0, 6, 0, 6];
            const runs = Array.isArray(c.t) ? c.t : null;
            const plain = runs ? runs.map((q) => q.text).join("") : String(c.t === undefined ? "" : c.t);
            if (plain.trim()) man.texts.push({ order: ++ord, slide: no, str: plain, x: cx + m[3], y: cy, w: cw - m[1] - m[3], h: ch, size: c.size || o.size || 12, font: c.font || o.font || FONT,
              color: c.color || "000000", bold: !!c.bold, align: c.align || "right", valign: c.valign || "middle", multi: !!c.multi, role: c.role || "cell", chrome: false, source: c.source || "" });
            if (c.fill) man.shapes.push({ order: ord, slide: no, kind: "cellfill", x: cx, y: cy, w: cw, h: ch, fill: c.fill, stroke: null, sw: 0, role: "cellfill", chrome: false });
            const B = c.border || [undefined, undefined, undefined, undefined];
            const options = { fontFace: c.font || o.font || FONT, fontSize: c.size || o.size || 12, color: c.color || "000000", bold: !!c.bold, align: c.align || "right",
              valign: c.valign || "middle", margin: m.map((v) => +(v / 72).toFixed(4)), border: [bd(B[0]), bd(B[1]), bd(B[2]), bd(B[3])] };
            if (c.fill) options.fill = { color: c.fill };
            if (cs > 1) options.colspan = cs;
            if (rs > 1) options.rowspan = rs;
            r.push({ text: runs ? runs.map((q) => ({ text: q.text, options: Object.assign({}, q.bold !== undefined ? { bold: q.bold } : {}, q.color ? { color: q.color } : {}, q.size ? { fontSize: q.size } : {}, q.superscript ? { superscript: true } : {}) })) : plain, options });
            ci += cs;
          });
          out.push(r);
        });
        const tw = colW.reduce((p, q) => p + q, 0), th = rowH.reduce((p, q) => p + q, 0);
        man.tables.push({ order: ++ord, slide: no, x, y, w: tw, h: th, colW, rowH, role: o.role || "table" });
        s.addTable(out, { x: I(x), y: I(y), w: I(tw), colW: colW.map(I), rowH: rowH.map(I) });
      },

      // 세로 막대 차트(파워포인트에서 고칠 수 있는 진짜 차트). 막대 위치를 미리 계산할 수 있게 그림 영역을 고정한다.
      //   x0: 첫 막대 왼쪽, pitch: 막대 사이 간격(왼쪽에서 왼쪽), barW: 막대 너비, baseY: 바닥선 y, maxH: 가장 큰 값의 막대 높이
      //   돌려주는 값: 막대마다 {x, y, w, h, value} — 값 표시나 축 이름을 그 위치에 맞춰 text()로 얹는다
      barChart({ x0, pitch, barW, baseY, maxH, values, labels, colors, vmax, name }) {
        const top = baseY - maxH, frameX = x0 - (pitch - barW) / 2, frameW = pitch * values.length;
        const vm = vmax || Math.max(...values);
        const hh = maxH * (vm / Math.max(...values));
        s.addChart(pres.charts.BAR, [{ name: name || "값", labels: labels || values.map((_, i) => String(i + 1)), values }], {
          x: I(frameX), y: I(baseY - hh), w: I(frameW), h: I(hh), barDir: "col", barGapWidthPct: Math.round(((pitch - barW) / barW) * 100),
          chartColors: colors, showLegend: false, showTitle: false, showValue: false, catAxisHidden: true, valAxisHidden: true,
          valGridLine: { style: "none" }, catGridLine: { style: "none" }, valAxisMinVal: 0, valAxisMaxVal: vm, layout: { x: 0, y: 0, w: 1, h: 1 },
        });
        man.charts.push({ order: ++ord, slide: no, x: frameX, y: top, w: frameW, h: maxH });
        return values.map((v, i) => {
          const h = (v / Math.max(...values)) * maxH, bx = x0 + pitch * i;
          man.shapes.push({ order: ord, slide: no, kind: "bar", x: bx, y: baseY - h, w: barW, h, fill: colors[i % colors.length], stroke: null, sw: 0, role: "bar", chrome: false });
          return { x: bx, y: baseY - h, w: barW, h, value: v };
        });
      },
    };
    return api;
  }

  // opt.roundDots: true 이면 점선(dash: "sysDot")의 점을 둥글게 만든다. pptxgenjs가 선 끝 모양을 못 정해서 저장한 뒤 XML을 고친다.
  async function save(file, opt = {}) {
    fs.mkdirSync(path.dirname(path.resolve(file)), { recursive: true });
    await pres.writeFile({ fileName: file });
    // 한글 글꼴과 영문·숫자 글꼴의 짝: 원본이 영문과 숫자를 다른 글꼴로 찍으면 같은 글 상자 안에서 그대로 따른다
    const LF = (FRAME && FRAME.latin_for) || {};
    if (Object.keys(LF).length && opt.latinPair !== false) {
      const JSZip = require(path.join(__dirname, "node_modules", "jszip"));
      const zip = await JSZip.loadAsync(fs.readFileSync(file));
      for (const name of Object.keys(zip.files)) {
        if (!/^ppt\/slides\/slide\d+\.xml$/.test(name)) continue;
        let xml = await zip.file(name).async("string");
        for (const [ea, la] of Object.entries(LF)) xml = xml.split(`<a:latin typeface="${ea}"`).join(`<a:latin typeface="${la}"`);
        zip.file(name, xml);
      }
      fs.writeFileSync(file, await zip.generateAsync({ type: "nodebuffer", compression: "DEFLATE" }));
    }
    if (opt.roundDots) {
      const JSZip = require(path.join(__dirname, "node_modules", "jszip"));
      const zip = await JSZip.loadAsync(fs.readFileSync(file));
      for (const name of Object.keys(zip.files)) {
        if (!/^ppt\/slides\/slide\d+\.xml$/.test(name)) continue;
        let xml = await zip.file(name).async("string");
        xml = xml.replace(/<a:ln( [^>]*)?>((?:(?!<\/a:ln>).)*?<a:prstDash val="sysDot"\/>)/g, (m, attrs, rest) => {
          attrs = (attrs || "").replace(/ cap="[^"]*"/, "");
          return `<a:ln${attrs} cap="rnd">${rest}`;
        });
        zip.file(name, xml);
      }
      fs.writeFileSync(file, await zip.generateAsync({ type: "nodebuffer", compression: "DEFLATE" }));
    }
    man.missing = [...new Set(man.missing)];
    const mf = file.replace(/\.pptx$/i, "") + ".manifest.json";
    fs.writeFileSync(mf, JSON.stringify(man));
    console.log(`저장 ${file} | 장표 ${cur}쪽, 글자 상자 ${man.texts.length}, 도형 ${man.shapes.length}, 그림 ${man.images.length}, 표 ${man.tables.length}, 차트 ${man.charts.length}` +
      (man.missing.length ? ` | 없는 그림 파일: ${man.missing.join(", ")}` : ""));
    return mf;
  }
  return { pres, slide, save, manifest: man, useCalib, useStyle, cal };
}

module.exports = { newDeck };

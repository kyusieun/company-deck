// calib_build.js — calib.py가 쓰는 시험 장표를 만든다. 사람이나 AI가 직접 부를 일은 없다.
//   node calib_build.js <spec.json> <out.pptx>
const path = require("path");
const fs = require("fs");
const L = require(path.join(__dirname, "lib.js"));
(async () => {
  const spec = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
  const deck = L.newDeck({ widthPt: spec.W, heightPt: spec.H, title: "calib", font: spec.font || "Malgun Gothic" });
  if (spec.calib) deck.useCalib(spec.calib);
  for (const sl of spec.slides) {
    const s = deck.slide({ name: sl.name || "" });
    for (const b of sl.items) {
      if (b.kind === "box") {
        s.text(b.t, b.x, b.y, b.w, b.h, { size: b.size, font: b.face, bold: b.bold, color: "000000", align: "left", valign: "middle", wrap: false, role: "calib" });
      } else if (b.kind === "para") {
        s.text(b.lines.map((t, i) => ({ text: t, breakLine: i < b.lines.length - 1 })), b.x, b.y, b.w, b.h,
          { size: b.size, font: b.face, bold: b.bold, color: "000000", align: "left", valign: "top", lineSpacing: b.pitch, multi: true, role: "calib" });
      } else if (b.kind === "at") {
        s.textAt(b.t, b.ox, b.base, { size: b.size, font: b.font, color: "000000", role: "calib" });
      } else if (b.kind === "paraAt") {
        s.paraAt(b.lines, b.ox, b.base, b.pitch, b.w, { size: b.size, font: b.font, color: "000000", role: "calib" });
      }
    }
  }
  await deck.save(process.argv[3]);
})();

# -*- coding: utf-8 -*-
"""설치된 글꼴이 있는 폴더 (윈도우, 맥)."""
import os, sys

if sys.platform == "darwin":
    FONT_DIRS = ["/Library/Fonts", os.path.expanduser("~/Library/Fonts"), "/System/Library/Fonts",
                 "/System/Library/Fonts/Supplemental",
                 "/Applications/Microsoft PowerPoint.app/Contents/Resources/DFonts"]  # 맥용 오피스가 함께 까는 글꼴
else:
    FONT_DIRS = [os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts"),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts")]


def find_font(fn):
    if os.path.exists(fn):
        return fn
    for d in FONT_DIRS:
        p = os.path.join(d, fn)
        if os.path.exists(p):
            return p
    return fn

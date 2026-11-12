"""Site style rule: no period at the end of a line in a box, table cell, bullet or one-sentence line.
Used by py/01_dq_outputs.py (dq.html) and run once on site/index.html."""
import re

END = re.compile(r"(?<=[\w)%\"'’”])\.(?=</(?:td|li|dd|span|div|small|b)>)")
P = re.compile(r"(<p\b[^>]*>)(.*?)(</p>)", re.S)


def nodot(html):
    html = END.sub("", html)

    def one(m):
        text = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if text.endswith(".") and ". " not in text and not text.endswith(".."):
            body = m.group(2).rstrip()
            if body.endswith("."):
                return m.group(1) + body[:-1] + m.group(3)
        return m.group(0)
    return P.sub(one, html)


if __name__ == "__main__":
    import pathlib, sys
    for f in sys.argv[1:]:
        p = pathlib.Path(f); s = p.read_text(); t = nodot(s)
        p.write_text(t); print(f, len(s) - len(t), "periods removed")

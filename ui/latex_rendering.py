"""Small, safe LaTeX-math renderer for Qt rich-text surfaces.

Qt's ``QTextDocument`` understands a useful HTML subset but does not render
LaTeX or MathML.  These helpers cover the notation commonly returned by chat
models without a browser engine, a system TeX installation, or network assets.
"""

from __future__ import annotations

import base64
import html
import re
from dataclasses import dataclass
from functools import lru_cache

import ziamath

# QtSvg implements the SVG 1.1 path subset reliably, while SVG2 ``symbol`` /
# ``use`` references can drop glyphs. Ziamath can emit equivalent standalone
# paths specifically for older renderers.
ziamath.config.svg2 = False


@dataclass(frozen=True)
class MathSpan:
    """A delimited math expression inside source text."""

    start: int
    end: int
    expression: str
    display: bool


@dataclass(frozen=True)
class RenderedLatex:
    """One fully typeset, self-contained SVG equation."""

    data_uri: str
    width: float
    height: float

    def image_html(self, *, max_width: float | None = None) -> str:
        """Return a Qt-rich-text image tag, scaling down oversized math."""
        width = self.width
        height = self.height
        if max_width and width > max_width:
            scale = max_width / width
            width *= scale
            height *= scale
        return (
            f'<img src="{self.data_uri}" width="{max(1, round(width))}" '
            f'height="{max(1, round(height))}" style="vertical-align:middle">'
        )


_SYMBOLS = {
    # Greek
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ",
    "epsilon": "ϵ", "varepsilon": "ε", "zeta": "ζ", "eta": "η",
    "theta": "θ", "vartheta": "ϑ", "iota": "ι", "kappa": "κ",
    "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "omicron": "ο",
    "pi": "π", "varpi": "ϖ", "rho": "ρ", "varrho": "ϱ",
    "sigma": "σ", "varsigma": "ς", "tau": "τ", "upsilon": "υ",
    "phi": "φ", "varphi": "ϕ", "chi": "χ", "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ",
    "Xi": "Ξ", "Pi": "Π", "Sigma": "Σ", "Upsilon": "Υ",
    "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
    # Relations and operators
    "times": "×", "cdot": "·", "div": "÷", "pm": "±", "mp": "∓",
    "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥", "ne": "≠", "neq": "≠",
    "approx": "≈", "sim": "∼", "simeq": "≃", "equiv": "≡", "propto": "∝",
    "in": "∈", "notin": "∉", "ni": "∋", "subset": "⊂", "subseteq": "⊆",
    "supset": "⊃", "supseteq": "⊇", "cup": "∪", "cap": "∩", "setminus": "∖",
    "land": "∧", "wedge": "∧", "lor": "∨", "vee": "∨", "neg": "¬",
    "forall": "∀", "exists": "∃", "nexists": "∄", "therefore": "∴", "because": "∵",
    "infty": "∞", "partial": "∂", "nabla": "∇", "ell": "ℓ", "hbar": "ℏ",
    "sum": "∑", "prod": "∏", "int": "∫", "iint": "∬", "iiint": "∭", "oint": "∮",
    "lim": "lim", "min": "min", "max": "max", "log": "log", "ln": "ln", "exp": "exp",
    "sin": "sin", "cos": "cos", "tan": "tan", "arcsin": "arcsin", "arccos": "arccos", "arctan": "arctan",
    # Arrows and punctuation
    "to": "→", "rightarrow": "→", "leftarrow": "←", "leftrightarrow": "↔",
    "Rightarrow": "⇒", "Leftarrow": "⇐", "Leftrightarrow": "⇔", "mapsto": "↦",
    "ldots": "…", "cdots": "⋯", "vdots": "⋮", "ddots": "⋱",
    "angle": "∠", "degree": "°", "prime": "′", "emptyset": "∅",
}

_SUPERSCRIPT = str.maketrans("0123456789+-=()ni", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱ")
_SUBSCRIPT = str.maketrans("0123456789+-=()aeioxhklmnpst", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑᵢₒₓₕₖₗₘₙₚₛₜ")
_MATRIX_RE = re.compile(
    r"^\s*\\begin\{(matrix|pmatrix|bmatrix|Bmatrix|vmatrix|Vmatrix|aligned|align\*?)\}"
    r"(.*?)\\end\{\1\}\s*$",
    re.DOTALL,
)
_CURRENCY_AMOUNT_RE = re.compile(
    r"\$(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?(?:[kKmMbB])?"
)
_INLINE_MATH_SIGNAL_RE = re.compile(
    r"\\[A-Za-z]+|[=^_<>±×÷∑∫]|(?:\d|\s)[+*/-](?:\d|\s)"
)


def _is_escaped(text: str, index: int) -> bool:
    slashes = 0
    index -= 1
    while index >= 0 and text[index] == "\\":
        slashes += 1
        index -= 1
    return bool(slashes % 2)


def _looks_like_currency_span(text: str, start: int, close: int) -> bool:
    """Return whether a single-dollar candidate starts as a money amount.

    Dollar-delimited inline math is ambiguous with ordinary currency.  A
    standalone amount such as ``$500`` must not borrow a later dollar sign as
    its closing delimiter.  Numeric equations such as ``$2 + 2 = 4$`` remain
    math because the candidate contains an explicit mathematical operator.
    """
    amount = _CURRENCY_AMOUNT_RE.match(text, start)
    if amount is None or amount.end() == close:
        return False
    if _CURRENCY_AMOUNT_RE.match(text, close) is not None:
        # In ``$500 - $300`` the second dollar starts another amount; it is not
        # a closing math delimiter even though the intervening prose contains
        # an arithmetic operator.
        return True
    expression = text[start + 1:close]
    return _INLINE_MATH_SIGNAL_RE.search(expression) is None


def iter_math_spans(text: str) -> list[MathSpan]:
    """Return complete, non-overlapping TeX math spans.

    Incomplete delimiters remain ordinary text, which is important while an
    answer is still streaming into the UI.
    """
    source = str(text or "")
    spans: list[MathSpan] = []
    i = 0
    while i < len(source):
        if source.startswith(r"\[", i) and not _is_escaped(source, i):
            close = source.find(r"\]", i + 2)
            if close >= 0:
                spans.append(MathSpan(i, close + 2, source[i + 2:close], True))
                i = close + 2
                continue
        if source.startswith(r"\(", i) and not _is_escaped(source, i):
            close = source.find(r"\)", i + 2)
            if close >= 0:
                spans.append(MathSpan(i, close + 2, source[i + 2:close], False))
                i = close + 2
                continue
        if source[i] == "$" and not _is_escaped(source, i):
            display = source.startswith("$$", i)
            width = 2 if display else 1
            if not display and (i + 1 >= len(source) or source[i + 1].isspace()):
                i += 1
                continue
            close = i + width
            matched = False
            while True:
                close = source.find("$" * width, close)
                if close < 0:
                    break
                if _is_escaped(source, close):
                    close += width
                    continue
                if not display and "\n" in source[i + 1:close]:
                    # Inline TeX cannot span a line.  Without this boundary,
                    # currency-heavy prose (for example Calc analysis with one
                    # ``$amount`` per bullet) pairs unrelated dollar signs and
                    # turns several rows of text into one malformed equation.
                    break
                if not display and close > i + 1 and source[close - 1].isspace():
                    close += width
                    continue
                if not display and _looks_like_currency_span(source, i, close):
                    break
                spans.append(MathSpan(i, close + width, source[i + width:close], display))
                i = close + width
                matched = True
                break
            if matched:
                continue
        i += 1
    return spans


def contains_latex_math(text: str) -> bool:
    """Return whether text contains at least one complete math expression."""
    return bool(iter_math_spans(text))


def _safe_svg_color(color: str) -> str:
    """Return a conservative opaque SVG colour."""
    value = str(color or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        return value.lower()
    if re.fullmatch(r"#[0-9a-fA-F]{8}", value):
        # QColor's eight-digit form is #AARRGGBB; equations are kept opaque so
        # their fine strokes remain readable against translucent bubbles.
        return f"#{value[3:]}".lower()
    return "#e9e6e0"


@lru_cache(maxsize=256)
def render_latex_image(
    expression: str,
    *,
    size: float = 18,
    color: str = "#e9e6e0",
    inline: bool = False,
) -> RenderedLatex | None:
    """Typeset a delimiter-free expression as self-contained SVG paths."""
    source = str(expression or "").strip()
    if not source or len(source) > 12_000:
        return None
    point_size = max(8.0, min(48.0, float(size)))
    try:
        equation = ziamath.Latex(
            source,
            size=point_size,
            color=_safe_svg_color(color),
            inline=bool(inline),
            title=source[:500],
            margin=1.0,
        )
        svg = equation.svg()
        root = equation.svgxml()
        width = float(str(root.attrib.get("width", "0")).removesuffix("px"))
        height = float(str(root.attrib.get("height", "0")).removesuffix("px"))
        if width <= 0 or height <= 0:
            return None
        payload = base64.b64encode(svg.encode("utf-8")).decode("ascii")
        return RenderedLatex(f"data:image/svg+xml;base64,{payload}", width, height)
    except Exception:
        # Model output can contain incomplete or unsupported TeX while it is
        # streaming. Rendering is best-effort and must never take down the UI.
        return None


class _MathParser:
    def __init__(self, source: str, *, as_html: bool):
        self.source = source
        self.as_html = as_html
        self.pos = 0

    def parse(self, stop: str = "") -> str:
        out: list[str] = []
        while self.pos < len(self.source):
            ch = self.source[self.pos]
            if stop and ch == stop:
                self.pos += 1
                break
            if ch == "\\":
                out.append(self._command())
            elif ch == "{":
                self.pos += 1
                out.append(self.parse("}"))
            elif ch in "^_":
                self.pos += 1
                atom = self._atom()
                out.append(self._script(atom, superscript=ch == "^"))
            elif ch == "~":
                self.pos += 1
                out.append("&nbsp;" if self.as_html else " ")
            elif ch == "&":
                self.pos += 1
                out.append("&nbsp;&nbsp;" if self.as_html else "  ")
            else:
                self.pos += 1
                out.append(html.escape(ch) if self.as_html else ch)
        return "".join(out)

    def _raw_group(self, opener: str = "{", closer: str = "}") -> str:
        if self.pos >= len(self.source) or self.source[self.pos] != opener:
            return ""
        start = self.pos + 1
        depth = 1
        self.pos += 1
        while self.pos < len(self.source):
            if self.source[self.pos] == opener:
                depth += 1
            elif self.source[self.pos] == closer:
                depth -= 1
                if depth == 0:
                    value = self.source[start:self.pos]
                    self.pos += 1
                    return value
            self.pos += 1
        return self.source[start:]

    def _render_fragment(self, source: str) -> str:
        return _MathParser(source, as_html=self.as_html).parse()

    def _atom(self) -> str:
        while self.pos < len(self.source) and self.source[self.pos].isspace():
            self.pos += 1
        if self.pos >= len(self.source):
            return ""
        if self.source[self.pos] == "{":
            return self._render_fragment(self._raw_group())
        if self.source[self.pos] == "\\":
            return self._command()
        ch = self.source[self.pos]
        self.pos += 1
        return html.escape(ch) if self.as_html else ch

    def _script(self, value: str, *, superscript: bool) -> str:
        if self.as_html:
            tag = "sup" if superscript else "sub"
            return f"<{tag}>{value}</{tag}>"
        table = _SUPERSCRIPT if superscript else _SUBSCRIPT
        translated = value.translate(table)
        if all(ord(ch) > 127 or ch.isspace() for ch in translated):
            return translated
        marker = "^" if superscript else "_"
        return marker + (translated if len(translated) == 1 else f"({translated})")

    def _command(self) -> str:
        self.pos += 1
        if self.pos >= len(self.source):
            return "\\"
        if self.source[self.pos] == "\\":
            self.pos += 1
            return "<br>" if self.as_html else "\n"
        match = re.match(r"[A-Za-z]+\*?", self.source[self.pos:])
        if match:
            command = match.group(0)
            self.pos += len(command)
        else:
            command = self.source[self.pos]
            self.pos += 1

        if command in {"left", "right"}:
            return ""
        if command in {",", ";", ":", "quad", "qquad", "!", " "}:
            return "&nbsp;" if self.as_html else " "
        if command in _SYMBOLS:
            return _SYMBOLS[command]
        if command in {"frac", "dfrac", "tfrac"}:
            numerator = self._render_fragment(self._raw_group())
            denominator = self._render_fragment(self._raw_group())
            if self.as_html:
                return f'<span style="white-space:nowrap"><sup>{numerator}</sup>⁄<sub>{denominator}</sub></span>'
            return f"{self._parenthesize(numerator)}⁄{self._parenthesize(denominator)}"
        if command == "sqrt":
            degree = ""
            if self.pos < len(self.source) and self.source[self.pos] == "[":
                degree = self._render_fragment(self._raw_group("[", "]"))
            body = self._render_fragment(self._raw_group())
            if self.as_html:
                prefix = f"<sup>{degree}</sup>" if degree else ""
                return f'{prefix}√<span style="text-decoration:overline">{body}</span>'
            prefix = self._script(degree, superscript=True) if degree else ""
            return f"{prefix}√{self._parenthesize(body)}"
        if command in {"text", "textrm", "textnormal", "operatorname"}:
            raw = self._raw_group()
            return html.escape(raw) if self.as_html else raw
        if command in {"mathbf", "boldsymbol", "bm", "mathrm", "mathsf", "mathtt", "mathit", "mathcal", "mathbb"}:
            body = self._render_fragment(self._raw_group())
            if not self.as_html:
                return body
            if command in {"mathbf", "boldsymbol", "bm"}:
                return f"<b>{body}</b>"
            if command == "mathit":
                return f"<i>{body}</i>"
            if command == "mathtt":
                return f'<span style="font-family:monospace">{body}</span>'
            return body
        if command in {"overline", "bar", "underline", "vec", "hat", "tilde", "dot", "ddot"}:
            body = self._atom()
            if self.as_html:
                if command == "underline":
                    return f"<u>{body}</u>"
                if command in {"overline", "bar"}:
                    return f'<span style="text-decoration:overline">{body}</span>'
                accent = {"vec": "⃗", "hat": "̂", "tilde": "̃", "dot": "̇", "ddot": "̈"}[command]
                return body + accent
            accent = {"vec": "⃗", "hat": "̂", "tilde": "̃", "dot": "̇", "ddot": "̈"}.get(command, "̅")
            return body + accent
        if command in {"{", "}", "$", "%", "#", "_", "&"}:
            return html.escape(command) if self.as_html else command
        # Keep unknown commands legible rather than silently deleting content.
        value = f"\\{command}"
        return html.escape(value) if self.as_html else value

    @staticmethod
    def _parenthesize(value: str) -> str:
        return value if len(value) <= 1 else f"({value})"


def _split_math_rows(source: str) -> list[list[str]]:
    rows = re.split(r"(?<!\\)\\\\", source)
    return [[cell.strip() for cell in re.split(r"(?<!\\)&", row)] for row in rows]


def latex_expression_to_html(
    expression: str,
    *,
    display: bool = False,
    color: str = "#e9e6e0",
    size: float = 18,
    max_width: float | None = None,
) -> str:
    """Render one delimiter-free TeX expression to safe Qt-compatible HTML."""
    source = str(expression or "").strip()
    image = render_latex_image(
        source,
        size=size,
        color=color,
        inline=not display,
    )
    if image is not None:
        rendered_image = image.image_html(max_width=max_width)
        if display:
            return f'<div align="center" style="margin:6px 0">{rendered_image}</div>'
        return rendered_image

    # Invalid or unsupported input still gets a safe, legible fallback rather
    # than disappearing from a streamed reply.
    matrix = _MATRIX_RE.match(source)
    if matrix:
        environment, body = matrix.groups()
        rows = _split_math_rows(body)
        if environment.startswith("align") or environment == "aligned":
            rendered = "<br>".join(
                "&nbsp;&nbsp;".join(_MathParser(cell, as_html=True).parse() for cell in row)
                for row in rows
            )
        else:
            cells = "".join(
                "<tr>" + "".join(
                    f'<td style="padding:1px 7px; text-align:center">{_MathParser(cell, as_html=True).parse()}</td>'
                    for cell in row
                ) + "</tr>"
                for row in rows
            )
            brackets = {"pmatrix": ("(", ")"), "bmatrix": ("[", "]"), "Bmatrix": ("{", "}"),
                        "vmatrix": ("|", "|"), "Vmatrix": ("‖", "‖")}.get(environment, ("", ""))
            rendered = (
                f'<table cellspacing="0" cellpadding="0" style="display:inline-table"><tr>'
                f'<td style="font-size:140%">{html.escape(brackets[0])}</td><td><table>{cells}</table></td>'
                f'<td style="font-size:140%">{html.escape(brackets[1])}</td></tr></table>'
            )
    else:
        rendered = _MathParser(source, as_html=True).parse()
    style = (
        "font-family:'Cambria Math','STIX Two Math','Bitter','DejaVu Serif',"
        "'Times New Roman',serif; white-space:nowrap"
    )
    if display:
        return f'<div align="center" style="{style}; margin:6px 0">{rendered}</div>'
    return f'<span style="{style}">{rendered}</span>'


def latex_expression_to_plain(expression: str) -> str:
    """Render one delimiter-free TeX expression as compact Unicode math."""
    source = str(expression or "").strip()
    matrix = _MATRIX_RE.match(source)
    if matrix:
        _environment, body = matrix.groups()
        rows = _split_math_rows(body)
        return "[" + "; ".join(
            "  ".join(_MathParser(cell, as_html=False).parse() for cell in row)
            for row in rows
        ) + "]"
    return _MathParser(source, as_html=False).parse()


def latex_to_plain_text(text: str) -> str:
    """Replace complete math spans with readable Unicode equivalents."""
    source = str(text or "")
    spans = iter_math_spans(source)
    if not spans:
        return source
    parts: list[str] = []
    cursor = 0
    for span in spans:
        parts.append(source[cursor:span.start])
        rendered = latex_expression_to_plain(span.expression)
        if span.display and parts and parts[-1] and not parts[-1].endswith("\n"):
            parts.append("\n")
        parts.append(rendered)
        if span.display and span.end < len(source) and not source[span.end:].startswith("\n"):
            parts.append("\n")
        cursor = span.end
    parts.append(source[cursor:])
    return "".join(parts)

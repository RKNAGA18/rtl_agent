"""
sv_parser.py — Robust SystemVerilog extractor from raw LLM output.

LLMs frequently surround code with conversational text, markdown fences with
varying language tags, and trailing commentary. This module strips all of that
and returns only the synthesizable SystemVerilog.
"""

import re
from typing import Optional


# ─── Regex patterns ────────────────────────────────────────────────────────────
# Match ```systemverilog, ```verilog, ```sv, or ``` (generic fence)
_FENCE_PATTERN = re.compile(
    r"```(?:systemverilog|verilog|sv)?\s*\n(.*?)```",
    re.DOTALL | re.IGNORECASE,
)

# Fallback: match a module...endmodule block directly in the text
_MODULE_PATTERN = re.compile(
    r"(`(?:timescale|default_nettype)[^\n]*\n)*"  # optional directives before module
    r"\s*module\b.*?endmodule"                     # module body
    r"(?:\s*`default_nettype\s+\w+)?",             # optional trailing directive
    re.DOTALL | re.IGNORECASE,
)

# Detect if code block looks like SystemVerilog (must contain 'module' keyword)
_SV_SANITY = re.compile(r"\bmodule\b", re.IGNORECASE)


def extract_systemverilog(raw_text: str) -> Optional[str]:
    """
    Extract SystemVerilog source from raw LLM output.

    Tries strategies in order of preference:
    1. Fenced code block with systemverilog/verilog/sv tag
    2. Generic fenced code block (```) if it looks like SV
    3. Bare module...endmodule block in the text

    Returns
    -------
    str  — The cleaned SV code, or None if nothing could be extracted.
    """
    if not raw_text:
        return None

    # Strategy 1 & 2: fenced blocks
    matches = _FENCE_PATTERN.findall(raw_text)
    for candidate in matches:
        cleaned = candidate.strip()
        if cleaned and _SV_SANITY.search(cleaned):
            return _normalize(cleaned)

    # Strategy 3: bare module block
    m = _MODULE_PATTERN.search(raw_text)
    if m:
        cleaned = m.group(0).strip()
        if _SV_SANITY.search(cleaned):
            return _normalize(cleaned)

    return None


def _normalize(code: str) -> str:
    """
    Normalize extracted code:
    - Strip leading/trailing whitespace
    - Ensure `timescale directive is present (add if missing)
    - Ensure `default_nettype none is present (add if missing)
    - Strip Windows-style line endings
    """
    code = code.replace("\r\n", "\n").strip()

    has_timescale = "`timescale" in code
    has_nettype_none = "`default_nettype none" in code

    header_lines = []
    if not has_timescale:
        header_lines.append("`timescale 1ns/1ps")
    if not has_nettype_none:
        header_lines.append("`default_nettype none")

    if header_lines:
        code = "\n".join(header_lines) + "\n\n" + code

    # Ensure trailing default_nettype wire
    if "`default_nettype wire" not in code:
        code = code + "\n\n`default_nettype wire"

    return code

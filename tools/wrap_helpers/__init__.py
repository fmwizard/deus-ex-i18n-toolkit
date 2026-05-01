"""Binary patches that adjust word-wrap behavior in stock DLLs for languages
without ASCII space wordbreaks (CJK, Thai, Lao, Khmer, etc.).

Stock Deus Ex word-wrapping treats ASCII 0x20 as the only word boundary.
That heuristic is correct for Latin/Cyrillic and broken for scripts written
without inter-word spaces. The patches here make the wrap algorithm work for
the latter; Latin/Cyrillic targets should leave them disabled.
"""

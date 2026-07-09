"""Stateful in-memory Airtable double with a real formula evaluator covering the
formula grammar this codebase actually uses: {field}='v', RECORD_ID()='v',
DATETIME_FORMAT({f},'YYYY-MM-DD') with = and >=, AND(...), OR(...), NOT(...)."""
import itertools

_counter = itertools.count(1)


def _find_top(s: str, needle: str) -> int:
    depth, i, q = 0, 0, False
    while i <= len(s) - len(needle):
        c = s[i]
        if c == "'":
            q = not q
        elif not q:
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            elif depth == 0 and s.startswith(needle, i):
                if needle == "=" and i > 0 and s[i-1] in "><!":
                    i += 1
                    continue
                return i
        i += 1
    return -1


def _split_top(s: str):
    parts, depth, q, cur = [], 0, False, ""
    for c in s:
        if c == "'":
            q = not q
        if not q:
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            elif c == "," and depth == 0:
                parts.append(cur)
                cur = ""
                continue
        cur += c
    if cur.strip():
        parts.append(cur)
    return parts


def _resolve(tok: str, rec: dict):
    tok = tok.strip()
    if tok.startswith("'") and tok.endswith("'"):
        return tok[1:-1]
    if tok == "RECORD_ID()":
        return rec["id"]
    if tok.startswith("DATETIME_FORMAT("):
        inner = tok[len("DATETIME_FORMAT("):-1]
        field = _split_top(inner)[0].strip()
        val = rec["fields"].get(field[1:-1], "") or ""
        return str(val)[:10]  # YYYY-MM-DD
    if tok.startswith("{") and tok.endswith("}"):
        v = rec["fields"].get(tok[1:-1], "")
        return "" if v is None else v
    return tok


def evaluate(formula: str, rec: dict) -> bool:
    f = formula.strip()
    if not f:
        return True
    for name in ("AND", "OR", "NOT"):
        if f.startswith(name + "(") and f.endswith(")"):
            parts = _split_top(f[len(name) + 1:-1])
            vals = [evaluate(p, rec) for p in parts]
            if name == "AND":
                return all(vals)
            if name == "OR":
                return any(vals)
            return not vals[0]
    for op in (">=", "<=", "!=", "=", ">", "<"):
        idx = _find_top(f, op)
        if idx != -1:
            left = _resolve(f[:idx], rec)
            right = _resolve(f[idx + len(op):], rec)
            l, r = str(left), str(right)
            return {"=": l == r, "!=": l != r, ">=": l >= r,
                    "<=": l <= r, ">": l > r, "<": l < r}[op]
    return False


class FakeAirtable:
    def __init__(self):
        self.tables: dict = {}

    def seed(self, table: str, fields: dict, rec_id: str | None = None) -> str:
        rid = rec_id or f"rec{next(_counter):06d}"
        self.tables.setdefault(table, {})[rid] = dict(fields)
        return rid

    async def list_records(self, table, formula="", fields=None, max_records=100):
        rows = [{"id": rid, "fields": dict(fl)}
                for rid, fl in self.tables.get(table, {}).items()]
        out = [r for r in rows if evaluate(formula, r)]
        return out[:max_records] if max_records else out

    async def create_record(self, table, fields):
        rid = self.seed(table, fields)
        return {"id": rid, "fields": dict(fields)}

    async def patch_record(self, table, record_id, fields):
        store = self.tables.setdefault(table, {}).setdefault(record_id, {})
        for k, v in fields.items():
            if v == "":
                store.pop(k, None)
            else:
                store[k] = v
        return {"id": record_id, "fields": dict(store)}

"""Regenerates docs/API_DOCUMENTATION.md from the live OpenAPI schema.

Usage (from backend/): uv run python -m scripts.gen_api_docs
"""

from pathlib import Path

from app.main import app

HEADER = """# API documentation

Generated from the live OpenAPI schema (`uv run python -m scripts.gen_api_docs` regenerates it).
Interactive docs are served at `/api/docs` outside production.

All endpoints return JSON. Errors use one envelope: `{"error": {"code", "message", "fields"?}}`.
State-changing requests need the `X-CSRF-Token` header (copy of the `ec_csrf` cookie).
Patient-scoped routes return **404** when the caller is not an active member of that care circle,
and **403** when they are a member without the required permission.
"""

FOOTER = """
## Internal

| Method | Path | Purpose |
|---|---|---|
| POST | `/internal/jobs/tick` | Reminder tick: Google OIDC (Cloud Scheduler) or `X-Job-Token`. |
| GET | `/healthz` | Liveness |
| GET | `/readyz` | Readiness: runs `SELECT 1` against the database |
"""


def main() -> None:
    spec = app.openapi()
    rows = sorted(
        (op.get("tags", ["other"])[0], method.upper(), path, op.get("summary", ""))
        for path, ops in spec["paths"].items()
        for method, op in ops.items()
    )
    lines = [HEADER]
    tag = None
    for t, m, p, s in rows:
        if t != tag:
            lines += ["", f"## {t.title()}", "", "| Method | Path | Purpose |", "|---|---|---|"]
            tag = t
        lines.append(f"| {m} | `{p}` | {s} |")
    out = Path(__file__).resolve().parents[2] / "docs" / "API_DOCUMENTATION.md"
    out.write_text("\n".join(lines) + "\n" + FOOTER, encoding="utf-8")
    print(f"wrote {len(rows)} operations to {out}")


if __name__ == "__main__":
    main()

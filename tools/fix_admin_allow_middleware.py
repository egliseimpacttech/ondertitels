from pathlib import Path

p = Path(__file__).resolve().parent.parent / "backend" / "main.py"
t = p.read_text(encoding="utf-8")

old = """            if allowed_raw:
                allowed = {e.strip().lower() for e in allowed_raw.split(",") if e.strip()}
                email = (claims.get("email") or "").strip().lower()
                if not email or email not in allowed:
                    # Non-allowlisted users can only access cinema endpoints
                    if not (path.startswith("/api/cinema") or path == "/api/health"):
                        return JSONResponse({"detail": "Access restricted to Cinema only."}, status_code=403)
                    request.state.is_cinema_only = True
                else:
                    request.state.is_cinema_only = False"""

new = """            if allowed_raw:
                allowed = {e.strip().lower() for e in allowed_raw.split(",") if e.strip()}
                email = (claims.get("email") or "").strip().lower()
                is_admin = _is_admin_email(email)
                if not email or (email not in allowed and not is_admin):
                    # Non-allowlisted users can only access cinema endpoints
                    if not (path.startswith("/api/cinema") or path == "/api/health"):
                        return JSONResponse({"detail": "Access restricted to Cinema only."}, status_code=403)
                    request.state.is_cinema_only = True
                else:
                    request.state.is_cinema_only = False"""

if old not in t:
    raise SystemExit("middleware block not found")

p.write_text(t.replace(old, new, 1), encoding="utf-8")
print("ok")

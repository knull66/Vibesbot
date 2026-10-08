#!/usr/bin/env python3
"""Patch src/web_server.py so Mac splash does not time out during Binance boot."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "src" / "web_server.py"


def patch(text: str) -> tuple[str, list[str]]:
    notes: list[str] = []

    if '"/healthz"' not in text:
        text2, n = re.subn(
            r'("/companion",\n)',
            r'\1        "/healthz",\n',
            text,
            count=1,
        )
        if n:
            text = text2
            notes.append("public /healthz")
        else:
            notes.append("WARN: could not add /healthz to public_exact")

    if "asyncio.create_task(_boot())" not in text:
        pattern = re.compile(
            r'(@app\.on_event\("startup"\)\n'
            r'    async def startup\(\):\n)'
            r'        await bot\.initialize\(\)\n'
            r'        try:\n'
            r'            from \.updater import maybe_daily_update\n'
            r'            result = await maybe_daily_update\(apply=False\)\n'
            r'            if result\.get\("available"\):\n'
            r'                logger\.info\(f"Update available: \{result\.get\(\'latest\'\)\}"\)\n'
            r'                await bot\.manager\.broadcast\(\{\n'
            r'                    "type": "update",\n'
            r'                    "available": True,\n'
            r'                    "current_version": result\.get\("current"\),\n'
            r'                    "latest_version": result\.get\("latest"\),\n'
            r'                    "release_notes": result\.get\("message"\) or "",\n'
            r'                \}\)\n'
            r'        except Exception as exc:\n'
            r'            logger\.warning\(f"Daily update skipped: \{exc\}"\)\n',
            re.M,
        )
        repl = (
            "\\1"
            "        async def _boot():\n"
            "            try:\n"
            "                await bot.initialize()\n"
            "            except Exception as exc:\n"
            "                logger.error(f\"Bot initialize failed: {exc}\")\n"
            "            try:\n"
            "                from .updater import maybe_daily_update\n"
            "                result = await maybe_daily_update(apply=False)\n"
            "                if result.get(\"available\"):\n"
            "                    logger.info(f\"Update available: {result.get('latest')}\")\n"
            "                    await bot.manager.broadcast({\n"
            "                        \"type\": \"update\",\n"
            "                        \"available\": True,\n"
            "                        \"current_version\": result.get(\"current\"),\n"
            "                        \"latest_version\": result.get(\"latest\"),\n"
            "                        \"release_notes\": result.get(\"message\") or \"\",\n"
            "                    })\n"
            "            except Exception as exc:\n"
            "                logger.warning(f\"Daily update skipped: {exc}\")\n"
            "\n"
            "        asyncio.create_task(_boot())\n"
        )
        text2, n = pattern.subn(repl, text, count=1)
        if n:
            text = text2
            notes.append("nonblocking startup")
        else:
            notes.append("WARN: startup pattern not found")

    if '@app.get("/healthz")' not in text:
        text2, n = re.subn(
            r'(    @app\.get\("/login", response_class=HTMLResponse\))',
            (
                '    @app.get("/healthz")\n'
                "    async def healthz():\n"
                '        ver_path = Path(__file__).parent.parent / "VERSION"\n'
                '        version = ver_path.read_text().strip() if ver_path.exists() else "0"\n'
                '        return {"ok": True, "version": version}\n'
                "\n"
                r"\1"
            ),
            text,
            count=1,
        )
        if n:
            text = text2
            notes.append("healthz route")
        else:
            notes.append("WARN: could not add healthz route")

    return text, notes


def main() -> int:
    if not PATH.exists():
        print(f"missing {PATH}")
        return 1
    original = PATH.read_text(encoding="utf-8")
    updated, notes = patch(original)
    if updated != original:
        PATH.write_text(updated, encoding="utf-8")
        print("patched", PATH)
    else:
        print("no file changes")
    for note in notes:
        print("-", note)
    ok = (
        '"/healthz"' in updated
        and "asyncio.create_task(_boot())" in updated
        and '@app.get("/healthz")' in updated
    )
    print("OK" if ok else "INCOMPLETE")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())

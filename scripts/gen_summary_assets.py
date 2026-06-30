from pathlib import Path
EV = Path("evidence/r3_supplement_20260610")
EV.mkdir(parents=True, exist_ok=True)
html_path = EV / "focused_requirements_summary.html"
html_path.write_text(Path("scripts/_summary_template.html").read_text(encoding="utf-8"), encoding="utf-8")
repro = EV / "focused_repro_commands.ps1"
repro.write_text("# R3 repro\npython -m patsight_cli.cli.main result --job-id 2064622971598807040 --job-type structureAndActivity --export-type admet --format csv\n", encoding="utf-8")
png = EV / "screenshots" / "05_focused_requirements_summary.png"
png.parent.mkdir(exist_ok=True)
try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1200, "height": 900})
        page.goto(html_path.resolve().as_uri())
        page.screenshot(path=str(png), full_page=True)
        b.close()
    print("png", png.stat().st_size)
except Exception as exc:
    print("png_skip", exc)
print("done")

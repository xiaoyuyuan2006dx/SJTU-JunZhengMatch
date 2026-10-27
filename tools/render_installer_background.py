"""Render the code-authored installer composition without altering its artwork."""
from pathlib import Path
from playwright.sync_api import sync_playwright

root=Path(__file__).resolve().parent.parent
output=root/'build/installer-background.png';output.parent.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(channel='chrome',headless=True)
    page=browser.new_page(viewport={'width':1280,'height':684},device_scale_factor=1)
    page.goto((root/'packaging/windows/installer-background.html').as_uri())
    page.locator('img').evaluate('(img)=>img.decode()')
    page.screenshot(path=str(output))
    browser.close()
from PIL import Image
with Image.open(output) as rendered:rendered.convert('RGB').save(output.with_suffix('.bmp'))

#!/usr/bin/env python
"""Diagnose why SEI auto_login fails with 'element is not visible'.

Opens headed Chromium, navigates to SEI_URL, captures DOM + screenshot,
and probes the password field's ancestor visibility chain.

Usage: .venv/Scripts/python.exe scripts/debug_sei_login.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

OUT_DIR = _REPO_ROOT / "procedures_data" / "sei_capture" / f"debug_login_{datetime.now():%Y%m%d_%H%M%S}"


async def main() -> int:
    from ufpr_automation.config.settings import SEI_URL, SEI_USERNAME
    from ufpr_automation.sei.browser import create_browser_context, launch_browser

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"out dir: {OUT_DIR}")

    pw, browser = await launch_browser(headless=False)
    try:
        context = await create_browser_context(browser, headless=False)
        page = await context.new_page()

        # ---- Stage 1: land on SEI_URL, capture pre-login state
        print(f"\n=== Stage 1: navigating to {SEI_URL} ===")
        await page.goto(SEI_URL, wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle", timeout=15000)
        await page.screenshot(path=str(OUT_DIR / "01_initial.png"), full_page=True)
        (OUT_DIR / "01_initial.html").write_text(await page.content(), encoding="utf-8")
        print(f"  url: {page.url}")
        print(f"  title: {await page.title()}")

        # Find all password inputs + probe their visibility
        probe = await page.evaluate(r"""
            () => {
                const result = {
                    passwords: [],
                    username_candidates: [],
                    overlays: [],
                    modals: [],
                    iframes: [],
                    scripts_hint: []
                };
                for (const el of document.querySelectorAll('input[type="password"]')) {
                    const cs = getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    const chain = [];
                    let cur = el;
                    while (cur && cur !== document.body) {
                        const ccs = getComputedStyle(cur);
                        chain.push({
                            tag: cur.tagName,
                            id: cur.id || null,
                            cls: cur.className || null,
                            display: ccs.display,
                            visibility: ccs.visibility,
                            opacity: ccs.opacity,
                            hidden_attr: cur.hidden || null
                        });
                        cur = cur.parentElement;
                    }
                    result.passwords.push({
                        id: el.id || null,
                        name: el.name || null,
                        offsetParent_is_null: el.offsetParent === null,
                        disabled: el.disabled,
                        readonly: el.readOnly,
                        rect: {x: rect.x, y: rect.y, w: rect.width, h: rect.height},
                        self_display: cs.display,
                        self_visibility: cs.visibility,
                        self_opacity: cs.opacity,
                        ancestor_chain: chain
                    });
                }
                for (const el of document.querySelectorAll('input[type="text"], input:not([type])')) {
                    result.username_candidates.push({
                        id: el.id || null,
                        name: el.name || null,
                        placeholder: el.placeholder || null,
                        visible: el.offsetParent !== null
                    });
                }
                // overlays: fixed/absolute elements with high z-index
                for (const el of document.querySelectorAll('body *')) {
                    const cs = getComputedStyle(el);
                    if ((cs.position === 'fixed' || cs.position === 'absolute') &&
                        parseInt(cs.zIndex || '0') >= 100 &&
                        el.offsetParent !== null) {
                        const rect = el.getBoundingClientRect();
                        if (rect.width > 100 && rect.height > 50) {
                            result.overlays.push({
                                tag: el.tagName,
                                id: el.id || null,
                                cls: (el.className || '').slice(0, 100),
                                z: cs.zIndex,
                                pos: cs.position,
                                rect: {w: rect.width, h: rect.height}
                            });
                        }
                    }
                }
                for (const el of document.querySelectorAll('[role="dialog"], .modal, .popup, [class*="overlay"]')) {
                    if (el.offsetParent !== null) {
                        result.modals.push({
                            tag: el.tagName,
                            id: el.id || null,
                            cls: (el.className || '').slice(0, 100)
                        });
                    }
                }
                for (const el of document.querySelectorAll('iframe')) {
                    result.iframes.push({
                        src: el.src || null,
                        id: el.id || null,
                        name: el.name || null
                    });
                }
                // Scripts hint: first ~30 chars of inline scripts to spot Vue/React/Angular
                const inline = [...document.querySelectorAll('script:not([src])')].map(s => (s.textContent || '').slice(0, 80));
                result.scripts_hint = inline.slice(0, 3);
                return result;
            }
        """)
        (OUT_DIR / "01_probe.json").write_text(
            json.dumps(probe, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"  password inputs found: {len(probe['passwords'])}")
        for i, p in enumerate(probe["passwords"]):
            print(f"    [{i}] id={p['id']} name={p['name']} "
                  f"offsetParent_null={p['offsetParent_is_null']} "
                  f"rect={p['rect']} display={p['self_display']} vis={p['self_visibility']}")
            # Find first invisible ancestor
            for a in p["ancestor_chain"]:
                if a["display"] == "none" or a["visibility"] == "hidden" or a["hidden_attr"]:
                    print(f"        >> HIDDEN ancestor: {a['tag']}#{a['id']}.{str(a['cls'])[:50]} "
                          f"display={a['display']} vis={a['visibility']} hidden={a['hidden_attr']}")
                    break
        print(f"  overlays (high z-index visible): {len(probe['overlays'])}")
        for o in probe["overlays"][:5]:
            print(f"    {o}")
        print(f"  modals/dialogs visible: {len(probe['modals'])}")
        for m in probe["modals"][:5]:
            print(f"    {m}")
        print(f"  iframes: {len(probe['iframes'])}")
        for f in probe["iframes"]:
            print(f"    {f}")

        # ---- Stage 2: try to fill username, then reprobe password visibility
        print(f"\n=== Stage 2: fill username, reprobe password ===")
        try:
            username_input = page.locator(
                'input#txtUsuario, input[name="txtUsuario"], '
                'input[type="text"][id*="usuario"], input[type="text"][id*="login"]'
            )
            await username_input.first.wait_for(state="visible", timeout=10000)
            await username_input.first.fill(SEI_USERNAME)
            print(f"  username filled OK")
            await page.wait_for_timeout(1500)
        except Exception as e:
            print(f"  username fill failed: {e}")

        await page.screenshot(path=str(OUT_DIR / "02_after_username.png"), full_page=True)
        (OUT_DIR / "02_after_username.html").write_text(await page.content(), encoding="utf-8")

        probe2 = await page.evaluate(r"""
            () => {
                const result = {passwords: [], visible_submit: []};
                for (const el of document.querySelectorAll('input[type="password"]')) {
                    const cs = getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    const chain = [];
                    let cur = el;
                    while (cur && cur !== document.body) {
                        const ccs = getComputedStyle(cur);
                        chain.push({
                            tag: cur.tagName, id: cur.id || null,
                            display: ccs.display, visibility: ccs.visibility
                        });
                        cur = cur.parentElement;
                    }
                    result.passwords.push({
                        id: el.id || null, name: el.name || null,
                        offsetParent_null: el.offsetParent === null,
                        rect: {w: rect.width, h: rect.height},
                        ancestor_chain: chain
                    });
                }
                for (const el of document.querySelectorAll('button, input[type="submit"]')) {
                    if (el.offsetParent !== null) {
                        result.visible_submit.push({
                            tag: el.tagName, id: el.id || null,
                            text: (el.textContent || el.value || '').slice(0, 40),
                            type: el.type || null
                        });
                    }
                }
                return result;
            }
        """)
        (OUT_DIR / "02_probe.json").write_text(
            json.dumps(probe2, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"  password inputs now: {len(probe2['passwords'])}")
        for p in probe2["passwords"]:
            print(f"    id={p['id']} offsetParent_null={p['offsetParent_null']} rect={p['rect']}")
            for a in p["ancestor_chain"]:
                if a["display"] == "none" or a["visibility"] == "hidden":
                    print(f"      >> HIDDEN ancestor: {a['tag']}#{a['id']} "
                          f"display={a['display']} vis={a['visibility']}")
                    break
        print(f"  visible buttons: {len(probe2['visible_submit'])}")
        for b in probe2["visible_submit"][:8]:
            print(f"    {b}")

        # ---- Stage 3: click ACESSAR, see if we land on a password page
        print(f"\n=== Stage 3: click sbmAcessar, probe next page ===")
        try:
            btn = page.locator('button#sbmAcessar, input#sbmAcessar')
            await btn.first.click()
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception as e:
            print(f"  click failed: {e}")

        await page.screenshot(path=str(OUT_DIR / "03_after_acessar.png"), full_page=True)
        (OUT_DIR / "03_after_acessar.html").write_text(await page.content(), encoding="utf-8")
        print(f"  url now: {page.url}")
        print(f"  title: {await page.title()}")

        probe3 = await page.evaluate(r"""
            () => {
                const result = {passwords: [], text_inputs: [], buttons: [], radios: [], all_visible_inputs: []};
                for (const el of document.querySelectorAll('input')) {
                    if (el.offsetParent === null) continue;
                    const rect = el.getBoundingClientRect();
                    result.all_visible_inputs.push({
                        type: el.type, id: el.id || null, name: el.name || null,
                        placeholder: el.placeholder || null,
                        rect: {w: rect.width, h: rect.height}
                    });
                    if (el.type === 'password') {
                        result.passwords.push({id: el.id, name: el.name, rect: {w: rect.width, h: rect.height}});
                    }
                    if (el.type === 'radio' || el.type === 'checkbox') {
                        result.radios.push({type: el.type, id: el.id, name: el.name, value: el.value, checked: el.checked});
                    }
                }
                for (const el of document.querySelectorAll('button, input[type="submit"]')) {
                    if (el.offsetParent !== null) {
                        result.buttons.push({
                            tag: el.tagName, id: el.id || null,
                            text: (el.textContent || el.value || '').trim().slice(0, 40)
                        });
                    }
                }
                return result;
            }
        """)
        (OUT_DIR / "03_probe.json").write_text(
            json.dumps(probe3, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"  visible inputs: {len(probe3['all_visible_inputs'])}")
        for inp in probe3["all_visible_inputs"]:
            print(f"    {inp}")
        print(f"  visible password inputs: {len(probe3['passwords'])}")
        for p in probe3["passwords"]:
            print(f"    {p}")
        print(f"  visible buttons: {len(probe3['buttons'])}")
        for b in probe3["buttons"]:
            print(f"    {b}")
        print(f"  visible radios/checkboxes: {len(probe3['radios'])}")
        for r in probe3["radios"]:
            print(f"    {r}")

        print(f"\n--- keeping browser open 15s for human inspection ---")
        await page.wait_for_timeout(15000)
        return 0
    finally:
        try:
            await browser.close()
        finally:
            await pw.stop()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

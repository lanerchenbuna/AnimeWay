#!/usr/bin/env python3
"""Optional real-browser acceptance check against an isolated localhost instance.

Run with Playwright available and ANIMEWAY_DATA_DIR pointing to a disposable
directory on the Streamlit server. Only fresh browser profiles are used. The
script does not read personal browser storage or print anonymous credentials.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
from urllib.parse import urlsplit


def main() -> None:
    from playwright.sync_api import expect, sync_playwright

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8751")
    parser.add_argument("--executable", help="Optional installed Chromium executable")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    parsed = urlsplit(args.url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.username:
        parser.error("Only an isolated localhost HTTP test instance is supported")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    checks = []
    title = "AnimeWay 浏览器验收手册"

    with tempfile.TemporaryDirectory(prefix="animeway-browser-") as directory, sync_playwright() as playwright:
        root = Path(directory)
        options = {"headless": True}
        if args.executable:
            options["executable_path"] = args.executable

        def launch(profile: str, *, mobile: bool = False):
            context = playwright.chromium.launch_persistent_context(
                str(root / profile), **options,
                viewport={"width": 390 if mobile else 1280, "height": 844 if mobile else 900},
                is_mobile=mobile, has_touch=mobile, accept_downloads=True,
            )
            # The non-AI text flow must work even when all external HTTP fails.
            context.route("**/*", lambda route: route.continue_() if urlsplit(route.request.url).hostname in {"127.0.0.1", "localhost"} else route.abort())
            page = context.pages[0]
            page.set_default_timeout(30000)
            page.goto(args.url)
            expect(page.locator(".st-key-aw_open_selected_discover button")).to_be_visible()
            # During the identity handshake Streamlit may briefly retain the
            # disabled old render next to the enabled replacement.
            expect(page.locator('[class*="st-key-aw_wish_discover_"] button:not([disabled])').first).to_be_visible()
            if mobile:
                collapse = page.get_by_test_id("stSidebarCollapseButton").get_by_role("button")
                if collapse.is_visible():
                    collapse.click()
            return context, page

        def click(page, key):
            button = page.locator(f".st-key-{key} button")
            expect(button).to_be_enabled()
            button.click()

        desktop, page = launch("owner")
        click(page, "aw_work_328609")
        scene = page.locator('[class*="st-key-aw_scene_location_"] button').first
        scene.click()
        wish = page.locator('[class*="st-key-aw_wish_detail_"] button')
        expect(wish).to_be_enabled()
        wish.click()
        expect(wish).to_contain_text("从想去清单移除")
        click(page, "aw_back")
        click(page, "aw_route_card_anime_route-shimokitazawa-first")
        optional = page.locator('[class*="st-key-aw_keep_"] input').first
        expect(optional).to_be_checked()
        page.locator('[class*="st-key-aw_keep_"] label').first.click()
        expect(optional).not_to_be_checked()
        expect(page.get_by_text("站点连接需要重新核查。这里不保留删点前的交通耗时，也不提供未经核实的总行程时间。", exact=True)).to_be_visible()
        click(page, "aw_adopt_route-shimokitazawa-first")
        name = page.locator('[class*="st-key-aw_trip_title_"] input')
        expect(name).to_be_visible()
        name.fill(title)
        name.press("Enter")
        page.locator('[class*="st-key-aw_rename_"] button').click()
        expect(page.get_by_role("heading", name=title, exact=True)).to_be_visible()
        checks.append("work_scene_location_wishlist_adopt_edit")
        with page.expect_download() as download:
            page.locator('[class*="st-key-aw_offline_"] button').click()
        path = root / "checklist.txt"
        download.value.save_as(path)
        checklist = path.read_text()
        assert title in checklist and "google.com/maps" in checklist
        assert "连接需要重新核查" in checklist or "重新核查" in checklist
        checks.append("text_download_without_external_network")
        click(page, "aw_nav_settings")
        with page.expect_download() as download:
            click(page, "aw_backup_download")
        backup_path = root / "backup.json"
        download.value.save_as(backup_path)
        backup = json.loads(backup_path.read_text())
        assert set(backup) == {"schema_version", "wishlist", "trips", "personal_trips"}
        assert len(backup["trips"]) == 1 and len(backup["wishlist"]) == 1
        desktop.close()

        mobile, page = launch("owner", mobile=True)
        click(page, "aw_continue_latest")
        expect(page.get_by_role("heading", name=title, exact=True)).to_be_visible()
        navigation = page.get_by_role("link", name="打开地图导航", exact=True)
        expect(navigation.first).to_be_visible()
        assert "google.com/maps" in navigation.first.get_attribute("href")
        expect(navigation).to_have_count(4)
        expect(page.locator("code").filter(has_text="35.661700, 139.667400")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        navigation.first.scroll_into_view_if_needed()
        page.screenshot(path=str(args.output_dir / "mobile-checklist.png"), full_page=True)
        checks.append("browser_restart_mobile_restore_navigation_copy")
        mobile.close()

        other, page = launch("other", mobile=True)
        click(page, "aw_nav_trips")
        expect(page.get_by_text(title, exact=True)).to_have_count(0)
        click(page, "aw_nav_wishlist")
        expect(page.locator('[class*="st-key-aw_wish_wishlist_"] button')).to_have_count(0)
        checks.append("separate_browser_isolation")
        click(page, "aw_nav_settings")
        page.locator('input[type="file"]').set_input_files(str(backup_path))
        click(page, "aw_restore")
        expect(page.get_by_test_id("stAlertContainer").filter(has_text="恢复")).to_be_visible()
        click(page, "aw_nav_trips")
        expect(page.get_by_text(title, exact=True)).to_be_visible()
        page.locator('[class*="st-key-aw_open_trip_"] button').click()
        expect(page.get_by_role("heading", name=title, exact=True)).to_be_visible()
        page.get_by_role("link", name="打开地图导航", exact=True).first.scroll_into_view_if_needed()
        page.screenshot(path=str(args.output_dir / "mobile-restored.png"), full_page=True)
        checks.append("user_controlled_backup_restore_other_browser")
        assert page.get_by_test_id("stException").count() == 0
        other.close()

    result = {"checks": checks, "passed": len(checks), "external_network": "blocked", "profiles": "temporary synthetic test users", "field_walks": 0, "human_participants": 0}
    (args.output_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

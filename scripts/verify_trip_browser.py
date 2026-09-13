#!/usr/bin/env python3
"""Real Chromium checks for Step 2 against a disposable localhost app, no Keys."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import tempfile
from urllib.parse import urlsplit


def main():
    from playwright.sync_api import expect, sync_playwright

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8753")
    parser.add_argument("--executable")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    parsed = urlsplit(args.url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.username:
        parser.error("Use an isolated localhost HTTP test instance")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    checks, title = [], "AnimeWay 两日个人 Trip 浏览器验收"

    with tempfile.TemporaryDirectory(prefix="animeway-trip-browser-") as directory, sync_playwright() as playwright:
        root = Path(directory)
        options = {"headless": True}
        if args.executable:
            options["executable_path"] = args.executable

        def launch(profile, mobile=False):
            context = playwright.chromium.launch_persistent_context(str(root / profile), **options,
                viewport={"width": 390 if mobile else 1280, "height": 844 if mobile else 900},
                is_mobile=mobile, has_touch=mobile, accept_downloads=True)
            context.route("**/*", lambda route: route.continue_() if urlsplit(route.request.url).hostname in {"127.0.0.1", "localhost"} else route.abort())
            page = context.pages[0]
            page.set_default_timeout(30000)
            page.goto(args.url)
            expect(page.locator('[class*="st-key-aw_wish_discover_"] button:not([disabled])').first).to_be_visible()
            if mobile:
                collapse = page.get_by_test_id("stSidebarCollapseButton").get_by_role("button")
                if collapse.is_visible():
                    collapse.click()
            return context, page

        def click(page, key):
            target = page.locator(f".st-key-{key} button:not([disabled])").first
            expect(target).to_be_visible()
            target.click()

        def widget(page, ending, tag):
            return page.locator(f'[class*="st-key-awp_"][class*="_{ending}"] {tag}').first

        desktop, page = launch("owner")
        click(page, "aw_nav_personal")
        click(page, "awp_new")
        page.get_by_text("用一句话整理需求（可选）", exact=True).click()
        page.locator('.st-key-awp_free_text textarea').fill("后天下午到东京，住新宿，两天，孤独摇滚和你的名字，不想太赶")
        click(page, "awp_parse")
        name = page.locator('.st-key-awp_new_1_title input')
        expect(name).to_be_visible()
        name.fill(title)
        page.get_by_role("button", name="确认条件并检查草案", exact=True).click()
        click(page, "awp_adopt_0")
        expect(page.get_by_role("heading", name=title, exact=True)).to_be_visible()
        checks.append("natural_text_local_parse_two_day_form_save_without_key")

        page.get_by_text("增加相关场景／缩短当天时间", exact=True).first.click()
        widget(page, "end_text", "input").fill("17:00")
        page.get_by_role("button", name="更新截止时间并检查", exact=True).first.click()
        expect(page.get_by_text("日本时间 · 版本 2 · 筹备草案", exact=True)).to_be_visible()
        page.get_by_text("撤销／恢复旧规划版本", exact=True).click()
        page.get_by_role("button", name="确认恢复这个规划版本", exact=True).click()
        expect(page.get_by_text("日本时间 · 版本 3 · 筹备草案", exact=True)).to_be_visible()
        checks.append("local_deadline_edit_then_restore_prior_version")

        page.get_by_text("我知道仍有待核查内容，准备按草案使用当天清单", exact=True).click()
        page.get_by_role("button", name="开始当天模式", exact=True).click()
        expect(page.get_by_text("日本时间 · 版本 4 · 当天使用中", exact=True)).to_be_visible()
        widget(page, "time", "input").fill("15:00")
        page.get_by_role("combobox", name="当天操作", exact=True).first.click()
        page.get_by_role("option", name="跳过此站", exact=True).click()
        page.get_by_text("确认记录这次现场操作", exact=True).first.click()
        page.get_by_role("button", name="记录并检查剩余安排", exact=True).first.click()
        expect(page.get_by_text("已跳过，未记到访", exact=True)).to_be_visible()
        with page.expect_download() as download:
            page.get_by_role("button", name="下载个人 Trip 文字清单", exact=True).click()
        text_path = root / "trip.txt"
        download.value.save_as(text_path)
        checklist = text_path.read_text()
        assert title in checklist and "skip" in checklist and "google.com/maps" in checklist
        assert "待核查" in checklist and "费用未知" in checklist
        checks.append("today_skip_preserved_in_offline_text_not_counted_as_visit")

        click(page, "aw_nav_settings")
        with page.expect_download() as download:
            click(page, "aw_backup_download")
        backup_path = root / "backup.json"
        download.value.save_as(backup_path)
        backup = json.loads(backup_path.read_text())
        assert set(backup) == {"schema_version", "wishlist", "trips", "personal_trips"}
        trip = backup["personal_trips"][0]
        assert trip["revision"] == 5 and len(trip["history"]) == 2
        assert trip["events"][0]["kind"] == "skip" and trip["state"] == "on_trip"
        original_id = trip["id"]
        desktop.close()

        mobile, page = launch("owner", mobile=True)
        click(page, "aw_nav_personal")
        click(page, f"awp_open_{original_id}")
        expect(page.get_by_role("heading", name=title, exact=True)).to_be_visible()
        expect(page.get_by_text("已跳过，未记到访", exact=True)).to_be_visible()
        navigation = page.get_by_role("link", name="打开地图导航", exact=True).first
        expect(navigation).to_be_visible()
        assert "google.com/maps" in navigation.get_attribute("href")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        navigation.scroll_into_view_if_needed()
        page.screenshot(path=str(args.output_dir / "mobile-trip.png"), full_page=True, animations="disabled")
        assert page.get_by_test_id("stException").count() == 0
        checks.append("browser_restart_mobile_conditions_history_execution_navigation")
        mobile.close()

        other, page = launch("other", mobile=True)
        click(page, "aw_nav_personal")
        expect(page.get_by_text(title, exact=True)).to_have_count(0)
        click(page, "aw_nav_settings")
        page.locator('input[type="file"]').set_input_files(str(backup_path))
        click(page, "aw_restore")
        expect(page.get_by_test_id("stAlertContainer").filter(has_text="恢复")).to_be_visible()
        click(page, "aw_nav_personal")
        expect(page.get_by_text(title, exact=True)).to_be_visible()
        page.locator('[class*="st-key-awp_open_"] button').click()
        expect(page.get_by_role("heading", name=title, exact=True)).to_be_visible()
        expect(page.get_by_text("已跳过，未记到访", exact=True)).to_be_visible()
        page.get_by_text("撤销／恢复旧规划版本", exact=True).click()
        undo = page.get_by_role("button", name="确认恢复这个规划版本", exact=True)
        expect(undo).to_be_visible()
        undo.scroll_into_view_if_needed()
        page.screenshot(path=str(args.output_dir / "mobile-restored-trip.png"), full_page=True, animations="disabled")
        assert page.get_by_test_id("stException").count() == 0
        checks.append("anonymous_isolation_user_backup_restores_history_and_execution")
        other.close()

    result = {"measured_at": datetime.now().astimezone().isoformat(), "checks": checks, "passed": len(checks),
              "external_http": "blocked", "profiles": "temporary synthetic test users", "live_ai_calls": 0,
              "field_walks": 0, "human_participants": 0, "device": "Chromium desktop and 390x844 mobile emulation"}
    (args.output_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Synthetic local-browser verification of private photos, sharing and recovery."""
from datetime import datetime
from io import BytesIO
import argparse
import json
from pathlib import Path
import sys
import tempfile
from urllib.parse import urljoin, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.pilot import load_pilot
from core.trip import empty_plan, new_requirements, propose


def main():
    from PIL import Image
    from playwright.sync_api import expect, sync_playwright
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8754")
    parser.add_argument("--executable")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if urlsplit(args.url).hostname not in {"localhost", "127.0.0.1"} or urlsplit(args.url).scheme != "http":
        parser.error("Only isolated localhost test services are allowed")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    catalog = load_pilot()
    req = new_requirements("今天", 1, anime_ids=["328609"])
    req["pace"] = "normal"
    location_id = propose(empty_plan(req), catalog)[0]["plan"]["days"][0]["stops"][0]["location_id"]
    location_name = next(p["name"] for p in catalog["locations"] if p["id"] == location_id)
    checks = []
    with tempfile.TemporaryDirectory(prefix="animeway-journal-") as folder, sync_playwright() as p:
        root = Path(folder)
        raw = BytesIO()
        Image.new("RGB", (320, 180), "#68e1fd").save(raw, format="JPEG")
        options = {"headless":True}
        if args.executable:
            options["executable_path"] = args.executable

        def launch(profile, mobile=False):
            ctx = p.chromium.launch_persistent_context(str(root/profile), **options,
                viewport={"width":390 if mobile else 1280,"height":844 if mobile else 900},
                is_mobile=mobile, has_touch=mobile, accept_downloads=True)
            ctx.route("**/*", lambda route: route.continue_() if urlsplit(route.request.url).hostname in {"localhost","127.0.0.1"} else route.abort())
            page = ctx.pages[0]
            page.set_default_timeout(30000)
            page.goto(args.url)
            expect(page.locator('[class*="st-key-aw_wish_discover_"] button:not([disabled])').first).to_be_visible()
            if mobile:
                collapse = page.get_by_test_id("stSidebarCollapseButton").get_by_role("button")
                if collapse.is_visible():
                    collapse.click()
            return ctx,page

        def click(page, key):
            target = page.locator(f".st-key-{key} button:not([disabled])").first
            expect(target).to_be_visible()
            target.click()

        def mode(page, name):
            page.get_by_test_id("stRadioGroup").get_by_text(name, exact=True).click()
            settle(page)

        def settle(page):
            # Streamlit can send a second render after its identity handshake.
            page.wait_for_timeout(350)
            page.wait_for_function("!document.querySelector('[data-test-script-state=running]')")

        owner,page = launch("owner")
        click(page,"aw_nav_personal")
        click(page,"awp_new")
        page.get_by_text("用一句话整理需求（可选）",exact=True).click()
        page.locator(".st-key-awp_free_text textarea").fill("今天一天孤独摇滚")
        click(page,"awp_parse")
        expect(page.locator(".st-key-awp_new_1_title input")).to_be_visible()
        page.get_by_role("button",name="确认条件并检查草案",exact=True).click()
        click(page,"awp_adopt_0")
        expect(page.get_by_role("heading",name="我的东京巡礼",exact=True)).to_be_visible()
        click(page,"aw_nav_journal")
        page.get_by_text("补记一次到访",exact=True).click()
        page.get_by_role("combobox",name="到访地点",exact=True).click()
        page.get_by_role("combobox",name="到访地点",exact=True).fill(location_name)
        page.get_by_role("option",name=location_name,exact=True).click()
        page.locator(".st-key-awj_new_note textarea").fill("PRIVATE NOTE SHOULD NEVER BE SHARED")
        page.get_by_text("我确认实际到访了该地点",exact=True).click()
        page.get_by_role("button",name="保存私密足迹",exact=True).click()
        expect(page.get_by_text("足迹已保存",exact=True)).to_be_visible()
        mode(page,"照片与短文")
        page.get_by_text("上传／替换个人照片",exact=True).click()
        page.locator(".st-key-awj_upload input[type=file]").set_input_files({"name":"synthetic.jpg","mimeType":"image/jpeg","buffer":raw.getvalue()})
        expect(page.get_by_text("synthetic.jpg",exact=True)).to_be_visible()
        settle(page)
        page.get_by_role("combobox",name="照片授权",exact=True).click()
        page.get_by_role("combobox",name="照片授权",exact=True).fill("本人拍摄且有权公开使用")
        page.get_by_role("option",name="本人拍摄且有权公开使用",exact=True).click()
        page.get_by_text("允许我稍后在预览中选择此照片分享（此处不会公开）",exact=True).click()
        page.get_by_role("textbox",name="私人照片说明",exact=True).fill("PRIVATE CAPTION")
        page.get_by_role("button",name="保存个人照片",exact=True).click()
        expect(page.locator('img[src^="data:image/jpeg"]')).to_have_count(1)
        checks.append("explicit_visit_private_inline_photo_upload_without_external_network")

        mode(page,"分享")
        page.get_by_role("textbox",name="公开标题",exact=True).fill("浏览器验证公开路线")
        page.get_by_role("combobox",name="明确选择公开照片",exact=True).click()
        page.get_by_role("option",name="个人照片 1",exact=True).click()
        page.get_by_role("button",name="生成发布预览",exact=True).click()
        expect(page.get_by_text("即将公开的副本",exact=True)).to_be_visible()
        page.get_by_text("已检查标题、短文和照片中的隐私，确认发布此预览",exact=True).click()
        click(page,"awj_publish")
        public_link = page.get_by_role("link",name="打开公开副本",exact=True)
        expect(public_link).to_be_visible()
        link = urljoin(args.url, public_link.get_attribute("href"))
        checks.append("public_projection_preview_and_explicit_photo_permission")
        mode(page,"记录备份")
        with page.expect_download() as download:
            click(page,"awj_backup")
        backup = root/"journal.json"
        download.value.save_as(backup)
        payload = json.loads(backup.read_text())
        assert len(payload["entries"]) == len(payload["photos"]) == 1
        assert "route_shares" not in payload

        other,visitor = launch("visitor",mobile=True)
        click(visitor,"aw_nav_journal")
        expect(visitor.get_by_text("PRIVATE NOTE SHOULD NEVER BE SHARED",exact=True)).to_have_count(0)
        visitor.goto(link)
        settle(visitor)
        expect(visitor.get_by_text("浏览器验证公开路线",exact=True)).to_be_visible()
        assert "PRIVATE NOTE" not in visitor.locator("body").inner_text()
        assert "PRIVATE CAPTION" not in visitor.locator("body").inner_text()
        expect(visitor.locator('img[src^="data:image/jpeg"]')).to_have_count(1)
        visitor.locator('img[src^="data:image/jpeg"]').evaluate("el => el.scrollIntoView({block: 'center'})")
        visitor.screenshot(path=str(args.output_dir/"mobile-public-share.png"),full_page=True,animations="disabled")
        click(visitor,"awj_copy_share")
        expect(visitor.get_by_role("heading",name="浏览器验证公开路线",exact=True)).to_be_visible()
        click(visitor,"aw_nav_journal")
        mode(visitor,"照片与短文")
        expect(visitor.get_by_text("先确认或补记一次到访，再整理照片。",exact=True)).to_be_visible()
        checks.append("separate_browser_share_copy_without_private_journal_or_photos")

        mode(page,"分享")
        page.get_by_role("button",name="撤下此分享",exact=True).click()
        visitor.goto(link)
        expect(visitor.get_by_text("此分享不存在或已撤下",exact=True)).to_be_visible()
        expect(visitor.locator('img[src^="data:image/jpeg"]')).to_have_count(0)
        checks.append("revocation_stops_new_public_reads")
        visitor.goto(args.url)
        click(visitor,"aw_nav_journal")
        mode(visitor,"记录备份")
        visitor.locator(".st-key-awj_restore_file input[type=file]").set_input_files(str(backup))
        click(visitor,"awj_restore")
        expect(visitor.get_by_text("新增 1 条记录；相同文件重复恢复不会重复添加",exact=True)).to_be_visible()
        mode(visitor,"照片与短文")
        expect(visitor.locator('img[src^="data:image/jpeg"]')).to_have_count(1)
        expect(visitor.get_by_text("PRIVATE CAPTION",exact=True)).to_be_visible()
        assert visitor.get_by_text("PRIVATE CAPTION",exact=True).evaluate("el => getComputedStyle(el).color") == "rgb(245, 247, 255)"
        assert visitor.evaluate("document.documentElement.scrollWidth <= window.innerWidth+1")
        visitor.locator('img[src^="data:image/jpeg"]').evaluate("el => el.scrollIntoView({block: 'center'})")
        visitor.screenshot(path=str(args.output_dir/"mobile-restored-record.png"),full_page=True,animations="disabled")
        assert page.get_by_test_id("stException").count() == 0
        assert visitor.get_by_test_id("stException").count() == 0
        checks.append("user_controlled_photo_backup_restore_defaults_private")
        owner.close()
        other.close()
    result = {"measured_at":datetime.now().astimezone().isoformat(),"checks":checks,"passed":len(checks),
              "profiles":"temporary synthetic users","external_http":"blocked","human_participants":0,"field_walks":0,"live_ai_calls":0}
    (args.output_dir/"result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()

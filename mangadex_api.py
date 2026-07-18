#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MangaDex Downloader
使用 MangaDex 官方公开 API（https://api.mangadex.org）搜索漫画、拉取章节、
下载页面图片，并可选打包为 .cbz（漫画阅读器通用格式，本质就是zip）。

MangaDex 官方是欢迎第三方客户端走 API 的（很多离线阅读器都这么做），
比直接爬网页 HTML 更稳定、也不容易触发反爬。

依赖：pip install requests

用法示例：
  # 按标题搜索并列出结果
  python mangadex_dl.py search "chainsaw man"

  # 按 manga 网址下载所有英文章节，打包成 cbz
  python mangadex_dl.py download --url https://mangadex.org/title/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx/some-manga --lang en --cbz

  # 只下载第1到第10话
  python mangadex_dl.py download --url ... --lang en --start 1 --end 10 --cbz
"""

import argparse
import os
import re
import sys
import time
import zipfile
import shutil
from urllib.parse import urlparse

import requests

API_BASE = "https://api.mangadex.org"
REQUEST_INTERVAL = 0.25  # 官方建议控制在约 5 req/s 以内，这里留点余量
UA = "mangadex-dl/1.0 (personal offline reader script)"


def _get(url, **kwargs):
    """带简单限速和重试的 GET 请求"""
    time.sleep(REQUEST_INTERVAL)
    for attempt in range(3):
        resp = requests.get(url, headers={"User-Agent": UA}, timeout=20, **kwargs)
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", "5"))
            print(f"  [限速] 429，等待 {wait}s 后重试...")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp
    resp.raise_for_status()
    return resp


def sanitize(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", name).strip()


def extract_manga_id(url: str) -> str:
    m = re.search(r"/title/([0-9a-fA-F-]{36})", url)
    if not m:
        raise ValueError("没能从这个网址里解析出 manga id，请确认是 mangadex.org/title/<uuid>/... 格式")
    return m.group(1)


def search_manga(title: str, limit: int = 5):
    resp = _get(f"{API_BASE}/manga", params={"title": title, "limit": limit})
    data = resp.json()["data"]
    results = []
    for item in data:
        titles = item["attributes"]["title"]
        name = titles.get("en") or next(iter(titles.values()), "未知标题")
        results.append({"id": item["id"], "title": name})
    return results


def get_manga_title(manga_id: str) -> str:
    resp = _get(f"{API_BASE}/manga/{manga_id}")
    titles = resp.json()["data"]["attributes"]["title"]
    return titles.get("en") or next(iter(titles.values()), manga_id)


def get_chapter_feed(manga_id: str, lang: str):
    """分页拉取某语言的全部章节，按章节号升序返回"""
    chapters = []
    offset = 0
    limit = 500
    while True:
        params = {
            "translatedLanguage[]": lang,
            "order[chapter]": "asc",
            "limit": limit,
            "offset": offset,
            "includes[]": "scanlation_group",
        }
        resp = _get(f"{API_BASE}/manga/{manga_id}/feed", params=params)
        payload = resp.json()
        chapters.extend(payload["data"])
        total = payload["total"]
        offset += limit
        if offset >= total:
            break
    return chapters


def get_chapter_images(chapter_id: str, data_saver: bool = False):
    resp = _get(f"{API_BASE}/at-home/server/{chapter_id}")
    payload = resp.json()
    base_url = payload["baseUrl"]
    chapter = payload["chapter"]
    filenames = chapter["dataSaver"] if data_saver else chapter["data"]
    mode = "data-saver" if data_saver else "data"
    urls = [f"{base_url}/{mode}/{chapter['hash']}/{fn}" for fn in filenames]
    return urls


def report_to_mdah(url, success, bytes_, duration_ms, cached):
    """向 MangaDex@Home 网络报告下载结果（官方客户端规范要求）"""
    try:
        requests.post(
            f"{API_BASE}/report",
            json={
                "url": url,
                "success": success,
                "bytes": bytes_,
                "duration": duration_ms,
                "cached": cached,
            },
            timeout=10,
        )
    except requests.RequestException:
        pass  # 上报失败不影响主流程


def download_image(url: str, dest_path: str) -> bool:
    start = time.time()
    try:
        resp = requests.get(url, headers={"User-Agent": UA}, timeout=30)
        resp.raise_for_status()
        with open(dest_path, "wb") as f:
            f.write(resp.content)
        duration_ms = int((time.time() - start) * 1000)
        cached = resp.headers.get("X-Cache", "").startswith("HIT")
        report_to_mdah(url, True, len(resp.content), duration_ms, cached)
        return True
    except requests.RequestException as e:
        print(f"    下载失败: {url} ({e})")
        duration_ms = int((time.time() - start) * 1000)
        report_to_mdah(url, False, 0, duration_ms, False)
        return False


def chapter_label(ch) -> str:
    attr = ch["attributes"]
    vol = attr.get("volume")
    num = attr.get("chapter")
    title = attr.get("title") or ""
    parts = []
    if vol:
        parts.append(f"Vol.{vol}")
    if num:
        parts.append(f"Ch.{num}")
    label = " ".join(parts) if parts else ch["id"][:8]
    if title:
        label += f" - {title}"
    return sanitize(label)


def download_chapter(ch, manga_title: str, out_dir: str, as_cbz: bool, data_saver: bool):
    label = chapter_label(ch)
    manga_dir = os.path.join(out_dir, sanitize(manga_title))
    chapter_dir = os.path.join(manga_dir, label)
    os.makedirs(chapter_dir, exist_ok=True)

    print(f"[章节] {label}")
    urls = get_chapter_images(ch["id"], data_saver=data_saver)
    ok = 0
    for i, url in enumerate(urls, start=1):
        ext = os.path.splitext(urlparse(url).path)[1] or ".jpg"
        dest = os.path.join(chapter_dir, f"{i:03d}{ext}")
        if os.path.exists(dest):
            ok += 1
            continue
        if download_image(url, dest):
            ok += 1
        print(f"  第 {i}/{len(urls)} 页", end="\r")
    print(f"  完成 {ok}/{len(urls)} 页" + " " * 10)

    if as_cbz:
        cbz_path = os.path.join(manga_dir, f"{label}.cbz")
        with zipfile.ZipFile(cbz_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname in sorted(os.listdir(chapter_dir)):
                zf.write(os.path.join(chapter_dir, fname), fname)
        shutil.rmtree(chapter_dir)
        print(f"  已打包: {cbz_path}")


def cmd_search(args):
    results = search_manga(args.title)
    if not results:
        print("没搜到结果")
        return
    for r in results:
        print(f"{r['id']}  {r['title']}")
        print(f"  -> https://mangadex.org/title/{r['id']}")


def cmd_download(args):
    manga_id = extract_manga_id(args.url) if args.url else args.id
    manga_title = get_manga_title(manga_id)
    print(f"漫画: {manga_title} ({manga_id})")

    chapters = get_chapter_feed(manga_id, args.lang)
    if not chapters:
        print(f"没有找到语言为 [{args.lang}] 的章节，换个 --lang 试试（如 en / zh / zh-hk / ja）")
        return

    def chapter_num(ch):
        try:
            return float(ch["attributes"]["chapter"])
        except (TypeError, ValueError):
            return -1

    chapters.sort(key=chapter_num)

    if args.start is not None or args.end is not None:
        lo = args.start if args.start is not None else float("-inf")
        hi = args.end if args.end is not None else float("inf")
        chapters = [c for c in chapters if lo <= chapter_num(c) <= hi]

    print(f"共 {len(chapters)} 话待下载")
    os.makedirs(args.out, exist_ok=True)
    for ch in chapters:
        download_chapter(ch, manga_title, args.out, args.cbz, args.data_saver)


def main():
    parser = argparse.ArgumentParser(description="MangaDex 下载器（基于官方公开API）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_search = sub.add_parser("search", help="按标题搜索漫画，获取网址/ID")
    p_search.add_argument("title")
    p_search.set_defaults(func=cmd_search)

    p_dl = sub.add_parser("download", help="下载指定漫画的章节")
    g = p_dl.add_mutually_exclusive_group(required=True)
    g.add_argument("--url", help="mangadex.org 漫画主页网址")
    g.add_argument("--id", help="manga 的 UUID（如果你已经知道）")
    p_dl.add_argument("--lang", default="en", help="章节语言代码，默认 en")
    p_dl.add_argument("--out", default="./downloads", help="输出目录，默认 ./downloads")
    p_dl.add_argument("--start", type=float, default=None, help="起始话数（含）")
    p_dl.add_argument("--end", type=float, default=None, help="结束话数（含）")
    p_dl.add_argument("--cbz", action="store_true", help="打包成 .cbz（推荐，方便阅读器打开）")
    p_dl.add_argument("--data-saver", action="store_true", help="使用压缩图（省流量，画质稍低）")
    p_dl.set_defaults(func=cmd_download)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

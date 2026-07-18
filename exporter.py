import zipfile
import os
import shutil
import tempfile
from pathlib import Path
from PIL import Image
from utils import natural_sort_key
import xml.etree.ElementTree as ET
import uuid

def export_cbz(volume, output_dir, log_func=print):
    """将一卷导出为 CBZ 文件"""
    if not volume.chapters:
        log_func(f"[警告] 卷 {volume.name} 没有章节，跳过")
        return
    cbz_name = f"{volume.name}.cbz"
    cbz_path = Path(output_dir) / cbz_name
    os.makedirs(output_dir, exist_ok=True)
    with zipfile.ZipFile(cbz_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for ch in volume.chapters:
            # 章节内图片按名称排序
            pages = sorted(ch.pages, key=lambda p: natural_sort_key(p.name))
            for idx, img_path in enumerate(pages, 1):
                # 在压缩包内命名：章节号/图片名 或 直接用原文件名（保证唯一性用前缀）
                # 这里采用 章节目录名/原文件名
                arcname = f"{ch.id}/{img_path.name}"
                zf.write(img_path, arcname)
    log_func(f"已导出: {cbz_path}")

def export_pdf(volume, output_dir, title=None, log_func=print):
    """将一卷导出为 PDF 文件（每页图片按顺序拼成多页PDF）"""
    if not volume.chapters:
        log_func(f"[警告] 卷 {volume.name} 没有章节，跳过")
        return
    pdf_name = f"{volume.name}.pdf"
    pdf_path = Path(output_dir) / pdf_name
    os.makedirs(output_dir, exist_ok=True)

    images = []
    for ch in volume.chapters:
        pages = sorted(ch.pages, key=lambda p: natural_sort_key(p.name))
        for img_path in pages:
            try:
                img = Image.open(img_path).convert("RGB")
                images.append(img)
            except Exception as e:
                log_func(f"  跳过无法读取的图片: {img_path} ({e})")

    if not images:
        log_func(f"[警告] 卷 {volume.name} 没有可用图片，跳过")
        return

    first, rest = images[0], images[1:]
    first.save(pdf_path, save_all=True, append_images=rest)
    log_func(f"已导出: {pdf_path}（{len(images)} 页，注意PDF体积会比cbz大不少）")


def _chapter_tag(ch):
    """生成章节前缀，如 36 -> 'chapter36'，36.5 -> 'chapter36.5'"""
    num = ch.number
    if num is None:
        return f"chapter_{ch.id}"
    if isinstance(num, float) and num == int(num):
        num = int(num)
    return f"chapter{num}"


def export_folder(volume, output_dir, log_func=print):
    """
    导出为纯文件夹：不打包、不压缩，图片按 "章节前缀-页码" 重命名后直接放进一个文件夹。
    例如 chapter1-001.jpg, chapter1-002.jpg, chapter2-001.jpg ...
    方便直接在文件夹里用图片工具批量处理/汉化，不用先解压cbz。
    """
    if not volume.chapters:
        log_func(f"[警告] 卷 {volume.name} 没有章节，跳过")
        return
    vol_dir = Path(output_dir) / volume.name
    os.makedirs(vol_dir, exist_ok=True)

    total = 0
    for ch in volume.chapters:
        pages = sorted(ch.pages, key=lambda p: natural_sort_key(p.name))
        tag = _chapter_tag(ch)
        for idx, img_path in enumerate(pages, 1):
            ext = img_path.suffix
            new_name = f"{tag}-{idx:03d}{ext}"
            shutil.copy2(img_path, vol_dir / new_name)
            total += 1
    log_func(f"已导出文件夹: {vol_dir}（共 {total} 张图片，按章节重命名）")


def export_volume(volume, output_dir, fmt, title=None, author="", log_func=print):
    """统一入口：按 fmt ('cbz'/'epub'/'pdf'/'folder') 导出一卷"""
    if fmt == "epub":
        export_epub(volume, output_dir, title=title, author=author, log_func=log_func)
    elif fmt == "pdf":
        export_pdf(volume, output_dir, title=title, log_func=log_func)
    elif fmt == "folder":
        export_folder(volume, output_dir, log_func=log_func)
    else:
        export_cbz(volume, output_dir, log_func=log_func)


def export_epub(volume, output_dir, title=None, author="", log_func=print):
    """将一卷导出为 EPUB 文件"""
    if not volume.chapters:
        log_func(f"[警告] 卷 {volume.name} 没有章节，跳过")
        return
    if not title:
        title = volume.name
    epub_name = f"{volume.name}.epub"
    epub_path = Path(output_dir) / epub_name
    os.makedirs(output_dir, exist_ok=True)

    # 创建临时目录
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        oebps = tmp / "OEBPS"
        images_dir = oebps / "images"
        oebps.mkdir(parents=True)
        images_dir.mkdir()

        # 收集所有图片信息并复制
        manifest_items = []
        spine_items = []
        all_pages = []
        for ch in volume.chapters:
            pages = sorted(ch.pages, key=lambda p: natural_sort_key(p.name))
            for pg in pages:
                all_pages.append((ch, pg))

        for idx, (ch, img_path) in enumerate(all_pages):
            # 获取图片尺寸
            try:
                with Image.open(img_path) as img:
                    width, height = img.size
            except:
                width, height = 800, 1200  # fallback
            ext = img_path.suffix
            img_name = f"{ch.id}_{img_path.stem}{ext}"
            dest = images_dir / img_name
            shutil.copy2(img_path, dest)
            # 生成 xhtml 页面
            page_name = f"page_{idx+1:04d}.xhtml"
            page_path = oebps / page_name
            _write_image_page(page_path, img_name, width, height)
            manifest_items.append((page_name, "application/xhtml+xml"))
            manifest_items.append((f"images/{img_name}", f"image/{ext[1:]}"))
            spine_items.append(page_name)

        # 写入 content.opf
        _write_opf(oebps, title, author, manifest_items, spine_items)
        # 写入 toc.ncx
        _write_ncx(oebps, title, spine_items)

        # mimetype
        with open(tmp / "mimetype", "w") as f:
            f.write("application/epub+zip")

        # 打包
        with zipfile.ZipFile(epub_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.write(tmp / "mimetype", "mimetype", compress_type=zipfile.ZIP_STORED)
            for root, dirs, files in os.walk(tmp):
                for file in files:
                    if file == "mimetype":
                        continue
                    full = Path(root) / file
                    arcname = full.relative_to(tmp)
                    zf.write(full, arcname)
        log_func(f"已导出: {epub_path}")

# 辅助函数（EPUB 内部用）
def _write_image_page(output_path, img_src, width, height):
    html = f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title></title>
<style>body{{margin:0;padding:0;text-align:center;}}img{{max-width:100%;height:auto;}}</style>
</head>
<body><div><img src="images/{img_src}" alt="" style="width:{width}px;height:{height}px;"/></div></body>
</html>'''
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

def _write_opf(oebps, title, author, manifest_items, spine_items):
    package = ET.Element('package', xmlns="http://www.idpf.org/2007/opf", version="2.0",
                         **{"unique-identifier": "book-id"})
    metadata = ET.SubElement(package, 'metadata', {
        'xmlns:dc': "http://purl.org/dc/elements/1.1/",
        'xmlns:opf': "http://www.idpf.org/2007/opf"
    })
    ET.SubElement(metadata, 'dc:title').text = title
    ET.SubElement(metadata, 'dc:creator').text = author or "Unknown"
    ET.SubElement(metadata, 'dc:identifier', id="book-id").text = str(uuid.uuid4())
    ET.SubElement(metadata, 'dc:language').text = "zh"

    manifest = ET.SubElement(package, 'manifest')
    ET.SubElement(manifest, 'item', id="ncx", href="toc.ncx", **{"media-type": "application/x-dtbncx+xml"})
    for i, (href, mtype) in enumerate(manifest_items):
        ET.SubElement(manifest, 'item', id=f"item_{i}", href=href, **{"media-type": mtype})

    spine = ET.SubElement(package, 'spine', toc="ncx")
    for page in spine_items:
        for i, (href, _) in enumerate(manifest_items):
            if href == page:
                ET.SubElement(spine, 'itemref', idref=f"item_{i}")
                break

    with open(oebps / "content.opf", 'wb') as f:
        f.write(ET.tostring(package, xml_declaration=True, encoding='utf-8'))

def _write_ncx(oebps, title, spine_items):
    ncx = ET.Element('ncx', xmlns="http://www.daisy.org/z3986/2005/ncx/", version="2005-1")
    head = ET.SubElement(ncx, 'head')
    ET.SubElement(head, 'meta', name="dtb:uid", content=str(uuid.uuid4()))
    ET.SubElement(head, 'meta', name="dtb:depth", content="1")
    ET.SubElement(head, 'meta', name="dtb:totalPageCount", content="0")
    ET.SubElement(head, 'meta', name="dtb:maxPageNumber", content="0")
    docTitle = ET.SubElement(ncx, 'docTitle')
    ET.SubElement(docTitle, 'text').text = title
    navMap = ET.SubElement(ncx, 'navMap')
    for idx, page in enumerate(spine_items):
        navPoint = ET.SubElement(navMap, 'navPoint', id=f"navPoint-{idx+1}", playOrder=str(idx+1))
        navLabel = ET.SubElement(navPoint, 'navLabel')
        ET.SubElement(navLabel, 'text').text = f"Page {idx+1}"
        ET.SubElement(navPoint, 'content', src=page)

    with open(oebps / "toc.ncx", 'wb') as f:
        f.write(ET.tostring(ncx, xml_declaration=True, encoding='utf-8'))
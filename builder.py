from pathlib import Path
from chapter_parser import Chapter, parse_chapter_from_dir
from volume_manager import Project, Volume
from utils import get_image_files
import os

def scan_chapters(source_dir):
    """
    扫描 source_dir 下的所有一级子目录，生成 Chapter 列表
    自动跳过无图片的目录
    """
    source = Path(source_dir)
    chapters = []
    for entry in source.iterdir():
        if entry.is_dir():
            number, title, ctype = parse_chapter_from_dir(entry)
            ch = Chapter(entry, number, title, ctype)
            ch.scan_pages()
            if ch.pages:   # 至少有一张图片才保留
                chapters.append(ch)
    # 按数字排序（数字为 None 的放在最后，按名称排序）
    chapters.sort(key=lambda c: (c.number is None, c.number if c.number is not None else float('inf'), c.title))
    return chapters

def auto_group_chapters(chapters, chapters_per_volume):
    """简单自动分卷：每 N 章为一卷"""
    volumes = []
    for i in range(0, len(chapters), chapters_per_volume):
        vol_chs = chapters[i:i+chapters_per_volume]
        vol_name = f"Vol.{len(volumes)+1:02d}"
        vol = Volume(vol_name)
        for ch in vol_chs:
            vol.add_chapter(ch)
        volumes.append(vol)
    return volumes

def build_project(source_dir, auto_split=None):
    """
    完整构建流程：
    1. 扫描目录
    2. 自动分卷（如果指定每卷章数）
    返回 Project 对象
    """
    chapters = scan_chapters(source_dir)
    proj = Project(title=Path(source_dir).name)
    proj.chapters = chapters
    # 先全部放入未分配
    proj.unassigned = chapters[:]
    if auto_split:
        vols = auto_group_chapters(chapters, auto_split)
        for vol in vols:
            proj.add_volume(vol)
            for ch in vol.chapters:
                if ch in proj.unassigned:
                    proj.unassigned.remove(ch)
    return proj
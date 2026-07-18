import re
import os
from pathlib import Path
from utils import get_image_files

class Chapter:
    """一个章节对象"""
    def __init__(self, folder, number, title="", chapter_type="normal"):
        self.folder = Path(folder).resolve()
        self.id = self.folder.name                # 用目录名作为唯一 id
        self.number = number                      # 章节号（如 36, 36.5）
        self.title = title
        self.chapter_type = chapter_type
        self.pages = []                           # 图片路径列表
        self.volume = None                        # 所属卷，由 volume_manager 设置

    def scan_pages(self):
        """扫描目录下的图片，存入 self.pages"""
        self.pages = get_image_files(self.folder)

    @property
    def page_count(self):
        return len(self.pages)

    def __repr__(self):
        return f"Chapter({self.number}, {self.title}, {self.page_count}P)"


def parse_chapter_from_dir(directory):
    """
    从目录名解析出章节号、标题和类型
    支持格式：
        - Ch.36
        - Chapter 36
        - 36
        - 36.5
        - Vol.12 Ch.36 - The Longest Day
        - 36 Extra
        - Omake
        - Special
    返回 (number, title, type) 三元组，number 可能为 None
    """
    name = Path(directory).name.strip()
    # 尝试匹配 Ch.数字 或 Chapter 数字
    m = re.search(r'Ch\.?\s*([\d.]+)', name, re.IGNORECASE)
    if m:
        number = float(m.group(1)) if '.' in m.group(1) else int(m.group(1))
        # 提取标题：去掉前面的 Vol.XX Ch.XX 部分
        title_part = re.sub(r'Vol\.?\s*\d+\.?\s*Ch\.?\s*[\d.]+[\s-]*', '', name, flags=re.IGNORECASE).strip()
        chapter_type = "normal"
        # 检测 Extra / Omake / Special
        if re.search(r'\b(extra|omake|bonus|special)\b', title_part, re.IGNORECASE):
            chapter_type = "extra"
        return number, title_part, chapter_type

    # 纯数字开头：如 "36 something"
    m = re.match(r'([\d.]+)\s*(.*)', name)
    if m:
        num_str = m.group(1)
        number = float(num_str) if '.' in num_str else int(num_str)
        title = m.group(2).strip()
        return number, title, "normal"

    # 无法识别的当作特殊章节
    return None, name, "special"
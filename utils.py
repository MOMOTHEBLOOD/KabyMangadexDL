import os
import re
from pathlib import Path

def natural_sort_key(name):
    """自然排序，处理数字 001 < 002 < 010"""
    parts = re.split(r'(\d+)', name)
    return [int(part) if part.isdigit() else part.lower() for part in parts]

def get_image_files(folder):
    """返回文件夹内所有图片文件的排序列表"""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    exts = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}
    files = [p for p in folder.iterdir() if p.suffix.lower() in exts]
    files.sort(key=lambda p: natural_sort_key(p.name))
    return files

def safe_path(input_path):
    """统一转为 Path 对象"""
    return Path(input_path)
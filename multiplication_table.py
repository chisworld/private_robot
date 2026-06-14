# -*- coding: utf-8 -*-
"""九九乘法表"""

def multiplication_table():
    """打印标准九九乘法表"""
    for i in range(1, 10):
        for j in range(1, i + 1):
            print(f"{j}×{i}={i * j:2d}", end="  ")
        print()  # 换行


if __name__ == "__main__":
    multiplication_table()

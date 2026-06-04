"""
九九乘法表
"""


def print_multiplication_table():
    """打印标准九九乘法表"""
    for i in range(1, 10):
        for j in range(1, i + 1):
            print(f"{j}×{i}={i * j:2d}", end="  ")
        print()


if __name__ == "__main__":
    print_multiplication_table()

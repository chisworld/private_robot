"""PNN Garden 原生 Live2D 桌宠（live2d-py + PySide6）。"""

__all__ = ["main"]


def main() -> None:
    from pnn.pet.window import main as _main

    _main()

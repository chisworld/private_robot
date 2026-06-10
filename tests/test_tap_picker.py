from __future__ import annotations

from pnn.pet.live2d_widget import _NoRepeatPicker


def test_no_repeat_picker_cycles_without_repeat_until_empty():
    p = _NoRepeatPicker()
    p.reset(["a", "b", "c"])
    seen: list[str] = []
    for _ in range(3):
        seen.append(p.pick())
    assert len(seen) == 3
    assert len(set(seen)) == 3
    assert p.pick() in {"a", "b", "c"}

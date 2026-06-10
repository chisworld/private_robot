"""批量校验日程口语解析（无 pytest 时也可 python -m tests.schedule_phrases_batch）。"""

from __future__ import annotations

from datetime import datetime

from pnn.pet.reminders.from_chat import parse_user_reminder_request

NOW = datetime(2026, 6, 8, 20, 0, 0)

# (用户原话, 标题应包含的片段 或 None 表示不应解析)
PHRASES: list[tuple[str, str | None]] = [
    # 睡觉 / 生活
    ("晚上11：00我们睡觉吧", "睡"),
    ("11点我们睡吧", "睡"),
    ("22:30吃药", "药"),
    ("下午三点开会别忘了", "开会"),
    ("周末一起去爬山", "爬山"),
    ("三分钟后提醒我喝水", "喝水"),
    ("每天8点叫我起床", "起床"),
    ("待会提醒我倒垃圾", "垃圾"),
    ("过会儿一起收菜", "收菜"),
    ("明天中午12点去吃黄焖鸡米饭", "黄焖鸡"),
    ("后天早上叫我起来", "起床"),
    ("下周三分组讨论", "讨论"),
    ("今晚十点追剧", "追"),
    ("一刻钟后提醒我上线", "上线"),
    ("两天后提醒我还信用卡", "信用"),
    ("九点半玩鸣潮", "鸣潮"),
    ("明早七点跑步", "跑"),
    ("下午记得接孩子", "接孩子"),
    ("8pm开会", "开会"),
    ("差10分6点叫我起床", "起床"),
    ("6月9号晚上8点看电影", "电影"),
    ("一周后提醒我还房租", "房租"),
    ("120秒后提醒我关灶", "关灶"),
    ("半小时后一起打王者", "王者"),
    ("明晚一起去吃肯德基", "肯德基"),
    ("下周五交论文", "论文"),
    ("记得明早喂猫", "喂猫"),
    ("九点提醒我做原神日常", "原神"),
    ("十二点差五分提醒我倒垃圾", "垃圾"),
    ("我们待会一起洗车", "洗车"),
    ("别忘了今晚清体力", "清体力"),
    ("后天下午三点体检", "体检"),
    ("这周末去钓鱼", "钓鱼"),
    ("10:30pm睡觉", "睡"),
    ("7:45am叫我", "起床"),
    ("两小时后提醒我还花呗", "花呗"),
    ("四点过十分开会", "开会"),
    # 不应解析
    ("今天天气不错", None),
    ("走吧一起洗澡去", None),
    ("你好呀", None),
    ("刚才吃过了", None),
]


def run_batch() -> int:
    failed = 0
    for text, expect in PHRASES:
        got = parse_user_reminder_request(text, now=NOW)
        if expect is None:
            if got is not None:
                print("FAIL expected None:", text, "->", got)
                failed += 1
            continue
        if got is None:
            print("FAIL expected match:", text)
            failed += 1
            continue
        title, start, _ = got
        if expect not in title:
            print("FAIL title:", text, "->", title, start)
            failed += 1
    print(f"batch: {len(PHRASES) - failed}/{len(PHRASES)} ok")
    return failed


if __name__ == "__main__":
    raise SystemExit(run_batch())

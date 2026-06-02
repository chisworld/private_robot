from __future__ import annotations

import argparse

from pnn.core.logging import setup_logging
from pnn.tts.service import tts_service


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TTS 语音合成（与 AI_assistant 相同引擎）")
    parser.add_argument("text", nargs="?", help="要合成的文本")
    parser.add_argument("-o", "--output", help="输出 wav 文件路径")
    parser.add_argument(
        "--provider",
        default="gpt-sovits",
        choices=["gpt-sovits", "genie-tts", "index-tts", "cosyvoice"],
        help="TTS 引擎",
    )
    parser.add_argument("--server-url", default="http://127.0.0.1:9880", help="TTS API 地址")
    parser.add_argument("--work-path", help="TTS 整合包目录")
    parser.add_argument("--gpt-model", help="GPT 权重 .ckpt 路径")
    parser.add_argument("--sovits-model", help="SoVITS 权重 .pth 路径")
    parser.add_argument("--ref-audio", help="参考音频路径")
    parser.add_argument("--prompt-text", default="", help="参考音频对应文本")
    parser.add_argument("--prompt-lang", default="zh", help="参考音频语言")
    parser.add_argument("--text-lang", default="zh", help="合成文本语言")
    parser.add_argument("--speed", type=float, default=1.0, help="语速倍率")
    parser.add_argument("--api-key", help="CosyVoice API Key")
    parser.add_argument("--character", help="Genie TTS 角色名")
    parser.add_argument("--start-server", action="store_true", help="仅启动本地 TTS 服务")
    parser.add_argument("--check", action="store_true", help="检查 TTS 服务是否在线")
    return parser


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    parser = build_parser()
    args = parser.parse_args(argv)

    patch = {
        "provider": args.provider,
        "server_url": args.server_url,
        "text_lang": args.text_lang,
        "prompt_lang": args.prompt_lang,
        "speed_factor": args.speed,
    }
    if args.work_path:
        patch["work_path"] = args.work_path
    if args.api_key:
        patch["api_key"] = args.api_key
    if args.character:
        patch["character_name"] = args.character
    if args.gpt_model:
        patch["gpt_model_path"] = args.gpt_model
    if args.sovits_model:
        patch["sovits_model_path"] = args.sovits_model
    if args.ref_audio:
        patch["ref_audio_path"] = args.ref_audio
    if args.prompt_text:
        patch["prompt_text"] = args.prompt_text
    tts_service.update_config(**patch)

    if args.check:
        result = tts_service.check_server()
        print(result)
        return 0 if result.get("ok") else 1

    if args.start_server:
        result = tts_service.start_server()
        print(result)
        return 0 if result.get("ok") else 1

    if not args.text:
        parser.error("请提供要合成的文本，或使用 --start-server / --check")

    path = tts_service.synthesize(args.text, output_path=args.output)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

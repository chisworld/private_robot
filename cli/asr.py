from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pnn.asr.stream import StreamConfig, StreamingASR
from pnn.asr.transcriber import ASRTranscriber
from pnn.core.paths import resolve_local_model_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="faster-whisper 语音识别转文字")
    parser.add_argument(
        "audio",
        nargs="?",
        help="音频文件路径；省略时使用 --mic 或 --stream",
    )
    parser.add_argument("--mic", action="store_true", help="从麦克风录音固定时长并识别")
    parser.add_argument("--stream", action="store_true", help="麦克风实时流式识别（Ctrl+C 结束）")
    parser.add_argument("--duration", type=float, default=5.0, help="--mic 模式录音时长（秒）")
    parser.add_argument(
        "--model", default="small", help="模型大小，如 tiny/base/small/medium/large-v3"
    )
    parser.add_argument("--model-path", help="本地已下载模型目录，指定后优先于 --model")
    parser.add_argument("--download-root", help="模型下载缓存目录")
    parser.add_argument(
        "--device", default="auto", choices=["auto", "cpu", "cuda"], help="推理设备"
    )
    parser.add_argument("--compute-type", default="default", help="计算精度，如 int8/float16")
    parser.add_argument("--language", default=None, help="语言代码，如 zh/en；默认自动检测")
    parser.add_argument(
        "--task", default="transcribe", choices=["transcribe", "translate"], help="转写或翻译为英文"
    )
    parser.add_argument("--output", "-o", help="输出文本文件路径")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出分段结果")
    parser.add_argument("--no-vad", action="store_true", help="关闭 VAD 过滤")
    parser.add_argument(
        "--input-device", type=int, default=None, help="麦克风设备编号，默认系统默认设备"
    )
    parser.add_argument(
        "--silence", type=float, default=0.8, help="流式模式：判定一句话结束的静音时长（秒）"
    )
    parser.add_argument(
        "--partial-interval", type=float, default=1.2, help="流式模式：partial 结果刷新间隔（秒）"
    )
    parser.add_argument("--list-devices", action="store_true", help="列出可用音频输入设备")
    return parser


def run_stream(args: argparse.Namespace, transcriber: ASRTranscriber) -> int:
    finals: list[str] = []

    def on_partial(text: str) -> None:
        print(f"\r[识别中] {text}", end="", flush=True, file=sys.stderr)

    def on_final(text: str) -> None:
        finals.append(text)
        print(file=sys.stderr)
        print(text, flush=True)

    def on_status(status: str) -> None:
        if status == "listening":
            print("[等待说话…]", file=sys.stderr)

    stream = StreamingASR(
        transcriber.model,
        language=args.language,
        task=args.task,
        config=StreamConfig(
            silence_duration=args.silence,
            partial_interval=args.partial_interval,
        ),
        on_partial=on_partial,
        on_final=on_final,
        on_status=on_status,
        input_device=args.input_device,
        vad_filter=not args.no_vad,
    )

    print(
        "实时流式识别已启动，对着麦克风说话；停顿后会输出完整句子。按 Ctrl+C 结束。",
        file=sys.stderr,
    )
    stream.start()
    try:
        while True:
            import time

            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\n正在停止…", file=sys.stderr)
        stream.stop()

    if args.output and finals:
        Path(args.output).write_text("\n".join(finals), encoding="utf-8")
        print(f"已写入: {args.output}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_devices:
        import sounddevice as sd

        print(sd.query_devices())
        return 0

    if not args.stream and not args.mic and not args.audio:
        parser.error("请提供音频文件路径，或使用 --mic / --stream")

    transcriber = ASRTranscriber(
        model_size=args.model,
        device=args.device,
        compute_type=args.compute_type,
        download_root=args.download_root,
        model_path=args.model_path or resolve_local_model_path(args.model),
    )

    if args.stream:
        return run_stream(args, transcriber)

    if args.mic:
        print(f"正在录音 {args.duration} 秒…", file=sys.stderr)
        result = transcriber.transcribe_microphone(
            duration=args.duration,
            language=args.language,
            task=args.task,
            vad_filter=not args.no_vad,
        )
    else:
        result = transcriber.transcribe_file(
            args.audio,
            language=args.language,
            task=args.task,
            vad_filter=not args.no_vad,
        )

    if args.json:
        payload = {
            "text": result.text,
            "language": result.language,
            "language_probability": result.language_probability,
            "duration": result.duration,
            "segments": [
                {"start": segment.start, "end": segment.end, "text": segment.text}
                for segment in result.segments
            ],
        }
        output_text = json.dumps(payload, ensure_ascii=False, indent=2)
    else:
        output_text = result.text

    if args.output:
        Path(args.output).write_text(output_text, encoding="utf-8")
        print(f"已写入: {args.output}", file=sys.stderr)
    else:
        print(output_text)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# ASR（语音识别）

ASR 已整合进 **private_robot** 主项目。

仓库：<https://github.com/chisworld/private_robot>

## 启动

```powershell
python scripts/launcher.py --page asr
python cli/asr.py --stream --language zh
python cli/asr.py --mic --language zh
python cli/asr.py audio.wav
```

## 模型

```
models/ASR/whisper/faster_whisper_small/
```

下载：[docs/MODEL_DOWNLOADS.md](../docs/MODEL_DOWNLOADS.md)

模块：`pnn/asr/`

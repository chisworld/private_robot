"""TTS 适配器实现（移植自 AI_assistant/tts/tts_adapter.py）。"""

from __future__ import annotations

import array
import base64
import logging
import math
import os
import subprocess
import time
import wave
from pathlib import Path

import requests

from pnn.tts.base import TTSAdapter
from pnn.core.runtime_files import alloc_runtime_path
from pnn.tts.paths import resolve_gpt_sovits_python
from pnn.tts.process_util import kill_server_on_url
from pnn.tts.probe import probe_http_server
from pnn.tts.text_sanitize import sanitize_for_gbk_tts

logger = logging.getLogger(__name__)


def _norm_weight_path(path: str) -> str:
    raw = (path or "").strip()
    if not raw:
        return ""
    try:
        return str(Path(raw).resolve()).replace("\\", "/")
    except OSError:
        return raw.replace("\\", "/")


class GPTSoVitsAdapter(TTSAdapter):
    """GPT-SoVITS TTS 适配器。"""

    def __init__(
        self,
        tts_server_url: str = "http://127.0.0.1:9880/",
        gpt_sovits_work_path: str | None = None,
        *,
        python_executable: str | None = None,
        auto_start: bool = True,
    ):
        self.tts_server_url = tts_server_url.rstrip("/") + "/"
        self.sovits_model_path = ""
        self.gpt_model_path = ""
        self.gpt_sovits_work_path = gpt_sovits_work_path
        self.python_executable = (python_executable or "").strip() or None
        self._server_process = None
        self._boot_log_handle = None
        self._http = requests.Session()
        self._last_error: str | None = None

        if self.gpt_sovits_work_path and str(self.gpt_sovits_work_path).endswith(".py"):
            self.gpt_sovits_work_path = Path(self.gpt_sovits_work_path).parent.as_posix()

        if auto_start:
            self._start_server_process()

    def stop_server(self) -> None:
        if self._server_process is not None:
            try:
                self._server_process.terminate()
                self._server_process.wait(timeout=5)
            except Exception:
                try:
                    self._server_process.kill()
                except Exception:
                    pass
            self._server_process = None
        if self._boot_log_handle is not None:
            try:
                self._boot_log_handle.close()
            except OSError:
                pass
            self._boot_log_handle = None
        kill_server_on_url(self.tts_server_url)

    def _start_server_process(self, *, force_restart: bool = False) -> None:
        if force_restart:
            self.stop_server()
            self.gpt_model_path = ""
            self.sovits_model_path = ""
            time.sleep(1.0)
        elif probe_http_server(self.tts_server_url):
            logger.info("GPT-SoVITS server is already running.")
            return
        logger.info("GPT-SoVITS server not found, attempting to start...")

        if self.gpt_sovits_work_path is None:
            raise RuntimeError("未配置 GPT-SoVITS work_path")

        if self._server_process is not None and self._server_process.poll() is None:
            logger.info("GPT-SoVITS server process already starting.")
            return

        os_path = self.gpt_sovits_work_path
        embeded_python_path = str(
            resolve_gpt_sovits_python(os_path, self.python_executable)
        )
        api_path = os.path.join(os_path, "api_v2.py")
        boot_log = os.path.join(os_path, "gpt_sovits_boot.log")
        if self._boot_log_handle is not None:
            try:
                self._boot_log_handle.close()
            except OSError:
                pass
        self._boot_log_handle = open(boot_log, "a", encoding="utf-8", errors="replace")

        self._server_process = subprocess.Popen(
            [embeded_python_path, api_path],
            cwd=os_path,
            stdout=self._boot_log_handle,
            stderr=subprocess.STDOUT,
        )
        logger.info(
            "GPT-SoVITS server starting… python=%s 日志: %s",
            embeded_python_path,
            boot_log,
        )

    def generate_speech(self, text, file_path=None, **kwargs):
        # Normalize Windows backslashes to forward slashes for the API
        ref_path = kwargs.get("ref_audio_path", "")
        if ref_path:
            ref_path = ref_path.replace("\\", "/")
        text_lang = kwargs.get("text_lang", "ja") or "ja"
        prompt_lang = kwargs.get("prompt_lang", "") or text_lang
        safe_text = sanitize_for_gbk_tts(text or "", text_lang)
        safe_prompt = sanitize_for_gbk_tts(kwargs.get("prompt_text", "") or "", prompt_lang)
        if not safe_text.strip():
            self._last_error = "清理后合成文本为空"
            logger.error("GPT-SoVITS TTS skipped: empty text after sanitize")
            return None
        split_method = "cut5" if text_lang == "ja" and len(safe_text) > 80 else "cut0"
        params = {
            "ref_audio_path": ref_path,
            "prompt_text": safe_prompt,
            "prompt_lang": prompt_lang,
            "text": safe_text,
            "text_lang": text_lang,
            "text_split_method": split_method,
            "batch_size": 1,
            "speed_factor": kwargs.get("speed_factor", 1.4),
        }

        try:
            self._last_error = None
            response = self._http.post(self.tts_server_url + "tts", json=params, timeout=300)
            if not response.ok:
                detail = response.text[:500]
                self._last_error = f"HTTP {response.status_code}: {detail}"
                logger.error("GPT-SoVITS TTS failed (%s): %s", response.status_code, detail)
                return None
            response.raise_for_status()

            if not file_path:
                file_path = str(alloc_runtime_path(".wav", subdir="tts"))

            with open(file_path, "wb") as f:
                f.write(response.content)

            return os.path.abspath(file_path)
        except Exception as exc:
            self._last_error = str(exc)
            logger.error("GPT-SoVITS TTS generation failed: %s", exc)
            return None

    def switch_model(self, model_info):
        gpt_model_path = _norm_weight_path(model_info.get("gpt_model_path", ""))
        sovits_model_path = _norm_weight_path(model_info.get("sovits_model_path", ""))

        if (
            _norm_weight_path(self.sovits_model_path) == sovits_model_path
            and _norm_weight_path(self.gpt_model_path) == gpt_model_path
        ):
            logger.debug("No model switch needed.")
            return

        try:
            if gpt_model_path and gpt_model_path.endswith(".ckpt"):
                response = self._http.get(
                    self.tts_server_url + "set_gpt_weights",
                    params={"weights_path": gpt_model_path},
                    timeout=600,
                )
                response.raise_for_status()
                self.gpt_model_path = gpt_model_path
                logger.info("gpt model switched successfully: %s", gpt_model_path)
        except Exception as exc:
            logger.error("Failed to switch gpt model: %s", exc)

        try:
            if sovits_model_path and sovits_model_path.endswith(".pth"):
                response = self._http.get(
                    self.tts_server_url + "set_sovits_weights",
                    params={"weights_path": sovits_model_path},
                    timeout=600,
                )
                response.raise_for_status()
                self.sovits_model_path = sovits_model_path
                logger.info("sovits model switched successfully: %s", sovits_model_path)
        except Exception as exc:
            logger.error("Failed to switch sovits model: %s", exc)


class IndexTTSAdapter(TTSAdapter):
    def __init__(
        self,
        index_server_url: str = "http://localhost:9880/",
        index_server_work_path: str | None = None,
        *,
        auto_start: bool = True,
    ):
        self.index_server_url = index_server_url
        self.current_model = None
        self._server_process = None
        self.gpt_sovits_work_path = index_server_work_path

        if auto_start:
            self._start_server_process()

    def stop_server(self) -> None:
        if self._server_process is not None:
            try:
                self._server_process.terminate()
                self._server_process.wait(timeout=5)
            except Exception:
                try:
                    self._server_process.kill()
                except Exception:
                    pass
            self._server_process = None

    def _start_server_process(self) -> None:
        try:
            response = requests.get(self.index_server_url, timeout=2.0)
            if response.status_code == 200:
                logger.info("Index TTS server is already running.")
                return
        except requests.exceptions.ConnectionError:
            logger.info("Index TTS server not found, attempting to start...")

        if self.gpt_sovits_work_path is None:
            return

        os_path = self.gpt_sovits_work_path
        embeded_python_path = os.path.join(os_path, "runtime", "python.exe")
        api_path = os.path.join(os_path, "api_v2.py")

        self._server_process = subprocess.Popen([embeded_python_path, api_path], cwd=os_path)
        logger.info("Index TTS server starting...")

    def generate_speech(self, text, file_path=None, **kwargs):
        try:
            params = {
                "text": text,
                "model_id": self.current_model,
                "voice_name": kwargs.get("voice_name", "default"),
                "language": kwargs.get("text_lang", "ja"),
            }
            response = requests.post(self.index_server_url + "generate", json=params, timeout=300)
            response.raise_for_status()

            if not file_path:
                file_path = str(alloc_runtime_path(".wav", subdir="tts"))

            with open(file_path, "wb") as f:
                f.write(response.content)

            return os.path.abspath(file_path)
        except Exception as exc:
            logger.error("Index TTS generation failed: %s", exc)
            return None

    def switch_model(self, model_info):
        model_id = model_info.get("model_id")
        if model_id and self.current_model != model_id:
            logger.info("Switching to Index TTS model: %s", model_id)
            self.current_model = model_id


class CosyVoiceAdapter(TTSAdapter):
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.current_model = "cosyvoice-v2"
        self.current_voice = "longxiaochun_v2"

    def generate_speech(self, text, file_path=None, **kwargs):
        api_url = "https://dashscope.aliyuncs.com/api/v1/tts/cosyvoice"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        params = {
            "model": kwargs.get("model", self.current_model),
            "voice": kwargs.get("voice", self.current_voice),
            "text": text,
        }

        try:
            response = requests.post(api_url, headers=headers, json=params, timeout=300)
            response.raise_for_status()

            if not file_path:
                file_path = str(alloc_runtime_path(".wav", subdir="tts"))

            with open(file_path, "wb") as f:
                f.write(response.content)

            return os.path.abspath(file_path)
        except Exception as exc:
            logger.error("CosyVoice TTS generation failed: %s", exc)
            return None

    def switch_model(self, model_info):
        voice = model_info.get("voice")
        model = model_info.get("model")

        if voice:
            self.current_voice = voice
            logger.info("CosyVoice voice switched to: %s", self.current_voice)
        if model:
            self.current_model = model
            logger.info("CosyVoice model switched to: %s", self.current_model)


class GenieTTSAdapter(TTSAdapter):
    def __init__(
        self,
        tts_server_url: str = "http://127.0.0.1:9880/",
        tts_work_path: str | None = None,
        gpt_sovits_work_path: str | None = None,
        *,
        auto_start: bool = True,
    ):
        self.tts_server_url = tts_server_url.rstrip("/") + "/"
        self.tts_work_path = tts_work_path or gpt_sovits_work_path
        self.character_name = None
        self.onnx_model_dir = None
        self.loaded_character_name = None
        self.reference_audio_key = None
        self._server_process = None
        if auto_start:
            self._start_server_process()

    def stop_server(self) -> None:
        if self._server_process is not None:
            try:
                self._server_process.terminate()
                self._server_process.wait(timeout=5)
            except Exception:
                try:
                    self._server_process.kill()
                except Exception:
                    pass
            self._server_process = None

    @staticmethod
    def _encode_name(name: str) -> str:
        if not name:
            return ""
        return base64.urlsafe_b64encode(name.encode("utf-8")).decode("ascii").rstrip("=")

    def _resolve_converter_script(self):
        if not self.tts_work_path:
            return None
        base_path = Path(self.tts_work_path)
        if base_path.suffix.lower() == ".py":
            return base_path if base_path.exists() else None
        candidates = [base_path / "convert.py", base_path / "convery.py"]
        for script in candidates:
            if script.exists():
                return script
        return None

    def _has_onnx_files(self, onnx_dir: str) -> bool:
        if not onnx_dir:
            return False
        onnx_path = Path(onnx_dir)
        if not onnx_path.exists() or not onnx_path.is_dir():
            return False
        return any(p.suffix.lower() == ".onnx" for p in onnx_path.glob("*.onnx"))

    def _convert_model_to_onnx(
        self, character_name: str, ckpt_model_path: str, pth_model_path: str, onnx_dir: str
    ):
        converter_script = self._resolve_converter_script()
        if converter_script is None:
            raise FileNotFoundError("Cannot find convert.py/convery.py in tts_work_path.")

        work_path = converter_script.parent
        embedded_python_path = work_path / "runtime" / "python.exe"
        if not embedded_python_path.exists():
            raise FileNotFoundError(f"Runtime python not found: {embedded_python_path}")

        Path(onnx_dir).mkdir(parents=True, exist_ok=True)
        cmd = [
            str(embedded_python_path),
            str(converter_script),
            "--pth",
            pth_model_path,
            "--ckpt",
            ckpt_model_path,
            "--out",
            onnx_dir,
        ]
        logger.info("Converting ONNX for '%s' ...", character_name)
        result = subprocess.run(
            cmd, cwd=str(work_path), capture_output=True, text=True, timeout=600
        )
        if result.returncode != 0:
            msg = (
                f"Convert failed (code={result.returncode}).\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
            raise RuntimeError(msg)
        logger.info("ONNX convert finished for '%s': %s", character_name, onnx_dir)

    def _is_valid_wav_file(self, file_path: str) -> bool:
        if not file_path or not os.path.exists(file_path):
            return False
        try:
            with wave.open(file_path, "rb") as wav_f:
                wav_f.getnchannels()
                wav_f.getframerate()
                wav_f.getnframes()
            return True
        except Exception:
            return False

    def _write_raw_stream_as_wav(
        self, raw_bytes: bytes, out_path: str, sample_rate: int = 32000
    ) -> bool:
        if not raw_bytes:
            return False
        pcm_bytes = b""

        if len(raw_bytes) % 4 == 0:
            try:
                float_arr = array.array("f")
                float_arr.frombytes(raw_bytes)
                if float_arr:
                    max_abs = max(abs(x) for x in float_arr if math.isfinite(x))
                    if max_abs <= 2.0:
                        pcm_i16 = array.array("h")
                        for x in float_arr:
                            if not math.isfinite(x):
                                x = 0.0
                            if x > 1.0:
                                x = 1.0
                            elif x < -1.0:
                                x = -1.0
                            pcm_i16.append(int(x * 32767.0))
                        pcm_bytes = pcm_i16.tobytes()
            except Exception:
                pcm_bytes = b""

        if not pcm_bytes and len(raw_bytes) % 2 == 0:
            pcm_bytes = raw_bytes

        if not pcm_bytes:
            return False

        try:
            with wave.open(out_path, "wb") as wav_f:
                wav_f.setnchannels(1)
                wav_f.setsampwidth(2)
                wav_f.setframerate(sample_rate)
                wav_f.writeframes(pcm_bytes)
            return self._is_valid_wav_file(out_path)
        except Exception:
            return False

    def _write_pcm_chunks_as_wav(self, chunks, out_path: str, sample_rate: int = 32000) -> bool:
        try:
            with wave.open(out_path, "wb") as wav_f:
                wav_f.setnchannels(1)
                wav_f.setsampwidth(2)
                wav_f.setframerate(sample_rate)
                for chunk in chunks:
                    if chunk:
                        wav_f.writeframesraw(chunk)
            return self._is_valid_wav_file(out_path)
        except Exception:
            return False

    def _start_server_process(self) -> None:
        if self._is_server_alive():
            logger.info("Genie TTS server is already running.")
            return

        if not self.tts_work_path:
            logger.warning("Genie TTS work path is empty, cannot auto start server.")
            return

        os_path = self.tts_work_path
        if os_path.endswith(".py"):
            os_path = str(Path(os_path).parent)

        embedded_python_path = os.path.join(os_path, "runtime", "python.exe")
        start_script_path = os.path.join(os_path, "start.py")

        if not os.path.exists(embedded_python_path):
            logger.error("Genie TTS runtime not found: %s", embedded_python_path)
            return
        if not os.path.exists(start_script_path):
            logger.error("Genie TTS start.py not found: %s", start_script_path)
            return

        self._server_process = subprocess.Popen(
            [embedded_python_path, start_script_path], cwd=os_path
        )
        logger.info("Genie TTS server starting...")
        for _ in range(20):
            time.sleep(0.5)
            if self._is_server_alive():
                logger.info("Genie TTS server started successfully.")
                return
        logger.warning("Genie TTS server start timeout, continue and retry on request.")

    def _is_server_alive(self) -> bool:
        try:
            response = requests.post(self.tts_server_url + "stop", timeout=1.5)
            return response.status_code in (200, 204, 405)
        except Exception:
            return False

    def _load_character_model(self, language: str = "ja") -> None:
        if not self.character_name or not self.onnx_model_dir:
            logger.warning("Genie TTS switch_model missing character_name/onnx_model_dir.")
            return
        try:
            encoded_character_name = self._encode_name(self.character_name)
            payload = {
                "character_name": encoded_character_name,
                "onnx_model_dir": self.onnx_model_dir,
                "language": language,
            }
            response = requests.post(
                self.tts_server_url + "load_character", json=payload, timeout=20
            )
            response.raise_for_status()
            self.loaded_character_name = self.character_name
            logger.info("Genie TTS character '%s' loaded successfully.", self.character_name)
        except Exception as exc:
            logger.error("Failed to load Genie TTS character model: %s", exc)
            raise

    def generate_speech(self, text, file_path=None, **kwargs):
        runtime_character_name = kwargs.get("character_name")
        if runtime_character_name and runtime_character_name != self.character_name:
            self.character_name = runtime_character_name

        if not self.character_name:
            logger.error("Genie TTS has no active character. Call switch_model first.")
            return None

        ref_audio_path = kwargs.get("ref_audio_path")
        audio_text = kwargs.get("prompt_text")
        audio_lang = kwargs.get("prompt_lang") or kwargs.get("text_lang") or "zh"
        reference_audio_key = f"{ref_audio_path}|{audio_text}|{audio_lang}"
        encoded_character_name = self._encode_name(self.character_name)

        if self.loaded_character_name != self.character_name:
            self._load_character_model(audio_lang)

        if ref_audio_path and audio_text and self.reference_audio_key != reference_audio_key:
            try:
                payload = {
                    "character_name": encoded_character_name,
                    "audio_path": ref_audio_path,
                    "audio_text": audio_text,
                    "language": audio_lang,
                }
                response = requests.post(
                    self.tts_server_url + "set_reference_audio", json=payload, timeout=20
                )
                response.raise_for_status()
                self.reference_audio_key = reference_audio_key
                logger.info("Genie TTS reference audio set successfully.")
            except Exception as exc:
                logger.error("Failed to set Genie TTS reference audio: %s", exc)

        try:
            if not file_path:
                file_path = str(alloc_runtime_path(".wav", subdir="tts"))

            abs_file_path = os.path.abspath(file_path)
            payload = {
                "character_name": encoded_character_name,
                "text": text,
                "split_sentence": False,
            }
            with requests.post(
                self.tts_server_url + "tts", json=payload, stream=True, timeout=120
            ) as response:
                response.raise_for_status()
                chunks = [chunk for chunk in response.iter_content(chunk_size=4096) if chunk]

            if not chunks:
                logger.error("Genie TTS returned empty audio stream.")
                return None

            first_bytes = chunks[0][:16]
            is_riff = first_bytes[:4] == b"RIFF"
            if is_riff:
                with open(abs_file_path, "wb") as f:
                    for chunk in chunks:
                        f.write(chunk)
            else:
                if not self._write_pcm_chunks_as_wav(chunks, abs_file_path, sample_rate=32000):
                    raw_bytes = b"".join(chunks)
                    if not self._write_raw_stream_as_wav(
                        raw_bytes, abs_file_path, sample_rate=32000
                    ):
                        logger.error("Genie TTS output is not valid WAV and conversion failed.")
                        return None

            if not os.path.exists(abs_file_path):
                logger.error("Genie TTS did not create output file: %s", abs_file_path)
                return None

            return abs_file_path
        except Exception as exc:
            logger.error("Genie TTS generation failed: %s", exc)
            return None

    def switch_model(self, model_info):
        if model_info is None:
            logger.warning("Genie TTS switch_model got empty model_info.")
            return
        new_character_name = model_info.get("character_name") or model_info.get("name")
        ckpt_model_path = model_info.get("gpt_model_path")
        pth_model_path = model_info.get("sovits_model_path")
        new_onnx_model_dir = model_info.get("onnx_model_dir")
        encoded_character_name = self._encode_name(new_character_name) if new_character_name else ""

        if not new_onnx_model_dir and encoded_character_name:
            new_onnx_model_dir = str((Path("onnx") / encoded_character_name).resolve())

        if new_onnx_model_dir and not self._has_onnx_files(new_onnx_model_dir):
            if ckpt_model_path and pth_model_path:
                try:
                    self._convert_model_to_onnx(
                        character_name=new_character_name or "unknown",
                        ckpt_model_path=ckpt_model_path,
                        pth_model_path=pth_model_path,
                        onnx_dir=new_onnx_model_dir,
                    )
                except Exception as exc:
                    logger.error("Auto convert ONNX failed: %s", exc)
            else:
                logger.warning("ONNX dir missing and no ckpt/pth path provided.")

        if new_onnx_model_dir and self.onnx_model_dir != new_onnx_model_dir:
            self.onnx_model_dir = new_onnx_model_dir
            self.loaded_character_name = None

        if new_character_name and self.character_name != new_character_name:
            self.character_name = new_character_name
            self.loaded_character_name = None

        if (
            self.character_name
            and self.onnx_model_dir
            and self.loaded_character_name != self.character_name
        ):
            logger.info("Switching Genie TTS character to: %s", self.character_name)
            self._load_character_model()

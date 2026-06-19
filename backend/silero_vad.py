"""Silero 前置 VAD：转录前切出语音段，切除静音、抑制幻觉/重复。

为什么需要：mlx-whisper（同 openai-whisper）在纯静音/噪音段上容易产生幻觉与
连环重复（Phase 0 实测复现："我会继续来到" 重复）。在喂给 ASR 前用 Silero VAD
切除非语音段，是 2026 长音频转录的标准抗幻觉手段，顺带跳过静音 → 进一步提速。

实现取舍：直接用 onnxruntime 跑 vendored 的 ``silero_vad_v6.onnx``（见
``backend/assets/``），**不引入官方 silero-vad 包**——后者硬依赖 torch（~440MB，
已在打包中排除）。下面的 VAD 算法移植自 faster-whisper 的 ``vad.py``（其又改编自
silero-vad，均为宽松许可：silero-vad MIT / faster-whisper MIT），仅去掉对
faster_whisper.utils 的依赖、改为从本仓库资产目录定位模型。

时间轴：VAD 产出语音段后转成 mlx_whisper 的 ``clip_timestamps`` 参数喂给 ASR——
mlx 直接在*原始音频*上只转录这些区间、跳过静音，输出的时间戳天然就是原始时间轴，
因此**无需拼接音频、也无需回映**（拼接会引入接缝伪影导致 mlx 提前停转，实测坐实）。
"""
from __future__ import annotations

import functools
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import numpy as np

logger = logging.getLogger(__name__)

VAD_ASSET_NAME = "silero_vad_v6.onnx"


def _resolve_asset_path() -> str:
    """定位 vendored 的 silero VAD onnx 模型。

    dev：``backend/assets/silero_vad_v6.onnx``（与本文件同级的 assets/）。
    打包(frozen)：PyInstaller 把资产收到 ``_MEIPASS/assets`` 或 macOS .app 的
    ``Contents/Resources/assets``；两处都探一下，避免符号链接缺失导致找不到。
    """
    candidates = [Path(__file__).resolve().parent / "assets" / VAD_ASSET_NAME]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        mp = Path(meipass)
        candidates += [
            mp / "assets" / VAD_ASSET_NAME,
            mp / "backend" / "assets" / VAD_ASSET_NAME,
            mp.parent / "Resources" / "assets" / VAD_ASSET_NAME,
        ]
    for c in candidates:
        if c.is_file():
            return str(c)
    raise FileNotFoundError(
        f"找不到 VAD 模型 {VAD_ASSET_NAME}；探测路径: {[str(c) for c in candidates]}"
    )


# The code below is adapted from https://github.com/snakers4/silero-vad
# (via faster-whisper's vad.py). Both are MIT-licensed.
@dataclass
class VadOptions:
    """VAD 选项。

    threshold：语音概率阈值，≥ 视为语音；0.5 是大多数数据集的稳妥默认值。
    neg_threshold：静音阈值（判定语音结束）；None 时取 max(threshold-0.15, 0.01)。
    min_speech_duration_ms：短于此的语音段丢弃。
    max_speech_duration_s：超长语音段在最后一次 >100ms 静音处切分，防止激进切割。
    min_silence_duration_ms：语音段结束前需等待的静音时长（默认放宽到 500ms，
        与本项目此前的 faster-whisper 配置一致，比上游 2000ms 更灵敏）。
    speech_pad_ms：每个语音段两侧各留白，避免边界吞字。
    """

    threshold: float = 0.5
    neg_threshold: Optional[float] = None
    min_speech_duration_ms: int = 250
    max_speech_duration_s: float = float("inf")
    min_silence_duration_ms: int = 500
    speech_pad_ms: int = 400


def get_speech_timestamps(
    audio: np.ndarray,
    vad_options: Optional[VadOptions] = None,
    sampling_rate: int = 16000,
    **kwargs,
) -> List[dict]:
    """用 silero VAD 把长音频切成语音块。

    Args:
      audio: 一维 float32 数组（16kHz 单声道）。
      vad_options: VAD 处理选项。
      sampling_rate: 采样率。

    Returns:
      每个语音块的 {start, end}（样本点，相对于传入的 audio）。
    """
    if vad_options is None:
        vad_options = VadOptions(**kwargs)

    threshold = vad_options.threshold
    neg_threshold = vad_options.neg_threshold
    min_speech_duration_ms = vad_options.min_speech_duration_ms
    max_speech_duration_s = vad_options.max_speech_duration_s
    min_silence_duration_ms = vad_options.min_silence_duration_ms
    window_size_samples = 512
    speech_pad_ms = vad_options.speech_pad_ms
    min_speech_samples = sampling_rate * min_speech_duration_ms / 1000
    speech_pad_samples = sampling_rate * speech_pad_ms / 1000
    max_speech_samples = (
        sampling_rate * max_speech_duration_s
        - window_size_samples
        - 2 * speech_pad_samples
    )
    min_silence_samples = sampling_rate * min_silence_duration_ms / 1000
    min_silence_samples_at_max_speech = sampling_rate * 98 / 1000

    audio_length_samples = len(audio)

    model = get_vad_model()

    padded_audio = np.pad(
        audio, (0, window_size_samples - audio.shape[0] % window_size_samples)
    )
    speech_probs = model(padded_audio)

    triggered = False
    speeches: List[dict] = []
    current_speech: dict = {}
    if neg_threshold is None:
        neg_threshold = max(threshold - 0.15, 0.01)

    # 暂存潜在的段结束点（容忍少量静音）
    temp_end = 0
    # 达到最大段长时暂存的边界
    prev_end = next_start = 0

    for i, speech_prob in enumerate(speech_probs):
        if (speech_prob >= threshold) and temp_end:
            temp_end = 0
            if next_start < prev_end:
                next_start = window_size_samples * i

        if (speech_prob >= threshold) and not triggered:
            triggered = True
            current_speech["start"] = window_size_samples * i
            continue

        if (
            triggered
            and (window_size_samples * i) - current_speech["start"] > max_speech_samples
        ):
            if prev_end:
                current_speech["end"] = prev_end
                speeches.append(current_speech)
                current_speech = {}
                # 之前到过静音(< neg_thres)且仍非语音(< thres)
                if next_start < prev_end:
                    triggered = False
                else:
                    current_speech["start"] = next_start
                prev_end = next_start = temp_end = 0
            else:
                current_speech["end"] = window_size_samples * i
                speeches.append(current_speech)
                current_speech = {}
                prev_end = next_start = temp_end = 0
                triggered = False
                continue

        if (speech_prob < neg_threshold) and triggered:
            if not temp_end:
                temp_end = window_size_samples * i
            # 避免在极短静音处切分
            if (window_size_samples * i) - temp_end > min_silence_samples_at_max_speech:
                prev_end = temp_end
            if (window_size_samples * i) - temp_end < min_silence_samples:
                continue
            else:
                current_speech["end"] = temp_end
                if (
                    current_speech["end"] - current_speech["start"]
                ) > min_speech_samples:
                    speeches.append(current_speech)
                current_speech = {}
                prev_end = next_start = temp_end = 0
                triggered = False
                continue

    if (
        current_speech
        and (audio_length_samples - current_speech["start"]) > min_speech_samples
    ):
        current_speech["end"] = audio_length_samples
        speeches.append(current_speech)

    for i, speech in enumerate(speeches):
        if i == 0:
            speech["start"] = int(max(0, speech["start"] - speech_pad_samples))
        if i != len(speeches) - 1:
            silence_duration = speeches[i + 1]["start"] - speech["end"]
            if silence_duration < 2 * speech_pad_samples:
                speech["end"] += int(silence_duration // 2)
                speeches[i + 1]["start"] = int(
                    max(0, speeches[i + 1]["start"] - silence_duration // 2)
                )
            else:
                speech["end"] = int(
                    min(audio_length_samples, speech["end"] + speech_pad_samples)
                )
                speeches[i + 1]["start"] = int(
                    max(0, speeches[i + 1]["start"] - speech_pad_samples)
                )
        else:
            speech["end"] = int(
                min(audio_length_samples, speech["end"] + speech_pad_samples)
            )

    return speeches


def to_clip_timestamps(
    speech: List[dict], sampling_rate: int = 16000, ndigits: int = 2
) -> List[float]:
    """把语音段（样本点）转成 mlx_whisper.transcribe 的 ``clip_timestamps`` 列表。

    形如 [start0, end0, start1, end1, ...]（秒）。mlx 据此只转录这些区间、跳过静音，
    输出时间戳即原始时间轴——无需拼接音频或回映。
    """
    clip: List[float] = []
    for s in speech:
        clip.append(round(s["start"] / sampling_rate, ndigits))
        clip.append(round(s["end"] / sampling_rate, ndigits))
    return clip


@functools.lru_cache
def get_vad_model() -> "SileroVADModel":
    """返回（缓存的）VAD 模型实例。"""
    return SileroVADModel(_resolve_asset_path())


class SileroVADModel:
    """silero VAD v6 的 onnxruntime 封装（批量一次性推理整段窗口）。"""

    def __init__(self, path: str):
        import onnxruntime

        opts = onnxruntime.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.enable_cpu_mem_arena = False
        opts.log_severity_level = 4

        self.session = onnxruntime.InferenceSession(
            path,
            providers=["CPUExecutionProvider"],
            sess_options=opts,
        )

    def __call__(
        self, audio: np.ndarray, num_samples: int = 512, context_size_samples: int = 64
    ) -> np.ndarray:
        assert audio.ndim == 1, "Input should be a 1D array"
        assert (
            audio.shape[0] % num_samples == 0
        ), "Input size should be a multiple of num_samples"

        h = np.zeros((1, 1, 128), dtype="float32")
        c = np.zeros((1, 1, 128), dtype="float32")

        batched_audio = audio.reshape(-1, num_samples)
        context = batched_audio[..., -context_size_samples:]
        context[-1] = 0
        context = np.roll(context, 1, 0)
        batched_audio = np.concatenate([context, batched_audio], 1)
        batched_audio = batched_audio.reshape(-1, num_samples + context_size_samples)

        encoder_batch_size = 10000
        num_segments = batched_audio.shape[0]
        outputs = []
        for i in range(0, num_segments, encoder_batch_size):
            output, h, c = self.session.run(
                None,
                {"input": batched_audio[i : i + encoder_batch_size], "h": h, "c": c},
            )
            outputs.append(output)

        return np.concatenate(outputs, axis=0)

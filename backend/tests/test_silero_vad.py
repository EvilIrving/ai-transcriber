"""silero_vad 的单元测试：clip 转换、分段算法、资产定位、onnx 接线。

分段算法用合成 speech_probs（monkeypatch 掉 onnx 模型）测，纯逻辑、不联网；
另有一条用真 onnx 模型跑全静音输入的接线冒烟（验证资产路径 + session + 形状）。
"""
from __future__ import annotations

import os

import numpy as np
import pytest

import silero_vad as V


def test_to_clip_timestamps():
    # 样本点 → 秒，扁平成 [s0,e0,s1,e1,...]，正是 mlx clip_timestamps 的格式。
    speech = [{"start": 0, "end": 16000}, {"start": 32000, "end": 48000}]
    assert V.to_clip_timestamps(speech, 16000) == [0.0, 1.0, 2.0, 3.0]


def test_to_clip_timestamps_empty():
    assert V.to_clip_timestamps([], 16000) == []


def test_resolve_asset_path_exists():
    # vendored 模型必须随仓库存在（打包/运行都依赖它）。
    p = V._resolve_asset_path()
    assert p.endswith(V.VAD_ASSET_NAME)
    assert os.path.isfile(p)


def test_get_speech_timestamps_single_segment(monkeypatch):
    sr, win = 16000, 512
    n_speech_win = int(2 * sr / win)  # 前 2s 语音

    def fake_model(audio):
        nw = len(audio) // win
        probs = np.zeros(nw, dtype=np.float32)
        probs[:n_speech_win] = 0.9  # 前半语音，后半静音
        return probs

    monkeypatch.setattr(V, "get_vad_model", lambda: fake_model)
    audio = np.zeros(4 * sr, dtype=np.float32)  # 4s
    sp = V.get_speech_timestamps(
        audio,
        V.VadOptions(speech_pad_ms=0, min_silence_duration_ms=100, min_speech_duration_ms=0),
    )
    assert len(sp) == 1
    assert sp[0]["start"] == 0
    # 段尾应落在 ~2s 附近（容忍几个窗口的静音判定延迟）。
    assert abs(sp[0]["end"] - 2 * sr) < win * 5


def test_get_speech_timestamps_two_segments(monkeypatch):
    sr, win = 16000, 512

    def fake_model(audio):
        nw = len(audio) // win
        probs = np.zeros(nw, dtype=np.float32)
        # 语音 [0,1s)，静音 [1,3s)，语音 [3,4s)
        probs[: int(1 * sr / win)] = 0.9
        probs[int(3 * sr / win) :] = 0.9
        return probs

    monkeypatch.setattr(V, "get_vad_model", lambda: fake_model)
    audio = np.zeros(4 * sr, dtype=np.float32)
    sp = V.get_speech_timestamps(
        audio,
        V.VadOptions(speech_pad_ms=0, min_silence_duration_ms=200, min_speech_duration_ms=0),
    )
    assert len(sp) == 2


def test_get_speech_timestamps_all_silence(monkeypatch):
    monkeypatch.setattr(
        V, "get_vad_model",
        lambda: (lambda audio: np.zeros(len(audio) // 512, dtype=np.float32)),
    )
    sp = V.get_speech_timestamps(np.zeros(16000, dtype=np.float32))
    assert sp == []


def test_real_onnx_model_silence_smoke():
    # 用真 onnx 模型跑全静音：验证资产路径 + onnxruntime session + 批量形状处理
    # 全链路可用（不依赖 mlx / ffmpeg）。纯静音应判为无语音。
    V.get_vad_model.cache_clear()
    audio = np.zeros(16000, dtype=np.float32)  # 1s 静音
    sp = V.get_speech_timestamps(audio)
    assert sp == []

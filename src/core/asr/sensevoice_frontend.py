from __future__ import annotations

from pathlib import Path
from typing import Tuple

import kaldi_native_fbank as knf
import numpy as np


class SenseVoiceFrontend:
    """Minimal WavFrontend for SenseVoice ONNX (kaldi-native-fbank + LFR + CMVN)."""

    def __init__(
        self,
        *,
        cmvn_file: str,
        fs: int = 16000,
        window: str = "hamming",
        n_mels: int = 80,
        frame_length: int = 25,
        frame_shift: int = 10,
        lfr_m: int = 7,
        lfr_n: int = 6,
        dither: float = 1.0,
    ) -> None:
        opts = knf.FbankOptions()
        opts.frame_opts.samp_freq = fs
        opts.frame_opts.dither = dither
        opts.frame_opts.window_type = window
        opts.frame_opts.frame_shift_ms = float(frame_shift)
        opts.frame_opts.frame_length_ms = float(frame_length)
        opts.mel_opts.num_bins = n_mels
        opts.energy_floor = 0
        opts.frame_opts.snip_edges = True
        opts.mel_opts.debug_mel = False
        self.opts = opts
        self.sample_rate = fs
        self.lfr_m = lfr_m
        self.lfr_n = lfr_n
        self.cmvn = self._load_cmvn(cmvn_file)

    def extract(self, waveform: np.ndarray) -> Tuple[np.ndarray, int]:
        feat, _feat_len = self._fbank(waveform)
        feat, feat_len = self._lfr_cmvn(feat)
        return feat.astype(np.float32), int(feat_len)

    def _fbank(self, waveform: np.ndarray) -> Tuple[np.ndarray, int]:
        scaled = waveform.astype(np.float32) * (1 << 15)
        fbank = knf.OnlineFbank(self.opts)
        fbank.accept_waveform(self.opts.frame_opts.samp_freq, scaled.tolist())
        frames = fbank.num_frames_ready
        mat = np.empty([frames, self.opts.mel_opts.num_bins], dtype=np.float32)
        for index in range(frames):
            mat[index, :] = fbank.get_frame(index)
        return mat, frames

    def _lfr_cmvn(self, feat: np.ndarray) -> Tuple[np.ndarray, int]:
        if self.lfr_m != 1 or self.lfr_n != 1:
            feat = self._apply_lfr(feat, self.lfr_m, self.lfr_n)
        feat = self._apply_cmvn(feat)
        return feat, feat.shape[0]

    @staticmethod
    def _apply_lfr(inputs: np.ndarray, lfr_m: int, lfr_n: int) -> np.ndarray:
        total = inputs.shape[0]
        total_lfr = int(np.ceil(total / lfr_n))
        left_padding = np.tile(inputs[0], ((lfr_m - 1) // 2, 1))
        padded = np.vstack((left_padding, inputs))
        total = total + (lfr_m - 1) // 2
        chunks = []
        for index in range(total_lfr):
            start = index * lfr_n
            if lfr_m <= total - start:
                chunks.append(padded[start : start + lfr_m].reshape(1, -1))
            else:
                frame = padded[start:].reshape(-1)
                while frame.shape[0] < lfr_m * inputs.shape[1]:
                    frame = np.hstack((frame, inputs[-1]))
                chunks.append(frame.reshape(1, -1))
        return np.vstack(chunks).astype(np.float32)

    def _apply_cmvn(self, inputs: np.ndarray) -> np.ndarray:
        frame_count, dim = inputs.shape
        means = np.tile(self.cmvn[0:1, :dim], (frame_count, 1))
        vars_ = np.tile(self.cmvn[1:2, :dim], (frame_count, 1))
        return (inputs + means) * vars_

    @staticmethod
    def _load_cmvn(cmvn_file: str) -> np.ndarray:
        path = Path(cmvn_file)
        lines = path.read_text(encoding="utf-8").splitlines()
        means_list: list[str] = []
        vars_list: list[str] = []
        for index, line in enumerate(lines):
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "<AddShift>" and index + 1 < len(lines):
                next_parts = lines[index + 1].split()
                if next_parts and next_parts[0] == "<LearnRateCoef>":
                    means_list = next_parts[3:-1]
            elif parts[0] == "<Rescale>" and index + 1 < len(lines):
                next_parts = lines[index + 1].split()
                if next_parts and next_parts[0] == "<LearnRateCoef>":
                    vars_list = next_parts[3:-1]
        means = np.array(means_list, dtype=np.float64)
        vars_ = np.array(vars_list, dtype=np.float64)
        return np.array([means, vars_])

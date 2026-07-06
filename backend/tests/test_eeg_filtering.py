from __future__ import annotations

import unittest

import numpy as np

from app.eeg import filter_eeg, filter_eeg_window


class EegWindowFilteringTests(unittest.TestCase):
    def test_context_filtering_matches_whole_recording(self) -> None:
        sampling_rate = 200.0
        times = np.arange(0, 80, 1 / sampling_rate)
        data = (0.8 * np.sin(2 * np.pi * 1.2 * times) + 0.25 * np.sin(2 * np.pi * 13 * times) + 0.01 * times)[None, :]
        start, end = int(25 * sampling_rate), int(55 * sampling_rate)
        expected = filter_eeg(data, sampling_rate, "broad")[:, start:end]
        actual = filter_eeg_window(data, start, end, sampling_rate, "broad")
        np.testing.assert_allclose(actual, expected, atol=1e-4)

    def test_broad_filter_stays_stable_with_large_dc_offset(self) -> None:
        sampling_rate = 250.0
        times = np.arange(0, 90, 1 / sampling_rate)
        data = (1_000_000 + 30 * np.sin(2 * np.pi * 10 * times))[None, :]
        result = filter_eeg_window(data, int(30 * sampling_rate), int(60 * sampling_rate), sampling_rate, "broad")
        self.assertTrue(np.isfinite(result).all())
        self.assertLess(np.max(np.abs(result)), 50)
        self.assertGreater(np.std(result), 10)

    def test_raw_window_is_cropped(self) -> None:
        data = np.arange(40, dtype=float).reshape(2, 20)
        result = filter_eeg_window(data, 4, 12, 100.0, "raw")
        expected = data[:, 4:12] - np.median(data[:, 4:12], axis=1, keepdims=True)
        np.testing.assert_allclose(result, expected)


if __name__ == "__main__":
    unittest.main()

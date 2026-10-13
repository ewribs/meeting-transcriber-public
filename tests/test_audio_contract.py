import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import audio_contract


class AudioContractTests(unittest.TestCase):
    def test_rejects_file_with_fewer_than_five_channels(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.m4a"
            path.write_bytes(b"stub")

            with patch.object(
                audio_contract,
                "_ffprobe_audio_stream",
                return_value={
                    "codec_name": "aac",
                    "sample_rate": "48000",
                    "channels": 2,
                    "channel_layout": "stereo",
                },
            ):
                result = audio_contract.inspect_audio_contract(path)

        self.assertFalse(result["compatible"])
        self.assertEqual(result["channels"], 2)
        self.assertIn("Expected at least 5", result["message"])

    def test_five_channel_input_uses_c0_c4_contract_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "test.m4a"
            source.write_bytes(b"stub")

            def fake_extract(_source, output_dir):
                remote = output_dir / "remote.wav"
                mic = output_dir / "mic.wav"
                remote.write_bytes(b"remote")
                mic.write_bytes(b"mic")
                return remote, mic

            with patch.object(
                audio_contract,
                "_ffprobe_audio_stream",
                return_value={
                    "codec_name": "aac",
                    "sample_rate": "48000",
                    "channels": 5,
                    "channel_layout": "5.0",
                },
            ), patch.object(
                audio_contract,
                "_extract_contract_channels",
                side_effect=fake_extract,
            ):
                result = audio_contract.inspect_audio_contract(source)

        self.assertTrue(result["compatible"])
        self.assertTrue(result["extraction_ok"])
        self.assertEqual(result["remote_channel_index"], 0)
        self.assertEqual(result["mic_channel_index"], 4)
        self.assertGreater(result["remote_extract_bytes"], 0)
        self.assertGreater(result["mic_extract_bytes"], 0)


    def test_finalize_recording_maps_five_channels_and_validates_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "capture.caf"
            output = Path(tmp) / "final.m4a"
            source.write_bytes(b"pcm")

            with patch.object(
                audio_contract,
                "_ffprobe_audio_stream",
                return_value={
                    "codec_name": "pcm_f32le",
                    "sample_rate": "48000",
                    "channels": 5,
                    "channel_layout": "",
                },
            ), patch.object(
                audio_contract.shutil,
                "which",
                return_value="/usr/bin/ffmpeg",
            ), patch.object(
                audio_contract.subprocess,
                "run",
            ) as run, patch.object(
                audio_contract,
                "inspect_audio_contract",
                return_value={"compatible": True, "path": str(output)},
            ) as inspect:
                result = audio_contract.finalize_recording_to_m4a(
                    source,
                    output,
                    sample_rate=48000,
                    channels=5,
                )

            command = run.call_args.args[0]
            self.assertIn(
                "[0:a]pan=5.0|FL=c0|FR=c1|FC=c2|BL=c3|BR=c4[out]",
                command,
            )
            self.assertIn("aac", command)
            self.assertEqual(command[-1], str(output.resolve()))
            inspect.assert_called_once_with(output.resolve())
            self.assertTrue(result["compatible"])
            self.assertEqual(
                result["source_capture_path"],
                str(source.resolve()),
            )


if __name__ == "__main__":
    unittest.main()

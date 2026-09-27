import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import backend_bridge


class BackendBridgeAudioContractTests(unittest.TestCase):
    def test_audio_contract_command(self):
        expected = {
            "schema_version": 1,
            "path": "/tmp/probe.m4a",
            "compatible": True,
        }

        with patch.object(
            backend_bridge,
            "audio_contract_payload",
            return_value=expected,
        ) as payload_mock:
            output = io.StringIO()
            with redirect_stdout(output):
                rc = backend_bridge.main(
                    ["audio-contract", "/tmp/probe.m4a"]
                )

        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(output.getvalue()), expected)
        payload_mock.assert_called_once_with("/tmp/probe.m4a")


    def test_finalize_audio_recording_command(self):
        expected = {
            "schema_version": 1,
            "path": "/tmp/final.m4a",
            "compatible": True,
        }

        with patch.object(
            backend_bridge,
            "finalize_audio_recording_payload",
            return_value=expected,
        ) as payload_mock:
            output = io.StringIO()
            with redirect_stdout(output):
                rc = backend_bridge.main(
                    [
                        "finalize-audio-recording",
                        "/tmp/capture.f32le",
                        "/tmp/final.m4a",
                        "48000",
                        "5",
                    ]
                )

        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(output.getvalue()), expected)
        payload_mock.assert_called_once_with(
            "/tmp/capture.f32le",
            "/tmp/final.m4a",
            48000,
            5,
        )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from maw.editor_burn import burn_editor_subtitles
from maw.postprocess_ffmpeg import BurnSubtitleRequest, MediaToolError, run_burn_subtitles
from tests import test_local_editor_server as server_fixture

server_editor = server_fixture.server_editor


class EditorBurnTests(unittest.TestCase):
    def test_video_and_audio_use_toolbox_pipeline_and_private_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.mp4"
            source.write_bytes(b"original")
            for streams, green in (([{"codec_type": "video"}], False),
                                   ([{"codec_type": "audio"}, {"codec_type": "video", "disposition": {"attached_pic": 1}}], True)):
                info = {"streams": streams, "format": {"duration": "9.25"}}
                probe = subprocess.CompletedProcess([], 0, json.dumps(info), "")
                with mock.patch("maw.editor_burn.subprocess.run", return_value=probe), mock.patch("maw.editor_burn.run_burn_subtitles") as burn:
                    burn_editor_subtitles(source, "current edited subtitles", "srt", root,
                                          ffmpeg_path=Path("ffmpeg"), ffprobe_path=Path("ffprobe"))
                    request = burn.call_args.args[0]
                    self.assertEqual(request.green_screen, green)
                    self.assertEqual(request.green_screen_audio, green)
                    self.assertEqual(request.green_screen_duration, 9.25 if green else None)
                    self.assertEqual(request.media_path, source)
                    self.assertEqual(request.output_path, root / "subtitled.mp4")
                    self.assertEqual(request.subtitle_path.read_text(), "current edited subtitles")
                    self.assertIsNone(request.srt_style)  # shared SRT default slot
            self.assertEqual(source.read_bytes(), b"original")

    def test_audio_duration_must_be_finite_and_positive(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "sound.wav"
            source.touch()
            for duration in ("NaN", "inf", "0", "-1"):
                info = {"streams": [{"codec_type": "audio"}], "format": {"duration": duration}}
                with mock.patch("maw.editor_burn.subprocess.run", return_value=subprocess.CompletedProcess([], 0, json.dumps(info), "")):
                    with self.assertRaises(MediaToolError):
                        burn_editor_subtitles(source, "test", "ass", root,
                                              ffmpeg_path=Path("ffmpeg"), ffprobe_path=Path("ffprobe"))

    def test_green_screen_preserves_audio_and_media_duration(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "sound.opus"
            source.write_bytes(b"source")
            subtitle = root / "current.ass"
            subtitle.write_text("[Script Info]\nPlayResX: 320\nPlayResY: 180\n[Events]\nFormat: Layer, Start, End, Text\nDialogue: 0,0:00:00.00,0:00:01.00,Hello\n")
            commands = []
            def run(command, **kwargs):
                commands.append(command)
                Path(command[-1]).write_bytes(b"video")
            with mock.patch("maw.postprocess_ffmpeg._run_ffmpeg_process", side_effect=run):
                result = run_burn_subtitles(BurnSubtitleRequest(
                    source, subtitle, green_screen=True, green_screen_audio=True,
                    green_screen_duration=8, output_path=root / "out.mp4", video_encoder="cpu",
                ), ffmpeg_path=Path("ffmpeg"))
            command = commands[0]
            self.assertIn("color=c=0x00ff00:s=320x180:r=30:d=8.000", command)
            self.assertIn("1:a", command)
            self.assertIn(str(source.resolve()), command)
            self.assertNotIn("-an", command)
            self.assertEqual(result.media_path, root / "out.mp4")
            self.assertEqual(source.read_bytes(), b"source")


class EditorBurnEndpointTests(unittest.TestCase):
    setUp = server_fixture.LocalEditorServerTests.setUp
    tearDown = server_fixture.LocalEditorServerTests.tearDown

    def test_endpoint_binds_source_and_streams_private_output_with_token(self):
        project = server_editor.ServerProject(
            json_path=self.project_path, data={"segments": []},
            media_path=self.media, sticker_root=None, stickers=[], source_media_path=self.media,
        )
        captured = []
        def burn(source, text, subtitle_format, output_dir, **kwargs):
            captured.append((source, text, subtitle_format, output_dir))
            output = output_dir / "burn.mp4"
            output.write_bytes(b"burned-video")
            return output
        with server_editor.EditorServer(("127.0.0.1", 0), project) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            url = f"http://127.0.0.1:{server.server_address[1]}/api/exports/burn-video"
            def post(payload):
                return urllib.request.urlopen(urllib.request.Request(url, data=json.dumps(payload).encode(),
                    headers={"Content-Type": "application/json"}, method="POST"), timeout=3)
            try:
                with mock.patch.object(server_editor, "editor_ffmpeg_tools", return_value=mock.Mock(ffmpeg=Path("ffmpeg"), ffprobe=Path("ffprobe"))), \
                     mock.patch.object(server, "ensure_libass_supported", return_value=True), \
                     mock.patch.object(server_editor, "burn_editor_subtitles", side_effect=burn):
                    payload = {"requestToken": "wrong", "format": "ass", "subtitles": "edited ASS",
                               "sourceMediaPath": str(self.other_media), "outputPath": str(self.other_media)}
                    with self.assertRaises(urllib.error.HTTPError) as rejected:
                        post(payload)
                    self.assertEqual(rejected.exception.code, 403)
                    self.assertEqual(captured, [])
                    payload["requestToken"] = server.request_token
                    for invalid_format in (["ass"], "exe"):
                        with self.assertRaises(urllib.error.HTTPError) as rejected:
                            post({**payload, "format": invalid_format})
                        self.assertEqual(rejected.exception.code, 400)
                    server.burn_video_lock.acquire()
                    try:
                        with self.assertRaises(urllib.error.HTTPError) as rejected:
                            post(payload)
                        self.assertEqual(rejected.exception.code, 409)
                    finally:
                        server.burn_video_lock.release()
                    with post(payload) as response:
                        self.assertEqual(response.read(), b"burned-video")
                        self.assertEqual(response.headers["Content-Type"], "video/mp4")
                        self.assertEqual(response.headers["Content-Length"], "12")
                    self.assertEqual(captured[0][:3], (self.media, "edited ASS", "ass"))
                    self.assertTrue(server.burn_video_lock.acquire(timeout=3))
                    self.assertFalse(captured[0][3].exists())
                    self.assertEqual(self.other_media.read_bytes(), b"abcdefghij")
                    server.burn_video_lock.release()
                    with mock.patch.object(server_editor, "burn_editor_subtitles", side_effect=MediaToolError("encoding failed")):
                        with self.assertRaises(urllib.error.HTTPError) as rejected:
                            post(payload)
                        self.assertEqual(rejected.exception.code, 422)
                    self.assertTrue(server.burn_video_lock.acquire(timeout=3))
                    server.burn_video_lock.release()
            finally:
                server.shutdown()
                thread.join(timeout=3)

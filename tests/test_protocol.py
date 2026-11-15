import unittest

from common.protocol import FrameBuffer, encode


class FrameBufferTests(unittest.TestCase):
    """Découpage des trames TCP : messages fragmentés ou regroupés, rejet des trames invalides ou trop volumineuses."""

    def test_fragmented_frame(self):
        buf = FrameBuffer()
        frame = encode({"type": "ping", "texte": "été"})
        self.assertEqual(buf.feed(frame[:5]), [])
        self.assertEqual(buf.feed(frame[5:]), [{"type": "ping", "texte": "été"}])

    def test_multiple_frames(self):
        buf = FrameBuffer()
        self.assertEqual(
            buf.feed(encode({"type": "ping"}) + encode({"type": "pong"})),
            [{"type": "ping"}, {"type": "pong"}],
        )

    def test_empty_lines_are_ignored(self):
        self.assertEqual(FrameBuffer().feed(b"\n  \n"), [])

    def test_invalid_json_raises(self):
        with self.assertRaisesRegex(ValueError, "JSON invalide"):
            FrameBuffer().feed(b"{not-json}\n")

    def test_invalid_utf8_raises(self):
        with self.assertRaisesRegex(ValueError, "JSON invalide"):
            FrameBuffer().feed(b"\xff\n")

    def test_oversized_incomplete_frame_raises(self):
        with self.assertRaisesRegex(ValueError, "trop volumineuse"):
            FrameBuffer(max_size=4).feed(b"12345")

    def test_oversized_complete_frame_raises(self):
        with self.assertRaisesRegex(ValueError, "trop volumineuse"):
            FrameBuffer(max_size=4).feed(b"12345\n")


if __name__ == "__main__":
    unittest.main()

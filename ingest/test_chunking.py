import unittest

from chunking import chunk


class ChunkTests(unittest.TestCase):
    def test_empty_text_yields_no_chunks(self):
        self.assertEqual(chunk(""), [])
        self.assertEqual(chunk("   \n\t  "), [])

    def test_short_text_is_one_chunk(self):
        self.assertEqual(chunk("hello world", size=100, overlap=10), ["hello world"])

    def test_windows_overlap_and_cover_the_text(self):
        body = "".join(str(i % 10) for i in range(250))
        pieces = chunk(body, size=100, overlap=20)
        self.assertEqual(pieces[0], body[0:100])
        self.assertEqual(pieces[1], body[80:180])
        self.assertEqual(pieces[-1].endswith(body[-1]), True)
        for p in pieces:
            self.assertLessEqual(len(p), 100)

    def test_no_chunk_is_whitespace_only(self):
        body = "word " + " " * 300 + "end"
        for p in chunk(body, size=50, overlap=10):
            self.assertTrue(p.strip())

    def test_overlap_must_be_smaller_than_size(self):
        with self.assertRaises(ValueError):
            chunk("abc", size=10, overlap=10)


if __name__ == "__main__":
    unittest.main()

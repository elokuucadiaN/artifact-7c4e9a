import unittest
from .source_scope import code_lines
class SourceScopeCounter(unittest.TestCase):
    def test_comments_and_literals(self):
        source='/* only comment\n second */\nchar *a="/* still code */"; // comment\n// nothing\nint b; /* trailing\n comment */ int c;\n'
        self.assertEqual(code_lines(source),3)
    def test_comment_delimiters_in_character_literals(self):
        self.assertEqual(code_lines("char c='\\\'';\nchar slash='/';\n/* comment */"),2)
    def test_final_line_and_blank_lines(self):
        self.assertEqual(code_lines('\n\t\n/*no*/\nint value;'),1)
    def test_bom_and_continued_line_comment(self):
        self.assertEqual(code_lines('\ufeff// ignored\\\nstill ignored\nint value;\n'),1)
if __name__=='__main__':unittest.main()

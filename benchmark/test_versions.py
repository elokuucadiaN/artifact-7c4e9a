import unittest
from .version_policy import require_paper_version,PINS
class PaperVersionAdmission(unittest.TestCase):
    def test_other_release_rejected(self):
        for os,commit in dict(freertos='def7d2df2b0506d3d249334974f51e427c17a41c',riot='b51f093a395bdd575cff94b7d26be415fa46771d',contiki='c20b12cd2db707d6c07918f8b26cfeb52cf298ca').items():
            with self.subTest(os=os),self.assertRaisesRegex(ValueError,'differs from EunoBench paper'):
                require_paper_version(dict(os=os,upstream_commit=commit))
    def test_missing_revision_rejected(self):
        for os in PINS:
            with self.subTest(os=os),self.assertRaises(ValueError):require_paper_version(dict(os=os))
if __name__=='__main__':unittest.main()

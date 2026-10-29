from dataclasses import replace
import unittest

from helpers.tests.test_extract_pdf import config, line
from helpers.text_extraction.parser import _identifier_values, parse_records


class SuffixMarkerTests(unittest.TestCase):
    def test_metadata_preserves_suffix_and_numeric_identifiers(self):
        self.assertEqual(_identifier_values('<33651a> <33651b>'), ['33651a', '33651b'])
        self.assertEqual(_identifier_values('VNCHN 08460/08461.'), ['08460', '08461'])

    def test_sections_remain_distinct_for_each_suffix(self):
        cfg = replace(config(), marker_pattern=r'^\s*<\s*(?P<id>\d+[A-Za-z]?)\s*>?\s*(?P<rest>.*)$')
        lines = [line('VĂN BIA SỐ 1'), line('Tên bia: Bia'), line('Địa điểm: Chùa'),
                 line('Niên đại: 1942'), line('Kí hiệu VNCHN: <33651a><33651b>'),
                 line('Nguyên văn chữ Hán Nôm:'), line('<33651a> 甲'), line('<33651b> 乙'),
                 line('Phiên âm Hán Việt:'), line('<33651a> Giáp'), line('<33651b> Ất')]
        records, _ = parse_records(lines, cfg)
        record = records[0]
        self.assertEqual(record['ky_hieu_vnchn'], ['33651a', '33651b'])
        self.assertEqual([f['ky_hieu'] for f in record['noi_dung']], ['33651a', '33651b'])
        self.assertEqual(record['noi_dung'][0]['chuyen_muc'][0]['van_ban'], '甲')
        self.assertEqual(record['noi_dung'][1]['chuyen_muc'][0]['van_ban'], '乙')


if __name__ == '__main__':
    unittest.main()

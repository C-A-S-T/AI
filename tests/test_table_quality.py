"""Table quality and source-structure regressions; fixtures never launch COM."""
from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

import pipeline
from src.preprocessing.clean_text import clean_document
from src.preprocessing.parse_hwpx import read_source_tables
from src.preprocessing.parse_pdf import EXTRACTION_VERSION
from src.preprocessing.table_quality import coverage, extract_tables_with_quality, suspect_regions


def cell(row, column, text, *, row_span=1, column_span=1, nested=""):
    """Build original XML cells with explicit addresses and merged spans."""
    return (f'<tc><subList><p><run><t>{text}</t>{nested}</run></p></subList>'
            f'<cellAddr rowAddr="{row}" colAddr="{column}"/>'
            f'<cellSpan rowSpan="{row_span}" colSpan="{column_span}"/></tc>')


class SourceTableTests(unittest.TestCase):
    """Check exact source-cell relationships rather than rendered line ordering."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "원본.hwpx"

    def archive(self, content):
        with zipfile.ZipFile(self.path, "w") as archive:
            archive.writestr("Contents/section0.xml", '<section xmlns="urn:test">' + content + '</section>')

    def test_merged_cells_and_blank_cells_keep_addresses(self):
        self.archive('<tbl id="source" rowCnt="2" colCnt="2"><tr>'
                     + cell(0, 0, '금리 2.2%', column_span=2) + '</tr><tr>'
                     + cell(1, 0, '개선') + cell(1, 1, '') + '</tr></tbl>')
        table = read_source_tables(self.path)[0]
        self.assertEqual(table['column_count'], 2)
        self.assertEqual(table['cells'][0]['column_span'], 2)
        self.assertEqual(table['cells'][0]['text'], '금리 2.2%')
        self.assertEqual(table['cells'][2]['column'], 1)
        self.assertEqual(table['cells'][2]['text'], '')
        self.assertNotIn('page_number', table)

    def test_nested_tables_do_not_duplicate_text_in_parent(self):
        nested = '<tbl rowCnt="1" colCnt="1"><tr>' + cell(0, 0, '자식 400만원') + '</tr></tbl>'
        self.archive('<tbl rowCnt="1" colCnt="1"><tr>' + cell(0, 0, '부모', nested=nested) + '</tr></tbl>')
        parent, child = read_source_tables(self.path)
        self.assertEqual(parent['cells'][0]['text'], '부모')
        self.assertEqual(child['cells'][0]['text'], '자식 400만원')
        self.assertEqual(child['parent_table_id'], parent['table_id'])
        self.assertEqual(child['parent_cell'], {'row': 0, 'column': 0})

    def test_out_of_bounds_and_overlapping_spans_are_rejected(self):
        for cells in (cell(0, 0, 'bad', column_span=3), cell(0, 0, 'a') + cell(0, 0, 'b')):
            with self.subTest(cells=cells):
                self.archive('<tbl rowCnt="1" colCnt="2"><tr>' + cells + '</tr></tbl>')
                with self.assertRaises(ValueError):
                    read_source_tables(self.path)

    def test_missing_sections_are_rejected(self):
        with zipfile.ZipFile(self.path, 'w') as archive:
            archive.writestr('unrelated.xml', '<section/>')
        with self.assertRaises(ValueError):
            read_source_tables(self.path)

    def test_explicit_line_break_preserved(self):
        self.archive('<tbl rowCnt="1" colCnt="1"><tr>' + cell(0, 0, '09시<lineBreak/>24시') + '</tr></tbl>')
        self.assertEqual(read_source_tables(self.path)[0]['cells'][0]['text'], '09시\n24시')


class TableQualityTests(unittest.TestCase):
    """Exercise missed tables, incomplete bodies and non-destructive alternatives."""

    def page(self, tables=(), text='heading body 2.2%'):
        page = Mock()
        page.find_tables.return_value = list(tables)
        page.crop.return_value.extract_text.return_value = text
        page.crop.return_value.find_tables.return_value = []
        return page

    def table(self, bbox, rows):
        table = Mock()
        table.bbox, table.cells = bbox, [bbox]
        table.extract.return_value = rows
        return table

    def test_missing_numbers_are_detected_but_blank_cells_are_not_errors(self):
        self.assertGreater(coverage('2.2% 1.7%', [['1.7%', None]])['missing_character_count'], 0)
        self.assertEqual(coverage('이름 금리', [['이름', None], ['금리', '']])['missing_character_count'], 0)

    def test_missed_table_region_forces_review(self):
        page = self.page()
        with patch('src.preprocessing.table_quality.suspect_regions', return_value=[{'bbox': [0, 0, 100, 100]}]):
            tables, details, quality, warnings = extract_tables_with_quality(page)
        self.assertEqual(tables, [])
        self.assertEqual(quality['status'], 'REVIEW_REQUIRED')
        self.assertTrue(any('SUSPECTED_TABLE_NOT_EXTRACTED' in w for w in warnings))

    def test_header_only_does_not_count_as_complete(self):
        header = self.table((0, 0, 100, 10), [['heading']])
        with patch('src.preprocessing.table_quality.suspect_regions', return_value=[{'bbox': [0, 0, 100, 100]}]):
            _, details, quality, warnings = extract_tables_with_quality(self.page([header]))
        self.assertIn('SINGLE_ROW_TABLE_REVIEW', details[0]['flags'])
        self.assertTrue(any('SUSPECTED_TABLE_REGION_INCOMPLETE' in w for w in warnings))

    def test_candidates_never_silently_replace_default_tables(self):
        page = self.page()
        page.crop.return_value.find_tables.return_value = [self.table((0, 0, 100, 100), [['heading', 'body 2.2%']])]
        with patch('src.preprocessing.table_quality.suspect_regions', return_value=[{'bbox': [0, 0, 100, 100]}]):
            tables, _, quality, _ = extract_tables_with_quality(page)
        self.assertEqual(tables, [])
        self.assertTrue(quality['review_candidates'])
        self.assertTrue(all(c['selection_status'] == 'UNVERIFIED_NOT_SELECTED' for c in quality['review_candidates']))

    def test_nested_pdf_tables_mark_overlap_without_deleting_data(self):
        outer = self.table((0, 0, 100, 100), [['heading'], ['body 2.2%']])
        inner = self.table((10, 10, 50, 50), [['heading'], ['body 2.2%']])
        with patch('src.preprocessing.table_quality.suspect_regions', return_value=[]):
            tables, details, _, _ = extract_tables_with_quality(self.page([outer, inner]))
        self.assertEqual(len(tables), 2)
        self.assertEqual(details[0]['contained_table_indexes'], [1])

    def test_single_rule_not_a_table_but_repeated_aligned_rows_are_suspect(self):
        page = Mock()
        page.bbox = (0, 0, 200, 200)
        page.edges = [{'orientation': 'h', 'x0': 10, 'x1': 190, 'top': 10}]
        self.assertEqual(suspect_regions(page), [])
        page.edges += [{'orientation': 'h', 'x0': 10, 'x1': 190, 'top': y} for y in (50, 90, 130)]
        page.crop.return_value.extract_words.return_value = [
            {'x0': x, 'top': y, 'text': 'cell'} for x in (20, 100) for y in (20, 60, 100)]
        self.assertEqual(len(suspect_regions(page)), 1)

    def test_quality_failure_is_not_silent(self):
        page = self.page()
        page.find_tables.side_effect = RuntimeError('fixture failure')
        _, _, quality, warnings = extract_tables_with_quality(page)
        self.assertEqual(quality['status'], 'REVIEW_REQUIRED')
        self.assertTrue(any('TABLE_QUALITY_CHECK_FAILED' in w for w in warnings))

    def test_old_cache_requires_reextraction(self):
        cached = {'document_id': 'DOC-fixture', 'file_hash_sha256': 'hash', 'pages': [], 'page_count': 0}
        with self.assertRaisesRegex(ValueError, 'REEXTRACTION_REQUIRED'):
            pipeline.check_existing_extraction(cached, 'DOC-fixture', 'hash', Path('fixture.json'))
        cached['extraction_version'] = EXTRACTION_VERSION
        pipeline.check_existing_extraction(cached, 'DOC-fixture', 'hash', Path('fixture.json'))

    def test_cleaning_preserves_source_tables_and_diagnostics(self):
        page = {'page_number': 1, 'text': 'text  \n', 'tables': [],
                'table_details': [], 'table_quality': {'status': 'REVIEW_REQUIRED'}}
        parsed = {'schema_version': 1, 'extraction_version': EXTRACTION_VERSION,
                  'document_id': 'doc', 'file_hash_sha256': 'hash', 'page_count': 1,
                  'quality_status': 'REVIEW_REQUIRED', 'warnings': [], 'pages': [page],
                  'source_tables': [{'table_id': 'original'}]}
        cleaned = clean_document(parsed)
        self.assertEqual(cleaned['source_tables'], parsed['source_tables'])
        self.assertEqual(cleaned['pages'][0]['table_quality'], page['table_quality'])
        self.assertEqual(cleaned['extraction_version'], EXTRACTION_VERSION)


if __name__ == '__main__':
    unittest.main()

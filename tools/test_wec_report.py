import unittest
import json
import tempfile
from pathlib import Path
from wec_report import duration, parse_csv, discover, render, summarize, stints, parse_classification

HEADER = 'NUMBER; DRIVER_NUMBER; LAP_NUMBER; LAP_TIME; DRIVER_NAME;CLASS;TEAM;PIT_TIME;CROSSING_FINISH_LINE_IN_PIT;FLAG_AT_FL\n'

class WECTests(unittest.TestCase):
    def test_event_pages_group_sessions_and_keep_years_separate(self):
        from wec_report import build_index
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for year, key, session in [('2026', 'a', '202604180900_Free Practice 1'),
                                       ('2026', 'b', '202604191300_Race'),
                                       ('2025', 'c', '202504191300_Race')]:
                directory = root/year/key
                directory.mkdir(parents=True)
                (directory/'report.html').write_text('report')
                (directory/'source.json').write_text(json.dumps({'event': '01_IMOLA', 'session': session}))
            build_index(root)
            pages = list(root.glob('*/event-*/index.html'))
            self.assertEqual(len(pages), 2)
            event = next(p for p in pages if p.parts[-3] == '2026')
            text = event.read_text()
            self.assertEqual(text.count('role="tab"'), 2)
            self.assertIn('Free Practice 1', text)
            self.assertIn('../b/report.html', text)
            self.assertNotIn('../c/report.html', text)
            self.assertIn('id="session-1" aria-controls="session-panel" aria-selected="true"', text)
            before = (root/'index.html').read_text()
            build_index(root)
            self.assertEqual((root/'index.html').read_text(), before)

    def test_times(self):
        self.assertEqual(duration('1:02:03.456'), 3723.456)
        for value in ['', 'NaN', 'inf', '-1', 'bad']:
            self.assertIsNone(duration(value))

    def test_pace_excludes_pit_and_flags_and_first_lap(self):
        data = HEADER + '\n'.join([
            '007;1;1;1:00.000;A;HYPERCAR;T;;;GF',
            '007;1;2;1:30.000;A;HYPERCAR;T;;;GF',
            '007;1;3;1:40.000;A;HYPERCAR;T;;;GF',
            '007;1;4;1:50.000;A;HYPERCAR;T;;B;GF',
            '007;2;5;2:00.000;B;HYPERCAR;T;0:20.000;;GF',
            '007;2;6;2:30.000;B;HYPERCAR;T;;;SC'])
        rows = parse_csv(data.encode())
        summary = summarize(rows)
        self.assertEqual(summary[0]['number'], '007')
        self.assertEqual(summary[0]['median'], 95)
        self.assertEqual(summary[0]['sample'], 2)
        self.assertIsNone(summary[1]['median'])
        self.assertEqual(summary[0]['pit_in'], 1)

    def test_schema_and_duplicates_fail(self):
        for text in ['<html>error</html>', HEADER, HEADER+'1;1;2;1:30;A;C;T;;;GF\n'*2]:
            with self.assertRaises(ValueError):
                parse_csv(text.encode())

    def test_discovery_excludes_support_series(self):
        files = [{'name':'Analysis.CSV','extension':'csv','url':f'wec/results/15_2026/08_MONZA/{series}/202611061030_Free Practice 1/23_Analysis_Free Practice 1.CSV'} for series in ['689_FIA WEC','690_Legends of Le Mans']]
        entries = discover({'folders':files})
        self.assertEqual(len(entries),1)
        self.assertEqual(len(next(iter(entries.values()))['files']),1)
        self.assertFalse(discover({'folders':files},'IMOLA'))

    def test_stints_split_pit_and_driver_change(self):
        rows = parse_csv((HEADER + '\n'.join([
            '7;1;1;1:30;A;C;T;;;GF',
            '7;1;2;1:40;A;C;T;;B;GF',
            '7;2;3;2:10;B;C;T;0:20;;GF',
            '7;2;4;1:32;B;C;T;;;GF'])).encode())
        self.assertEqual([[r['LAP_NUMBER'] for r in laps] for _,laps in stints(rows)], [['1','2'],['3','4']])

    def test_official_classification_is_not_recomputed(self):
        rows = parse_csv((HEADER+'7;1;2;1:30;A;C;T;;;GF').encode())
        page = render({'event':'E','session':'S'}, rows, [], [{'POS':'8', 'NUMBER':'7', 'CLASS':'C','TIME':'1:30','TEAM':'<Team>'}])
        self.assertIn('<td>8</td>',page)
        self.assertIn('&lt;Team&gt;',page)

    def test_race_classification_aliases(self):
        result = parse_classification(b'POSITION;NUMBER;CLASS;TOTAL_TIME;STATUS\n2;007;HYPERCAR;6:00:01.000;Classified\n')
        self.assertEqual(result[0]['POS'], '2')
        self.assertEqual(result[0]['TIME'], '6:00:01.000')

    def test_html_escapes_driver_and_embedded_script(self):
        rows=parse_csv((HEADER+'007;1;2;1:30;</script><script>alert(1)</script>;C;T;;;GF').encode())
        page=render({'event':'E','session':'S'},rows,[])
        self.assertNotIn('</script><script>alert',page)
        self.assertIn('&lt;/script&gt;',page)

if __name__ == '__main__': unittest.main()

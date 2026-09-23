"""Optional offline V3 writer when the Node @oai/artifact-tool is unavailable.

Uses the same local artifact_tool spreadsheet engine; never contacts POMS or
any discovery service. Only used if the existing Node writer cannot import its
own package. Input/output paths are supplied by mp_export.py in a staging dir.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

from artifact_tool import Workbook, SpreadsheetFile

CST = timezone(timedelta(hours=8))


def local_datetime(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(CST).replace(tzinfo=None)


def main(input_file: str, output_file: str):
    data = json.loads(Path(input_file).read_text(encoding='utf-8'))
    book = Workbook.create()
    intro = book.worksheets.add('说明与统计')
    coverage = list(data.get('collector', {}).get('keyword_coverage', {}).values())
    notes = [
        ['微信公众号 TechDesign V3', None],
        ['正式监测开始', local_datetime(data['monitoring_start_time'])],
        ['有效文章数', data['valid_articles']], ['已采集帐号数', data['table_counts'][4]],
        ['表1、表2输出时间', local_datetime(data['content_export_at'])],
        ['表3—表5输出时间', local_datetime(data['metrics_export_at'])],
        ['采集状态', data.get('collector', {}).get('status', 'UNKNOWN')],
        ['本批次结束时间', data.get('monitoring_end_time') or '未限定'],
        ['总候选数', data['total_candidates']],
        ['明确无效文章数', data['invalid_articles']], ['待人工核验文章数', data['pending_review_articles']],
        ['搜索完成度', f"{sum(x in ('SUCCESS','NO_RESULTS') for x in coverage)}/{len(coverage)} 个关键词到达自然终点。"],
        ['公开数据边界', data.get('limitations')],
        ['正文与过滤', data.get('content_note')], ['文章标识', data.get('identity_note')],
        ['公开文章链接限制', data.get('canonical_url_limitation')],
        ['POMS文件格式', data.get('poms_json_note')],
        ['帐号统计口径', data.get('account_metrics_note')], ['CSV导入', data.get('csv_note')],
        ['数值占位说明', data.get('zero_placeholder_note')],
        ['公开互动量说明', data.get('interaction_placeholder_note')],
        ['帐号关联ID说明', data.get('account_id_note')],
        ['原始证据保留', data.get('raw_preservation_note')],
        ['评论表说明', data.get('comment_note')],
    ]
    intro.get_range_by_indexes(0, 0, len(notes), 2).values = notes
    all_notes = intro.get_range(f'A1:B{len(notes)}')
    all_notes.format.wrap_text = True
    all_notes.format.row_height = 40
    intro.get_range(f'A1:A{len(notes)}').format.column_width = 28
    intro.get_range(f'B1:B{len(notes)}').format.column_width = 100
    intro.get_range('A1:B1').format = {'fill': '#25465B', 'font': {'bold': True, 'color': '#FFFFFF'}}
    for name in ('B2', 'B5', 'B6'):
        intro.get_range(name).set_number_format('yyyy-mm-dd hh:mm:ss')
    for sheet_name, headers, table in zip(data['sheets'], data['fields'], data['tables']):
        sheet = book.worksheets.add(sheet_name)
        converted = []
        for row in table:
            cells = []
            for header, value in zip(headers, row):
                if '时间' in header and isinstance(value, str):
                    try:
                        value = local_datetime(value)
                    except ValueError:
                        pass
                if isinstance(value, str) and value.startswith('='):
                    value = "'" + value  # Literal public text, never an Excel formula.
                cells.append(value)
            converted.append(cells)
        rng = sheet.get_range_by_indexes(0, 0, 1 + len(converted), len(headers))
        rng.values = [headers, *converted]
        rng.format.column_width = 24
        rng.format.row_height = 32
        rng.format.wrap_text = True
        head = sheet.get_range_by_indexes(0, 0, 1, len(headers))
        head.format = {'fill': '#25465B', 'font': {'bold': True, 'color': '#FFFFFF'}, 'row_height': 42}
        for col, header in enumerate(headers):
            column = sheet.get_range_by_indexes(0, col, 1 + len(converted), 1)
            if '编号' in header or 'ID' in header:
                column.set_number_format('@')
                column.format.column_width = 38
            elif '时间' in header:
                if converted:
                    sheet.get_range_by_indexes(1, col, len(converted), 1).set_number_format('yyyy-mm-dd hh:mm:ss')
                column.format.column_width = 26
            elif any(part in header for part in ('标题', '正文', '关键词', '链接')):
                column.format.column_width = 65
        sheet.freeze_panes.freeze_rows(1)
        sheet.freeze_panes.freeze_columns(1)
    # The caller audits the physical workbook before publishing CSV/JSON/summary.
    staged = str(output_file) + '.tmp'
    SpreadsheetFile.export_xlsx(book).save(staged)
    Path(staged).replace(output_file)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])

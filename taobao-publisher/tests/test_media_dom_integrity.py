# -*- coding: utf-8 -*-
"""在 Node 中运行页面表达式与去敏 DOM 替身；不连接任何浏览器。"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
import unittest

SUBPROJECT = pathlib.Path(__file__).resolve().parents[1]
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish import page


DOM_FIXTURE = r"""
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const mutations = [];
class Field {
  constructor(value) { this.current = value; this.disabled = false; this.readOnly = false; }
  get value() { return this.current; }
  set value(value) { mutations.push(value); this.current = value; }
  dispatchEvent() {}
}
const price = new Field('12.00'), stock = new Field('3');
stock.disabled = input.disabled === true;
const cells = [
  {textContent: 'M', querySelector: () => null},
  {textContent: '', querySelector: () => null},
  {textContent: '元', querySelector: () => price},
  {textContent: '件', querySelector: () => stock},
];
const row = { querySelectorAll: selector => selector === 'td' ? cells : [] };
const skuRoot = {
  querySelectorAll: selector => selector === 'table' ? [{}]
    : selector === 'tr.sku-table-row' ? Array(input.rowCount || 1).fill(row) : [],
};
const slot = { querySelector: selector => selector === 'img' ? {src: input.url} : null };
const mainArea = {
  querySelector: () => mainLabel,
  querySelectorAll: () => [slot],
};
const mainLabel = { textContent: '1:1主图', closest: () => mainArea };
global.document = {
  querySelectorAll: selector => selector === '.sell-sku-table-wrapper-new'
    ? (input.noSkuRoot ? [] : [skuRoot])
    : selector === '.sell-component-info-wrapper-wrap' ? [mainArea] : [],
  querySelector: selector => selector === '.sell-sku-table-wrapper-new'
    && !input.noSkuRoot ? skuRoot : null,
};
const result = eval(input.expression);
process.stdout.write(JSON.stringify({result, mutations}));
"""


@unittest.skipUnless(shutil.which("node"), "需要本地 Node 运行隔离 DOM 表达式")
class MediaDomIntegrityTest(unittest.TestCase):
    def run_expression(self, expression, **options):
        result = subprocess.run(
            [shutil.which("node"), "-e", DOM_FIXTURE],
            input=json.dumps({"expression": expression, **options}, ensure_ascii=False),
            text=True, encoding="utf-8", capture_output=True, timeout=10, check=True,
        )
        return json.loads(result.stdout)

    def test_main_image_url_is_preserved_beyond_120_characters(self):
        url = "https://img.example.invalid/" + "x" * 300 + "/distinct.jpg"
        output = self.run_expression(page.build_read_main_slots_expression("1:1主图"), url=url)
        self.assertEqual(output["result"]["images"], [url])

    def test_disabled_stock_prevents_both_price_and_stock_mutations(self):
        output = self.run_expression(page.build_set_sku_row_numbers_expression(0, "15", "7"), disabled=True)
        self.assertFalse(output["result"]["ok"])
        self.assertEqual(output["result"]["reason"], "sku_controls_unavailable")
        self.assertEqual(output["mutations"], [])

    def test_a_missing_sku_root_does_not_fall_back_to_an_unrelated_table(self):
        output = self.run_expression(page.build_set_sku_row_numbers_expression(0, "15", "7"), noSkuRoot=True)
        self.assertFalse(output["result"]["ok"])
        self.assertEqual(output["mutations"], [])

    def test_numeric_readback_carries_specs_from_the_same_row(self):
        output = self.run_expression(page.build_read_sku_row_numbers_expression())
        self.assertEqual(output["result"]["rows"], [{"specs": ["M"], "price": "12.00", "stock": "3"}])

    def test_sku_readback_preserves_all_rows_above_the_old_60_row_cap(self):
        output = self.run_expression(page.build_read_sku_table_expression(), rowCount=61)
        self.assertEqual(output["result"]["rowCount"], 61)
        self.assertEqual(len(output["result"]["rows"]), 61)


if __name__ == "__main__":
    unittest.main()

/** 与后端归档样本一致：汉字计 2、ASCII 计 1；其它字符的实际平台规则待验证。 */
export function countTaobaoTitleUnits(text: string): number {
  let units = 0;
  for (const char of text) {
    const point = char.codePointAt(0)!;
    const han = (point >= 0x3400 && point <= 0x9fff) ||
      (point >= 0xf900 && point <= 0xfaff) ||
      (point >= 0x20000 && point <= 0x323af);
    units += han ? 2 : 1;
  }
  return units;
}

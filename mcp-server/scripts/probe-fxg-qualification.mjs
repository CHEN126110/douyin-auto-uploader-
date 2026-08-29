import { probeFxgQualification } from "../fxg-qualification-probe.js";
import { writeFile } from "node:fs/promises";

const result = await probeFxgQualification({
  cdpListUrl: process.env.DOUYIN_CDP_LIST_URL || process.env.CDP_LIST_URL,
  targetUrlContains: process.env.TARGET_HINT || "fxg.jinritemai.com/ffa/g/create",
  maxModules: Number(process.env.MAX_MODULES || 120),
  snippetRadius: Number(process.env.SNIPPET_RADIUS || 1200),
});

const output = JSON.stringify(result, null, 2);
if (process.env.OUTPUT_PATH) {
  await writeFile(process.env.OUTPUT_PATH, output, "utf8");
} else {
  console.log(output);
}

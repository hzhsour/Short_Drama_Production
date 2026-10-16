import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";

const require = createRequire(import.meta.url);
const cliPackagePath = require.resolve("@remotion/cli/package.json");
const cliPackage = JSON.parse(readFileSync(cliPackagePath, "utf8"));
const cliPath = join(dirname(cliPackagePath), cliPackage.bin.remotion);
const browserNames = process.platform === "win32"
  ? ["chrome.exe", "chromium.exe", "msedge.exe"]
  : ["chromium", "chromium-browser", "google-chrome", "google-chrome-stable"];

let browserPath = process.env.CHROME_EXECUTABLE;
if (browserPath && !existsSync(browserPath)) {
  console.error(`CHROME_EXECUTABLE 指向的文件不存在：${browserPath}`);
  process.exit(1);
}

if (!browserPath) {
  for (const browserName of browserNames) {
    const command = process.platform === "win32" ? "where.exe" : "which";
    const lookup = spawnSync(command, [browserName], { encoding: "utf8" });
    const candidate = lookup.status === 0 ? lookup.stdout.split(/\r?\n/)[0]?.trim() : "";
    if (candidate && existsSync(candidate)) {
      browserPath = candidate;
      break;
    }
  }
}

if (!browserPath) {
  console.error("未找到 Chrome/Chromium。请先安装浏览器，或设置 CHROME_EXECUTABLE 指向其可执行文件。");
  process.exit(1);
}

const args = [
  cliPath,
  "render",
  "src/remotion/index.ts",
  "ShortDramaPreview",
  "renders/preview.mp4",
  "--browser-executable",
  browserPath,
  "--chrome-mode",
  "chrome-for-testing",
];
const result = spawnSync(process.execPath, args, { stdio: "inherit" });
if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}
process.exit(result.status ?? 1);

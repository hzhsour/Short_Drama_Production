#!/usr/bin/env node
/** Stage local media, render with installed Chromium, and never replace originals. */
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { closeSync, copyFileSync, existsSync, linkSync, mkdirSync, mkdtempSync, openSync, readFileSync, readSync, realpathSync, rmSync, statSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, extname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(import.meta.url);

function fail(message) { throw new Error(message); }
function positiveInteger(value, name, allowZero = false) {
  if (!Number.isInteger(value) || value < (allowZero ? 0 : 1)) fail(`${name} 必须是${allowZero ? "非负" : "正"}整数`);
}
function localFile(value, base) {
  if (typeof value !== "string" || !value || (/^[a-z][a-z0-9+.-]*:/i.test(value) && !/^[a-z]:[\\/]/i.test(value)) || /^(\/\/|\\\\)/.test(value)) fail("仅支持本地媒体文件，禁止网络/协议路径");
  const path = realpathSync(isAbsolute(value) ? value : resolve(base, value));
  if (!statSync(path).isFile()) fail(`不是媒体文件: ${path}`);
  return path;
}
function browserExecutable() {
  if (process.env.CHROME_EXECUTABLE) return localFile(process.env.CHROME_EXECUTABLE, process.cwd());
  const names = process.platform === "win32" ? ["chrome.exe", "chromium.exe", "msedge.exe"] : ["chromium", "chromium-browser", "google-chrome", "google-chrome-stable"];
  for (const name of names) {
    const result = spawnSync(process.platform === "win32" ? "where.exe" : "which", [name], { encoding: "utf8" });
    const path = result.status === 0 ? result.stdout.split(/\r?\n/)[0]?.trim() : "";
    if (path && existsSync(path)) return path;
  }
  fail("未找到本地 Chrome/Chromium，请配置 CHROME_EXECUTABLE；本工具不会自动下载浏览器。");
}

let staging;
let temporaryOutput;
try {
  const [timelineArgument, outputArgument, ...extra] = process.argv.slice(2);
  if (!timelineArgument || !outputArgument || extra.length) fail("用法: node tools/render_episode.mjs TIMELINE.json OUTPUT.mp4（拒绝覆盖）");
  const manifestPath = localFile(timelineArgument, process.cwd());
  const outputPath = resolve(outputArgument);
  if (extname(outputPath).toLowerCase() !== ".mp4") fail("输出必须为 .mp4");
  if (existsSync(outputPath)) fail(`禁止静默覆盖现有输出: ${outputPath}`);
  const timeline = JSON.parse(readFileSync(manifestPath, "utf8"));
  if (timeline.schema !== "short-drama.timeline/v1") fail("不支持的时间线 schema");
  for (const key of ["fps", "width", "height", "duration_frames"]) positiveInteger(timeline[key], key);
  if (timeline.width % 2 || timeline.height % 2) fail("H.264 宽高必须为偶数");
  if (!Array.isArray(timeline.shots) || !timeline.shots.length) fail("时间线没有镜头");
  if (!Array.isArray(timeline.tracks) || !Array.isArray(timeline.subtitles)) fail("时间线 tracks/subtitles 必须为数组");
  // Validate structural coverage again for users invoking this helper directly.
  const pythonCommand = process.env.PYTHON || process.execPath;
  const pythonPrefix = process.env.PYTHON ? [] : [join(projectRoot, "tools/python.mjs")];
  const check = spawnSync(pythonCommand, [...pythonPrefix, "-c", "import json,sys; from short_drama.timeline import validate_timeline; from short_drama.media import validate_timeline_media; t=json.load(open(sys.argv[1],encoding='utf-8')); errors=validate_timeline(t); errors+=validate_timeline_media(t) if not errors else []; print('\\n'.join(errors)); sys.exit(bool(errors))", manifestPath], { cwd: dirname(manifestPath), env: { ...process.env, PYTHONPATH: join(projectRoot, "src") }, encoding: "utf8" });
  if (check.status !== 0) fail(check.stderr?.trim() || check.stdout?.trim() || "时间线校验失败（需要 Python 3）");
  const browserPath = browserExecutable();
  staging = mkdtempSync(join(tmpdir(), "short-drama-render-"));
  const publicDir = join(staging, "public");
  mkdirSync(join(publicDir, "media"), { recursive: true });
  const stage = (source, expectedHash) => {
    const path = localFile(source, dirname(manifestPath));
    const digest = createHash("sha256");
    const handle = openSync(path, "r");
    try {
      const chunk = Buffer.alloc(1024 * 1024);
      let count;
      while ((count = readSync(handle, chunk, 0, chunk.length, null)) > 0) digest.update(chunk.subarray(0, count));
    } finally { closeSync(handle); }
    const hash = digest.digest("hex");
    if (expectedHash && expectedHash !== hash) fail(`媒体哈希不匹配: ${path}`);
    const extension = extname(path).toLowerCase();
    if (!/^\.[a-z0-9]+$/.test(extension)) fail(`不支持媒体扩展名: ${extension}`);
    const relative = `media/${hash}${extension}`;
    const destination = join(publicDir, relative);
    if (!existsSync(destination)) copyFileSync(path, destination);
    return relative;
  };
  for (const shot of timeline.shots) shot.media.path = stage(shot.media.path, shot.media.sha256);
  for (const track of timeline.tracks) track.path = stage(track.path, track.sha256);
  const propsPath = join(staging, "props.json");
  writeFileSync(propsPath, JSON.stringify({ timeline }), "utf8");
  mkdirSync(dirname(outputPath), { recursive: true });
  // Render to a unique sibling. Atomic hard-link publishing fails if another
  // process creates the requested target during the render, preserving it.
  const outputWork = mkdtempSync(join(dirname(outputPath), ".episode-render-"));
  temporaryOutput = outputWork;
  const renderedFile = join(outputWork, "episode.mp4");
  const packagePath = require.resolve("@remotion/cli/package.json");
  const cliPackage = JSON.parse(readFileSync(packagePath, "utf8"));
  const cliPath = join(dirname(packagePath), cliPackage.bin.remotion);
  const result = spawnSync(process.execPath, [cliPath, "render", join(projectRoot, "src/remotion/index.ts"), "ProductionEpisode", renderedFile, "--props", propsPath, "--public-dir", publicDir, "--browser-executable", browserPath, "--chrome-mode", "chrome-for-testing", "--codec", "h264", "--audio-codec", "aac", "--enforce-audio-track", "--pixel-format", "yuv420p", "--concurrency", "2"], { cwd: projectRoot, stdio: "inherit" });
  if (result.error || result.status !== 0) fail(result.error?.message || `Remotion 渲染失败: ${result.status}`);
  linkSync(renderedFile, outputPath);
  console.log(`已渲染技术/制作时间线: ${outputPath}`);
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
} finally {
  if (staging) rmSync(staging, { recursive: true, force: true });
  if (temporaryOutput) rmSync(temporaryOutput, { recursive: true, force: true });
}

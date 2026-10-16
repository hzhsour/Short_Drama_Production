import { spawnSync } from "node:child_process";

if (!process.env.npm_execpath) {
  console.error("请通过 npm run check 调用完整检查。");
  process.exit(1);
}
for (const command of [["test"], ["run", "validate"], ["run", "typecheck"]]) {
  const result = spawnSync(process.execPath, [process.env.npm_execpath, ...command], { stdio: "inherit" });
  if (result.status !== 0) process.exit(result.status ?? 1);
}

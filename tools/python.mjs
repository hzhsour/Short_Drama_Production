import { spawnSync } from "node:child_process";

const choices = process.env.PYTHON_EXECUTABLE
  ? [[process.env.PYTHON_EXECUTABLE]]
  : process.platform === "win32"
    ? [["py", "-3"], ["python"], ["python3"]]
    : [["python3"], ["python"]];
let selected;
for (const [executable, ...prefix] of choices) {
  const check = spawnSync(executable, [...prefix, "--version"], { encoding: "utf8" });
  const version = `${check.stdout ?? ""}${check.stderr ?? ""}`.match(/Python (\d+)\.(\d+)/);
  if (check.status === 0 && version && (Number(version[1]) > 3 || (Number(version[1]) === 3 && Number(version[2]) >= 10))) {
    selected = [executable, ...prefix];
    break;
  }
}
if (!selected) {
  console.error("需要 Python 3.10+。可用 PYTHON_EXECUTABLE 指定已安装的解释器路径。");
  process.exit(1);
}
const [executable, ...prefix] = selected;
const result = spawnSync(executable, [...prefix, ...process.argv.slice(2)], { stdio: "inherit" });
if (result.error) console.error(result.error.message);
process.exit(result.status ?? 1);

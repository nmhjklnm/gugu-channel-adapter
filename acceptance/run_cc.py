"""用真 Claude Code(-p) 验收一条渠道链路: 隔离 HOME、指向网关、挂带问题 schema 的 stub MCP, 看含工具往返的链路是否真通。
 用法: [EFFORT=xhigh] run_cc.py <base_url> <token> <label> [model]   (model 默认 gemini-3.8-flash)
 验收标准: 三项都 is_error=False 且回显 STUB-OK-7731 / gemini-link-ok；「hi 能回」不算通。"""
import json, os, subprocess, sys, tempfile, time
base, token, label = sys.argv[1], sys.argv[2], sys.argv[3]
MODEL = sys.argv[4] if len(sys.argv) > 4 else "gemini-3.8-flash"
EFFORT = os.environ.get("EFFORT")   # 例: EFFORT=xhigh，复现 /effort xhigh 的请求形态
here = os.path.dirname(os.path.abspath(__file__))
MCP = os.path.join(tempfile.mkdtemp(prefix="cc-mcp-"), "mcp.json")
json.dump({"mcpServers": {"stub": {"command": "python3", "args": [os.path.join(here, "stub_mcp.py")]}}}, open(MCP, "w"))
home = tempfile.mkdtemp(prefix="cc-real-")
cwd = tempfile.mkdtemp(prefix="cc-cwd-")
env = {"PATH": os.environ["PATH"], "HOME": home, "ANTHROPIC_BASE_URL": base, "ANTHROPIC_API_KEY": token,
       "DISABLE_TELEMETRY": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}
def run(name, prompt, allowed, max_turns=5):
    t = time.time()
    cmd = ["claude", "-p", prompt, "--model", MODEL, "--mcp-config", MCP,
           "--max-turns", str(max_turns), "--output-format", "json"]
    if EFFORT: cmd += ["--effort", EFFORT]
    for a in allowed: cmd += ["--allowedTools", a]
    try:
        r = subprocess.run(cmd, env=env, cwd=cwd, capture_output=True, text=True, timeout=240)
        out = r.stdout.strip()
        try:
            d = json.loads(out)
            res = d.get("result") if isinstance(d, dict) else str(d)[:200]
            info = f"is_error={d.get('is_error')} turns={d.get('num_turns')} result={str(res)[:160]!r}"
        except Exception:
            info = f"exit={r.returncode} stdout={out[:200]!r} stderr={r.stderr.strip()[:300]!r}"
    except subprocess.TimeoutExpired:
        info = "TIMEOUT 240s"
    print(f"[{label}] {name:26s} {time.time()-t:5.1f}s  {info}", flush=True)
run("1 hi", "hi", [])
run("2 调 MCP 桩工具", "请调用 mcp__stub__echo_stub 工具，text 参数填 hello，然后把工具返回的完整内容原样告诉我。", ["mcp__stub__echo_stub", "mcp__stub__query_stub"])
run("3 跑 Bash 命令", "请运行命令 echo gemini-link-ok，然后告诉我命令输出。", ["Bash(echo:*)"])

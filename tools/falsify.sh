#!/usr/bin/env bash
# L0 真相层：对抗性审查断言的反向执行。
#
# 本脚本把 SPEC 中的七条强断言（A1-A7）变成可运行的反向检查，回答同一个问题：
#
#   这条断言，今天还成立吗？
#
# 状态语义（务必区分）：
#   PRESENT  缺陷仍存在 —— 断言成立，SPEC 描述的问题还没修
#   FIXED    缺陷已消除 —— 断言不再成立
#   UNKNOWN  无法离线判定 —— 需要运行时数据或外部环境
#
# 默认只报告，不失败（exit 0）。加 --gate 则在存在 PRESENT 时 exit 1。
#
# 用法：
#   bash tools/falsify.sh
#   bash tools/falsify.sh --gate
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 2

GATE=0
[ "${1:-}" = "--gate" ] && GATE=1

PYTHON="${PYTHON:-.venv/bin/python}"
[ -x "$PYTHON" ] || PYTHON="python3"

fixed=0
present=0
unknown=0
declare -a LINES=()

record() {
  local id="$1" claim="$2" status="$3" evidence="$4"
  case "$status" in
    FIXED) fixed=$((fixed + 1)) ;;
    PRESENT) present=$((present + 1)) ;;
    *) unknown=$((unknown + 1)) ;;
  esac
  printf '%-4s %s\n' "$id" "$claim"
  printf '     状态: %s\n' "$status"
  printf '     证据: %s\n\n' "$evidence"
}

echo "=============================================================="
echo " L0 证伪报告 —— 断言的实际状态"
echo " 生成时间: 不记录（本报告必须可重复得到相同结论）"
echo "=============================================================="
echo

# ---------------------------------------------------------------- A1
container_decls=$(grep -c '^\[\[containers\]\]' frontend/cloudflare/wrangler.toml 2>/dev/null) || container_decls=0
# 只统计真实调用点：排除 tests/ 与被调用模块自身（collect-cycle.ts 是定义处）
wired=$(grep -rn "runCollectCycle" frontend/cloudflare --include=*.ts --include=*.mts 2>/dev/null \
  | grep -v "tests/" | grep -vc "collect-cycle.ts:" || true)
a1_evidence="[[containers]] 声明数=${container_decls}；runCollectCycle 真实调用点=${wired}"
if [ "$container_decls" -eq 0 ] && [ "$wired" -gt 0 ]; then
  record "A1" "\"零成本\"叙事成立：无付费 Container，采集已由 Worker 原生承担" "FIXED" "$a1_evidence"
else
  record "A1" "\"零成本\"叙事成立：无付费 Container，采集已由 Worker 原生承担" "PRESENT" \
    "${a1_evidence}；付费 Container 仍在，Worker 原生采集未被接线"
fi

# ---------------------------------------------------------------- A2
a2_threshold=0
a2_judge=0
grep -q 'confidence_threshold_high: float = 0.85' src/news_sentry/core/confidence_router.py 2>/dev/null \
  && a2_threshold=1
grep -q 'confidence = int(classification.get("confidence", 50))' \
  src/news_sentry/skills/judge/rules_judge.py 2>/dev/null && a2_judge=1
a2_evidence="confidence_router 阈值 0.85 存在=${a2_threshold}；rules_judge 产出 0-100 整数=${a2_judge}"
if [ "$a2_threshold" -eq 0 ] || [ "$a2_judge" -eq 0 ]; then
  record "A2" "研判链路量纲一致，AI 升级分支可达" "FIXED" "$a2_evidence"
else
  record "A2" "研判链路量纲一致，AI 升级分支可达" "PRESENT" \
    "${a2_evidence}；0.85 与 0-100 整数比较恒真，AI 升级在生产不可达"
fi

# ---------------------------------------------------------------- A3
a3_evidence=""
a3_status="FIXED"
if ! $PYTHON tools/gen_metrics.py --check >/dev/null 2>&1; then
  a3_status="PRESENT"
  a3_evidence="gen_metrics --check 失败：事实基线与工作区不一致"
elif ! $PYTHON tools/render_docs.py --check >/dev/null 2>&1; then
  a3_status="PRESENT"
  a3_evidence="render_docs --check 失败：文档生成区间与事实基线不一致"
fi
pinned=$(grep -nE '\*\*Commit:\*\*|c2a052e0' AGENTS.md README.md 2>/dev/null | wc -l)
if [ "$pinned" -gt 0 ]; then
  a3_status="PRESENT"
  a3_evidence="${a3_evidence:+$a3_evidence；}文档中存在固定 commit 引用 ${pinned} 处"
fi
[ -z "$a3_evidence" ] && a3_evidence="生成物与事实基线一致；文档无固定 commit 引用"
record "A3" "文档规模数字可验证且唯一来源，无失效的 commit 引用" "$a3_status" "$a3_evidence"

# ---------------------------------------------------------------- A4
golden_dir=0
[ -d fixtures/golden ] && golden_dir=1
parity_job=$(grep -rl "parity" .github/workflows/ 2>/dev/null | wc -l)
a4_evidence="fixtures/golden 目录存在=${golden_dir}；CI 中 parity job 数=${parity_job}"
if [ "$golden_dir" -eq 1 ] && [ "$parity_job" -gt 0 ]; then
  record "A4" "跨运行时对等性由共享 golden fixture 与 CI 门禁强制" "FIXED" "$a4_evidence"
else
  record "A4" "跨运行时对等性由共享 golden fixture 与 CI 门禁强制" "PRESENT" \
    "${a4_evidence}；对等性仍依赖手抄常量，单边修改不可被发现"
fi

# ---------------------------------------------------------------- A5
a5_reads=$($PYTHON - <<'PY' 2>/dev/null || echo "error"
import ast, pathlib
source = pathlib.Path("src/news_sentry/core/async_run.py").read_text(encoding="utf-8")
tree = ast.parse(source)
targets = [
    node for node in ast.walk(tree)
    if isinstance(node, ast.AsyncFunctionDef) and node.lineno in (230, 511)
]
reads = 0
for fn in targets:
    body = ast.dump(ast.Module(body=fn.body, type_ignores=[]))
    if "Attribute(value=Name(id='cache_mgr'" in body:
        reads += 1
print(reads)
PY
)
if [ "$a5_reads" = "error" ]; then
  record "A5" "LLM 缓存已接入采集/研判热路径" "UNKNOWN" "无法解析 async_run.py"
elif [ "$a5_reads" -gt 0 ]; then
  record "A5" "LLM 缓存已接入采集/研判热路径" "FIXED" "cache_mgr 在函数体内被读取：${a5_reads} 处"
else
  record "A5" "LLM 缓存已接入采集/研判热路径" "PRESENT" \
    "cache_mgr 仅作为参数传递，函数体内 0 处读取；缓存实际未生效"
fi

# ---------------------------------------------------------------- A6
stale_gate=$(grep -c 'reasonCodes.push("stale\|reasonCodes.push("no_recent\|reasonCodes.push("collection_stale' \
  frontend/cloudflare/workers/lib/health-status.ts 2>/dev/null) || stale_gate=0
if [ "$stale_gate" -gt 0 ]; then
  record "A6" "采集停滞会导致 health 非 ok（健康语义不再失真）" "FIXED" \
    "health-status.ts 存在陈旧性 reason code：${stale_gate} 处"
else
  record "A6" "采集停滞会导致 health 非 ok（健康语义不再失真）" "PRESENT" \
    "health-status.ts 无任何陈旧性 reason code（静态代理判定，最终结论需运行时验证）"
fi

# ---------------------------------------------------------------- A7
literal=$(grep -c 'index_event(event, target_id, "drafts"' src/news_sentry/core/async_run.py 2>/dev/null) || literal=0
mapping=$(grep -rn "def stage_to_dir\|def stage_to_directory" src/news_sentry/ 2>/dev/null | wc -l)
a7_evidence="索引写入使用目录名字面量=${literal} 处；stage→dir 映射函数数=${mapping}"
if [ "$literal" -eq 0 ] || [ "$mapping" -gt 0 ]; then
  record "A7" "目录与 pipeline_stage 的正交关系有单一仲裁映射" "FIXED" "$a7_evidence"
else
  record "A7" "目录与 pipeline_stage 的正交关系有单一仲裁映射" "PRESENT" \
    "${a7_evidence}；两套表示已在语义上分叉且无仲裁者"
fi

echo "=============================================================="
printf ' 汇总: FIXED=%d  PRESENT=%d  UNKNOWN=%d\n' "$fixed" "$present" "$unknown"
echo " PRESENT 表示 SPEC 描述的缺陷仍然存在，不是脚本失败。"
echo "=============================================================="

if [ "$GATE" -eq 1 ] && [ "$present" -gt 0 ]; then
  exit 1
fi
exit 0

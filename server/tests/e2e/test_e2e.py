"""
Lite Ailoha 全链路测试脚本。

用法:
    cd server
    python tests/e2e/test_e2e.py                    # 默认用 test_1.jpg
    python tests/e2e/test_e2e.py --image test.png   # 指定图片

依赖: 服务端运行在 http://localhost:8080
输出: tests/e2e/output/report_YYYYMMDD_HHMMSS.txt
"""
import base64
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# ── 配置 ──────────────────────────────────────────────────────────────
SERVER = "http://127.0.0.1:8080"
INPUT_DIR = Path(__file__).parent / "input"
OUTPUT_DIR = Path(__file__).parent / "output"
DEFAULT_IMAGE = "test_1.jpg"
TIMEOUT = 600  # SSE 流超时（秒），完整管道约 5-6 分钟


def main():
    image_name = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--image" else DEFAULT_IMAGE
    image_path = INPUT_DIR / image_name
    if not image_path.exists():
        print(f"❌ 图片不存在: {image_path}")
        print(f"   可用图片: {list(INPUT_DIR.glob('*'))}")
        sys.exit(1)

    report = Report(image_name)

    # ── [1/6] 健康检查 ─────────────────────────────────────────────────
    t0 = time.time()
    try:
        with urllib.request.urlopen(f"{SERVER}/health", timeout=5) as resp:
            health = json.loads(resp.read())
        report.step(1, "健康检查", True, time.time() - t0, health)
    except Exception as e:
        report.step(1, "健康检查", False, time.time() - t0, str(e))
        return report.save_and_exit(1)

    # ── [2/6] 阶段一: 分析截图 ──────────────────────────────────────────
    t0 = time.time()
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()
    report.info(f"图片: {image_name} | base64={len(img_b64)//1024}KB")

    body = json.dumps({"image": img_b64, "user_context": "全链路自动化测试"}).encode()
    req = urllib.request.Request(
        f"{SERVER}/api/v1/analyze",
        data=body,
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )

    session_id = None
    sse_events = []
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            for line in resp:
                decoded = line.decode("utf-8").rstrip()
                if not decoded or ": ping" in decoded:
                    continue
                sse_events.append(decoded)
                # 提取 session_id（从 struct 事件的 data JSON 中取）
                if session_id is None and "event: struct" in decoded:
                    pass  # session_id 不在 SSE 里，稍后从 DB 查
        elapsed = time.time() - t0
        report.step(2, "阶段一: 分析截图", True, elapsed, {"events": len(sse_events)})
        for ev in sse_events:
            report.sse_event(ev)
    except Exception as e:
        report.step(2, "阶段一: 分析截图", False, time.time() - t0, str(e))
        return report.save_and_exit(1)

    # 从数据库查 session_id
    session_id = _get_latest_session_id()
    if not session_id:
        report.step(2, "阶段一", False, 0, "无法从数据库获取 session_id")
        return report.save_and_exit(1)
    report.info(f"Session: {session_id}")

    # ── [3/6] 查询会话 ──────────────────────────────────────────────────
    t0 = time.time()
    try:
        with urllib.request.urlopen(f"{SERVER}/api/v1/sessions/{session_id}", timeout=5) as resp:
            session_data = json.loads(resp.read())
        state = session_data.get("session_state", "?")
        cards = session_data.get("cards", [])
        report.step(3, "查询会话", True, time.time() - t0, {
            "session_state": state,
            "cards": len(cards),
        })
        for c in cards:
            report.info(f"  card: [{c['type']}] {c['id']} — {c['summary'][:60]}")
    except Exception as e:
        report.step(3, "查询会话", False, time.time() - t0, str(e))
        return report.save_and_exit(1)

    # ── [4/6] 用户操作 ──────────────────────────────────────────────────
    t0 = time.time()
    try:
        for i, card in enumerate(cards):
            action = "confirm" if i == 0 else "cancel"  # 确认第一张，取消其余
            body = json.dumps({
                "session_id": session_id,
                "type": card["type"],
                "summary": card["summary"],
            }).encode()
            req = urllib.request.Request(
                f"{SERVER}/api/v1/actions/{card['id']}/{action}",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                json.loads(resp.read())
            report.info(f"  {action}: [{card['type']}] {card['summary'][:50]}")
        report.step(4, "用户操作", True, time.time() - t0, {
            "confirmed": min(1, len(cards)),
            "cancelled": max(0, len(cards) - 1),
        })
    except Exception as e:
        report.step(4, "用户操作", False, time.time() - t0, str(e))
        # 不致命，继续

    # ── [5/6] 阶段二: 生成洞察 ──────────────────────────────────────────
    t0 = time.time()
    insight_sse = []
    try:
        req = urllib.request.Request(
            f"{SERVER}/api/v1/sessions/{session_id}/insight",
            headers={"Accept": "text/event-stream"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            for line in resp:
                decoded = line.decode("utf-8").rstrip()
                if not decoded or ": ping" in decoded:
                    continue
                insight_sse.append(decoded)
        report.step(5, "阶段二: 生成洞察", True, time.time() - t0, {"events": len(insight_sse)})
        for ev in insight_sse:
            report.sse_event(ev)
    except Exception as e:
        report.step(5, "阶段二: 生成洞察", False, time.time() - t0, str(e))

    # ── [6/6] 最终验证 ──────────────────────────────────────────────────
    t0 = time.time()
    try:
        with urllib.request.urlopen(f"{SERVER}/api/v1/sessions/{session_id}", timeout=5) as resp:
            final = json.loads(resp.read())
        state = final.get("session_state", "?")
        insight = final.get("insight")
        passed = state == "COMPLETED" and insight is not None
        report.step(6, "最终验证", passed, time.time() - t0, {
            "session_state": state,
            "insight": f"{len(insight)} chars" if insight else "None",
        })
        if insight:
            report.info(f"洞察摘要: {insight[:200]}...")
    except Exception as e:
        report.step(6, "最终验证", False, time.time() - t0, str(e))

    report.save_and_exit(0 if report.all_passed() else 1)


# ── 辅助函数 ────────────────────────────────────────────────────────────

def _get_latest_session_id() -> str | None:
    """从 SQLite 获取最新 session_id。"""
    import sqlite3
    db_path = Path(__file__).parent.parent.parent / "lite_ailoha.db"
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.execute(
            "SELECT session_id FROM analyze_sessions ORDER BY created_at DESC LIMIT 1"
        )
        row = cur.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None


# ── 报告生成器 ──────────────────────────────────────────────────────────

class Report:
    def __init__(self, image_name: str):
        self.image_name = image_name
        self.start_time = datetime.now()
        self.lines: list[str] = []
        self.steps: list[dict] = []
        self._all_passed = True

    def info(self, text: str):
        self.lines.append(f"  {text}")

    def sse_event(self, raw: str):
        """解析一行 SSE 输出为可读格式。"""
        # 提取 event:/id:/data: 行
        self.lines.append(f"    {raw[:300]}")

    def step(self, num: int, name: str, passed: bool, elapsed: float, detail=None):
        status = "✅" if passed else "❌"
        self.steps.append({"num": num, "name": name, "passed": passed, "elapsed": elapsed, "detail": detail})
        self.lines.append(f"[{num}/6] {name} {status} ({elapsed:.1f}s)")
        if detail:
            if isinstance(detail, dict):
                for k, v in detail.items():
                    self.lines.append(f"       {k}: {v}")
            else:
                self.lines.append(f"       {detail}")
        if not passed:
            self._all_passed = False
        self.lines.append("")

    def all_passed(self) -> bool:
        return self._all_passed

    def save_and_exit(self, exit_code: int):
        elapsed_total = (datetime.now() - self.start_time).total_seconds()
        passed = sum(1 for s in self.steps if s["passed"])
        total = len(self.steps)

        header = []
        header.append("=" * 60)
        header.append("Lite Ailoha 全链路测试报告")
        header.append(f"时间: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        header.append(f"图片: {self.image_name}")
        header.append(f"结果: {passed}/{total} 通过")
        header.append(f"总耗时: {elapsed_total:.1f}s")
        header.append("=" * 60)
        header.append("")

        report = "\n".join(header + self.lines)
        timestamp = self.start_time.strftime("%Y%m%d_%H%M%S")
        report_path = OUTPUT_DIR / f"report_{timestamp}.txt"
        report_path.write_text(report, encoding="utf-8")
        print(report)
        print(f"报告已保存: {report_path}")
        sys.exit(exit_code)


if __name__ == "__main__":
    main()

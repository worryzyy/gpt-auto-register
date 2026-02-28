import builtins
import os
import queue
import random
import re
import threading
import time
from datetime import datetime

from flask import Flask, jsonify, request, send_from_directory

import browser
import email_service
import main
from config import cfg

app = Flask(__name__, static_url_path="")


class AppState:
    def __init__(self):
        self.is_running = False
        self.stop_requested = False
        self.success_count = 0
        self.fail_count = 0
        self.total_count = 0
        self.worker_count = 1
        self.current_action = "等待启动"
        self.logs = []
        self.lock = threading.Lock()

        self.last_frame = None
        self.frame_lock = threading.Lock()

    def add_log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        with self.lock:
            self.logs.append(f"[{timestamp}] {message}")
            if len(self.logs) > 1000:
                self.logs.pop(0)

    def get_logs(self, start_index=0):
        with self.lock:
            return list(self.logs[start_index:])

    def update_frame(self, frame_bytes):
        with self.frame_lock:
            self.last_frame = frame_bytes

    def get_frame(self):
        with self.frame_lock:
            return self.last_frame

    def reset_run(self, total_count: int, worker_count: int):
        with self.lock:
            self.is_running = True
            self.stop_requested = False
            self.success_count = 0
            self.fail_count = 0
            self.total_count = total_count
            self.worker_count = worker_count
            self.current_action = f"任务启动，目标 {total_count}，并发 {worker_count}"

    def finish_run(self):
        with self.lock:
            self.is_running = False
            self.current_action = "任务已完成"

    def set_current_action(self, message: str):
        with self.lock:
            self.current_action = message

    def add_result(self, success: bool):
        with self.lock:
            if success:
                self.success_count += 1
            else:
                self.fail_count += 1
            return self.success_count + self.fail_count

    def snapshot(self):
        with self.lock:
            return {
                "is_running": self.is_running,
                "current_action": self.current_action,
                "success": self.success_count,
                "fail": self.fail_count,
                "total_count": self.total_count,
                "worker_count": self.worker_count,
            }


state = AppState()


def parse_sub2api_status(status_text):
    if not status_text:
        return status_text, None

    match = re.search(
        r"^(?P<base>.*?)\s*[（(]\s*id\s*[:=]\s*(?P<id>\d+)\s*[)）]\s*$",
        status_text,
        re.IGNORECASE,
    )
    if not match:
        return status_text, None

    base_status = match.group("base").strip() or status_text
    sub2api_id = int(match.group("id"))
    return base_status, sub2api_id


original_print = builtins.print


def hooked_print(*args, **kwargs):
    sep = kwargs.get("sep", " ")
    msg = sep.join(map(str, args))
    state.add_log(msg)
    original_print(*args, **kwargs)


main.print = hooked_print
browser.print = hooked_print
email_service.print = hooked_print

try:
    import sub2api_service

    sub2api_service.print = hooked_print
except ImportError:
    pass


def worker_thread(total_count: int, worker_count: int):
    total_count = max(1, int(total_count))
    worker_count = max(1, min(int(worker_count), total_count))
    state.reset_run(total_count, worker_count)
    state.update_frame(None)

    main.print(f"🚀 开始批量任务：总数={total_count}，并发={worker_count}")

    try:
        task_queue = queue.Queue()
        for index in range(1, total_count + 1):
            task_queue.put(index)

        def monitor(driver, step):
            if state.stop_requested:
                main.print("🛑 检测到停止请求，正在中断当前任务...")
                raise InterruptedError("用户请求停止")

            try:
                png_bytes = driver.get_screenshot_as_png()
                state.update_frame(png_bytes)
            except Exception as exc:
                main.print(f"⚠️ 截图流更新失败: {exc}")

        def register_worker(worker_id: int):
            while not state.stop_requested:
                try:
                    task_index = task_queue.get_nowait()
                except queue.Empty:
                    break

                state.set_current_action(
                    f"Worker-{worker_id} 正在注册 ({task_index}/{total_count})"
                )

                try:
                    _, _, success = main.register_one_account(monitor_callback=monitor)
                    done = state.add_result(success)
                    status_text = "成功" if success else "失败"
                    main.print(
                        f"{'✅' if success else '❌'} Worker-{worker_id} 完成 "
                        f"#{task_index}（{status_text}） | 进度 {done}/{total_count}"
                    )
                    state.set_current_action(
                        f"进行中：{done}/{total_count}（并发 {worker_count}）"
                    )
                except InterruptedError:
                    state.stop_requested = True
                    main.print(f"🛑 Worker-{worker_id} 中断任务")
                    break
                except Exception as exc:
                    done = state.add_result(False)
                    main.print(f"❌ Worker-{worker_id} 异常: {exc}")
                    state.set_current_action(
                        f"进行中：{done}/{total_count}（并发 {worker_count}）"
                    )
                finally:
                    task_queue.task_done()

                if state.stop_requested:
                    break

                if not task_queue.empty():
                    wait_time = random.randint(cfg.batch.interval_min, cfg.batch.interval_max)
                    main.print(f"⏳ Worker-{worker_id} 冷却 {wait_time}s")
                    for _ in range(wait_time):
                        if state.stop_requested:
                            break
                        time.sleep(1)

        workers = []
        for worker_id in range(1, worker_count + 1):
            thread = threading.Thread(target=register_worker, args=(worker_id,), daemon=True)
            thread.start()
            workers.append(thread)

        for thread in workers:
            thread.join()

        if state.stop_requested:
            main.print("🛑 任务已停止")
        else:
            main.print("✅ 全部任务执行完成")

    except Exception as exc:
        main.print(f"💥 严重错误: {exc}")
    finally:
        state.finish_run()
        main.print("🏁 任务结束")


def gen_frames():
    while True:
        frame = state.get_frame()
        if frame:
            yield (
                b"--frame\r\n"
                b"Content-Type: image/png\r\n\r\n" + frame + b"\r\n"
            )
        time.sleep(0.5)


@app.route("/video_feed")
def video_feed():
    return Flask.response_class(
        gen_frames(), mimetype="multipart/x-mixed-replace; boundary=frame"
    )


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/status")
def get_status():
    total_inventory = 0
    if os.path.exists(cfg.files.accounts_file):
        try:
            with open(cfg.files.accounts_file, "r", encoding="utf-8") as file_obj:
                total_inventory = sum(1 for line in file_obj if "@" in line)
        except Exception:
            pass

    data = state.snapshot()
    data["total_inventory"] = total_inventory
    data["logs"] = state.get_logs(int(request.args.get("log_index", 0)))
    return jsonify(data)


@app.route("/api/start", methods=["POST"])
def start_task():
    if state.is_running:
        return jsonify({"error": "Already running"}), 400

    data = request.get_json(silent=True) or {}
    default_workers = getattr(cfg.batch, "worker_count", 1)

    try:
        count = int(data.get("count", 1))
        worker_count = int(data.get("worker_count", default_workers))
    except (TypeError, ValueError):
        return jsonify({"error": "count and worker_count must be integers"}), 400

    if count < 1:
        return jsonify({"error": "count must be >= 1"}), 400
    if worker_count < 1:
        return jsonify({"error": "worker_count must be >= 1"}), 400

    worker_count = min(worker_count, count)
    threading.Thread(
        target=worker_thread,
        args=(count, worker_count),
        daemon=True,
    ).start()
    return jsonify({"status": "started", "count": count, "worker_count": worker_count})


@app.route("/api/stop", methods=["POST"])
def stop_task():
    if not state.is_running:
        return jsonify({"error": "Not running"}), 400

    state.stop_requested = True
    state.set_current_action("停止中...")
    return jsonify({"status": "stopping"})


@app.route("/api/accounts")
def get_accounts():
    accounts = []
    if os.path.exists(cfg.files.accounts_file):
        try:
            with open(cfg.files.accounts_file, "r", encoding="utf-8") as file_obj:
                for line in file_obj:
                    row = line.strip()
                    if not row:
                        continue

                    if "----" in row:
                        parts = [part.strip() for part in row.split("----")]
                        if len(parts) >= 4:
                            email, password, time_text, status = parts[:4]
                        else:
                            continue
                    else:
                        parts = [part.strip() for part in row.split("|")]
                        if len(parts) >= 4:
                            email, password, status, time_text = parts[:4]
                        elif len(parts) >= 2:
                            email, password = parts[:2]
                            status = parts[2] if len(parts) > 2 else ""
                            time_text = parts[3] if len(parts) > 3 else ""
                        else:
                            continue

                    if email:
                        parsed_status, sub2api_id = parse_sub2api_status(status)
                        accounts.append(
                            {
                                "email": email,
                                "password": password,
                                "status": parsed_status,
                                "sub2api_id": sub2api_id,
                                "time": time_text,
                            }
                        )
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    return jsonify(accounts[::-1])


if __name__ == "__main__":
    import argparse
    from waitress import serve

    parser = argparse.ArgumentParser(description="ChatGPT 自动注册 Web 服务")
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="监听地址（默认: 0.0.0.0）",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help="监听端口（默认: 5000）",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=6,
        help="Waitress 线程数（默认: 6）",
    )
    args = parser.parse_args()

    if args.port < 1 or args.port > 65535:
        raise SystemExit("port 必须在 1-65535 之间")
    if args.threads < 1:
        raise SystemExit("threads 必须 >= 1")

    display_host = "localhost" if args.host in ("0.0.0.0", "::") else args.host
    print(f"🌐 Web Server started at http://{display_host}:{args.port}")
    serve(app, host=args.host, port=args.port, threads=args.threads)

"""
ChatGPT 账号自动注册脚本
主程序入口

使用方法:
    1. 修改 config.py 中的配置
    2. 运行: python main.py

依赖安装:
    pip install undetected-chromedriver selenium requests

功能:
    - 自动创建临时邮箱（基于 cloudflare_temp_email）
    - 自动完成 ChatGPT 注册流程
    - 自动提取验证码
    - 批量注册支持
"""

import argparse
import queue
import random
import threading
import time

from config import (
    TOTAL_ACCOUNTS,
    BATCH_WORKER_COUNT,
    BATCH_INTERVAL_MIN,
    BATCH_INTERVAL_MAX,
    cfg
)
from utils import generate_random_password, save_to_txt, update_account_status
from email_service import create_temp_email, wait_for_verification_email
from browser import (
    create_driver,
    fill_signup_form,
    enter_verification_code,
    fill_profile_info,
    perform_openai_oauth
)


def register_one_account(monitor_callback=None):
    """
    注册单个账号
    :param monitor_callback: 回调函数 func(driver, step_name)，用于截图和中断检查
    
    返回:
        tuple: (邮箱, 密码, 是否成功)
    """
    driver = None
    email = None
    password = None
    success = False
    
    # 辅助函数：执行回调
    def _report(step_name):
        if monitor_callback and driver:
            monitor_callback(driver, step_name)

    try:
        # 1. 创建临时邮箱
        email, jwt_token = create_temp_email()
        if not email:
            print("❌ 创建邮箱失败，终止注册")
            return None, None, False
        
        # 2. 生成随机密码
        password = generate_random_password()
        
        # 3. 初始化浏览器
        driver = create_driver(headless=False)
        _report("init_browser")
        
        # 4. 打开注册页面
        url = "https://chat.openai.com/chat"
        print(f"🌐 正在打开 {url}...")
        driver.get(url)
        time.sleep(3)
        _report("open_page")
        
        # 5. 填写注册表单（邮箱和密码）
        if not fill_signup_form(driver, email, password):
            print("❌ 填写注册表单失败")
            return email, password, False
        _report("fill_form")
        
        # 6. 等待验证邮件
        time.sleep(5)
        verification_code = wait_for_verification_email(jwt_token)
        
        # 如果没有自动获取到验证码，提示手动输入
        if not verification_code:
            print("⚠️ 未自动获取验证码，尝试请求用户输入...")
            # 可以在这里扩展手动输入回调，暂略
            # verification_code = input("⌨️ 请手动输入验证码: ").strip()
        
        if not verification_code:
            print("❌ 未获取到验证码，终止注册")
            return email, password, False
        
        # 7. 输入验证码
        if not enter_verification_code(driver, verification_code):
            print("❌ 输入验证码失败")
            return email, password, False
        _report("enter_code")
        
        # 8. 填写个人资料
        if not fill_profile_info(driver):
            print("❌ 填写个人资料失败")
            return email, password, False
        _report("fill_profile")
        
        # 9. 保存账号信息 (注册成功)
        save_to_txt(email, password, "已注册")

        # 10. 完成注册
        print("\n" + "=" * 50)
        print("🎉 注册成功！")
        print(f"   邮箱: {email}")
        print(f"   密码: {password}")
        print("=" * 50)

        success = True
        print("⏳ 等待页面稳定...")
        time.sleep(5)
        _report("registered")

        # 11. 自动绑定到 sub2api（如果启用）
        if cfg.sub2api.enabled:
            try:
                print("\n" + "=" * 50)
                print("🔗 开始绑定到 sub2api...")
                print("=" * 50)

                if not (cfg.sub2api.base_url and cfg.sub2api.email and cfg.sub2api.password):
                    raise Exception("sub2api 已启用，但 base_url/email/password 配置不完整")

                from sub2api_service import Sub2ApiClient
                client = Sub2ApiClient(
                    cfg.sub2api.base_url,
                    cfg.sub2api.email,
                    cfg.sub2api.password
                )
                client.login()

                # 获取 OAuth 授权 URL
                auth_url, session_id = client.generate_openai_auth_url()
                _report("sub2api_oauth_start")

                # 在浏览器中执行 OAuth 授权
                code, state = perform_openai_oauth(
                    driver,
                    auth_url,
                    email,
                    password,
                    email_jwt_token=jwt_token
                )
                _report("sub2api_oauth_done")

                # 1) 创建账号（优先带并发/优先级/分组）
                created_account = client.create_account_from_oauth(
                    session_id,
                    code,
                    state,
                    name=email,
                    concurrency=cfg.sub2api.concurrency,
                    priority=cfg.sub2api.priority,
                    group_ids=(cfg.sub2api.group_ids or None)
                )

                account_id = created_account.get('id')
                if not account_id:
                    raise Exception("sub2api 创建账号成功但未返回 account_id")

                # 2) 最小字段更新兜底
                needs_update = (
                    cfg.sub2api.concurrency is not None
                    or cfg.sub2api.priority is not None
                    or bool(cfg.sub2api.group_ids)
                )
                if needs_update:
                    client.update_account(
                        account_id,
                        concurrency=cfg.sub2api.concurrency,
                        priority=cfg.sub2api.priority,
                        group_ids=(cfg.sub2api.group_ids or None)
                    )

                # 3) 查询完整参数后，按你要求调用 /api/v1/admin/accounts/{id} 做整包更新
                try:
                    latest_account = client.get_account(account_id)
                except Exception as detail_err:
                    print(f"⚠️ 查询账号详情失败，改用创建返回数据兜底: {detail_err}")
                    latest_account = created_account

                full_payload = {
                    'name': latest_account.get('name', email),
                    'notes': latest_account.get('notes', ''),
                    'proxy_id': latest_account.get('proxy_id', 0),
                    'concurrency': (
                        int(cfg.sub2api.concurrency)
                        if cfg.sub2api.concurrency is not None
                        else int(latest_account.get('concurrency', 0))
                    ),
                    'priority': (
                        int(cfg.sub2api.priority)
                        if cfg.sub2api.priority is not None
                        else int(latest_account.get('priority', 0))
                    ),
                    'rate_multiplier': latest_account.get('rate_multiplier', 1),
                    'status': latest_account.get('status', 'active'),
                    'group_ids': (
                        list(cfg.sub2api.group_ids)
                        if cfg.sub2api.group_ids
                        else list(latest_account.get('group_ids', []))
                    ),
                    'expires_at': latest_account.get('expires_at', 0),
                    'auto_pause_on_expired': latest_account.get('auto_pause_on_expired', True),
                    'credentials': latest_account.get('credentials', {}),
                    'extra': latest_account.get('extra', {}),
                }
                synced_account = client.update_account_full(account_id, full_payload)
                synced_account_id = synced_account.get('id', account_id)
                print(
                    "✅ sub2api 参数已同步:"
                    f" concurrency={synced_account.get('concurrency')},"
                    f" priority={synced_account.get('priority')},"
                    f" group_ids={synced_account.get('group_ids')}"
                )

                update_account_status(email, f"已绑定sub2api(id={synced_account_id})")
                print("✅ sub2api 绑定完成！")

            except Exception as e:
                print(f"⚠️ sub2api 绑定失败: {e}")
                update_account_status(email, "已注册(绑定失败)")
                # 启用 sub2api 时，绑定失败视为整条流程失败
                success = False
        else:
            print("✅ 注册完成，已跳过绑卡与取消订阅流程")
        
    except InterruptedError:
        print("🛑 任务已被用户强制中断")
        if email: update_account_status(email, "用户中断")
        return email, password, False
        
    except Exception as e:
        print(f"❌ 发生错误: {e}")
        # 即使出错也保存已有的账号信息（便于排查）
        if email and password:
            update_account_status(email, f"错误: {str(e)[:50]}")
    
    finally:
        if driver:
            print("🔒 正在关闭浏览器...")
            driver.quit()
    
    return email, password, success
    



def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="ChatGPT 账号批量注册工具")
    parser.add_argument(
        "-n",
        "--count",
        type=int,
        default=None,
        help=f"本次注册账号数量（默认: config.yaml 的 registration.total_accounts={TOTAL_ACCOUNTS}）",
    )
    parser.add_argument(
        "-w",
        "--worker-count",
        "--workers",
        dest="worker_count",
        type=int,
        default=None,
        help=f"并发数（默认: config.yaml 的 batch.worker_count={BATCH_WORKER_COUNT}）",
    )
    parser.add_argument(
        "--interval-min",
        type=int,
        default=None,
        help=f"任务间隔最小秒数（默认: {BATCH_INTERVAL_MIN}）",
    )
    parser.add_argument(
        "--interval-max",
        type=int,
        default=None,
        help=f"任务间隔最大秒数（默认: {BATCH_INTERVAL_MAX}）",
    )
    return parser.parse_args()


def _normalize_batch_args(total_accounts=None, worker_count=None, interval_min=None, interval_max=None):
    """合并配置与参数，并做基础校验"""
    total_accounts = TOTAL_ACCOUNTS if total_accounts is None else total_accounts
    worker_count = BATCH_WORKER_COUNT if worker_count is None else worker_count
    interval_min = BATCH_INTERVAL_MIN if interval_min is None else interval_min
    interval_max = BATCH_INTERVAL_MAX if interval_max is None else interval_max

    total_accounts = int(total_accounts)
    worker_count = int(worker_count)
    interval_min = int(interval_min)
    interval_max = int(interval_max)

    if total_accounts < 1:
        raise ValueError("count 必须 >= 1")
    if worker_count < 1:
        raise ValueError("worker_count 必须 >= 1")
    if interval_min < 0 or interval_max < 0:
        raise ValueError("interval_min/interval_max 必须 >= 0")
    if interval_min > interval_max:
        raise ValueError("interval_min 不能大于 interval_max")

    worker_count = min(worker_count, total_accounts)
    return total_accounts, worker_count, interval_min, interval_max


def run_batch(total_accounts=None, worker_count=None, interval_min=None, interval_max=None):
    """
    批量注册账号
    """
    total_accounts, worker_count, interval_min, interval_max = _normalize_batch_args(
        total_accounts=total_accounts,
        worker_count=worker_count,
        interval_min=interval_min,
        interval_max=interval_max,
    )

    print("\n" + "=" * 60)
    print(f"🚀 开始批量注册，目标数量: {total_accounts}，并发数: {worker_count}")
    print("=" * 60 + "\n")

    print("\n⚠️  免责声明：本项目仅供学习研究使用。请勿用于商业用途或违规操作。")
    print("⚠️  使用者需自行承担因违规使用导致的一切后果。\n")
    time.sleep(2)
    
    success_count = 0
    fail_count = 0
    registered_accounts = []
    
    task_queue = queue.Queue()
    for index in range(1, total_accounts + 1):
        task_queue.put(index)

    progress_lock = threading.Lock()

    def register_worker(worker_id):
        nonlocal success_count, fail_count

        while True:
            try:
                task_index = task_queue.get_nowait()
            except queue.Empty:
                return

            print("\n" + "#" * 60)
            print(f"📝 Worker-{worker_id} 正在注册第 {task_index}/{total_accounts} 个账号")
            print("#" * 60 + "\n")

            try:
                email, password, success = register_one_account()

                with progress_lock:
                    if success:
                        success_count += 1
                        registered_accounts.append((email, password))
                    else:
                        fail_count += 1

                    done = success_count + fail_count
                    print("\n" + "-" * 40)
                    print(f"📊 当前进度: {done}/{total_accounts}")
                    print(f"   ✅ 成功: {success_count}")
                    print(f"   ❌ 失败: {fail_count}")
                    print("-" * 40)

            finally:
                task_queue.task_done()

            if not task_queue.empty():
                wait_time = random.randint(interval_min, interval_max)
                print(f"\n⏳ Worker-{worker_id} 等待 {wait_time} 秒后继续...")
                time.sleep(wait_time)

    workers = []
    for worker_id in range(1, worker_count + 1):
        worker = threading.Thread(target=register_worker, args=(worker_id,), daemon=True)
        worker.start()
        workers.append(worker)

    for worker in workers:
        worker.join()
    
    # 最终统计
    print("\n" + "=" * 60)
    print("🏁 批量注册完成")
    print("=" * 60)
    print(f"   总计: {total_accounts}")
    print(f"   ✅ 成功: {success_count}")
    print(f"   ❌ 失败: {fail_count}")
    
    if registered_accounts:
        print("\n📋 成功注册的账号:")
        for email, password in registered_accounts:
            print(f"   - {email}")
    
    print("=" * 60)


if __name__ == "__main__":
    args = parse_args()
    run_batch(
        total_accounts=args.count,
        worker_count=args.worker_count,
        interval_min=args.interval_min,
        interval_max=args.interval_max,
    )

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

import time
import random

from config import (
    TOTAL_ACCOUNTS,
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
        print("📧 正在创建临时邮箱...")
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

                # 调用 sub2api 创建账号
                client.create_account_from_oauth(session_id, code, state, name=email)

                update_account_status(email, "已绑定sub2api")
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
    



def run_batch():
    """
    批量注册账号
    """
    print("\n" + "=" * 60)
    print(f"🚀 开始批量注册，目标数量: {TOTAL_ACCOUNTS}")
    print("=" * 60 + "\n")

    print("\n⚠️  免责声明：本项目仅供学习研究使用。请勿用于商业用途或违规操作。")
    print("⚠️  使用者需自行承担因违规使用导致的一切后果。\n")
    time.sleep(2)
    
    success_count = 0
    fail_count = 0
    registered_accounts = []
    
    for i in range(TOTAL_ACCOUNTS):
        print("\n" + "#" * 60)
        print(f"📝 正在注册第 {i + 1}/{TOTAL_ACCOUNTS} 个账号")
        print("#" * 60 + "\n")
        
        email, password, success = register_one_account()
        
        if success:
            success_count += 1
            registered_accounts.append((email, password))
        else:
            fail_count += 1
        
        # 显示进度
        print("\n" + "-" * 40)
        print(f"📊 当前进度: {i + 1}/{TOTAL_ACCOUNTS}")
        print(f"   ✅ 成功: {success_count}")
        print(f"   ❌ 失败: {fail_count}")
        print("-" * 40)
        
        # 如果还有下一个，等待随机时间
        if i < TOTAL_ACCOUNTS - 1:
            wait_time = random.randint(BATCH_INTERVAL_MIN, BATCH_INTERVAL_MAX)
            print(f"\n⏳ 等待 {wait_time} 秒后继续下一个注册...")
            time.sleep(wait_time)
    
    # 最终统计
    print("\n" + "=" * 60)
    print("🏁 批量注册完成")
    print("=" * 60)
    print(f"   总计: {TOTAL_ACCOUNTS}")
    print(f"   ✅ 成功: {success_count}")
    print(f"   ❌ 失败: {fail_count}")
    
    if registered_accounts:
        print("\n📋 成功注册的账号:")
        for email, password in registered_accounts:
            print(f"   - {email}")
    
    print("=" * 60)


if __name__ == "__main__":
    run_batch()

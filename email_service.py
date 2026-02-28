"""
邮箱服务模块
基于 cloudflare_temp_email 项目实现临时邮箱功能
项目地址: https://github.com/dreamhunter2333/cloudflare_temp_email
"""

import random
import string
import time
import email
from email import policy

from config import (
    EMAIL_WORKER_URL,
    EMAIL_DOMAIN,
    EMAIL_PREFIX_LENGTH,
    EMAIL_WAIT_TIMEOUT,
    EMAIL_POLL_INTERVAL,
    HTTP_TIMEOUT
)
from utils import http_session, get_user_agent, extract_verification_code

EMAIL_WORKER_BASE_URL = (EMAIL_WORKER_URL or "").rstrip("/")


def _worker_url(path: str) -> str:
    return f"{EMAIL_WORKER_BASE_URL}{path}"


def create_temp_email():
    """
    创建临时邮箱
    调用 cloudflare_temp_email 的 /api/new_address 接口
    
    注意: 服务器会自动给邮箱名称添加 'tmp' 前缀，
    因此应该使用服务器返回的 address 字段作为实际邮箱地址
    
    返回:
        tuple: (邮箱地址, JWT令牌)，失败返回 (None, None)
    """
    print("📧 正在创建临时邮箱...")
    
    # 生成随机邮箱前缀（服务器会自动添加 tmp 前缀）
    prefix = ''.join(random.choices(
        string.ascii_lowercase + string.digits, 
        k=EMAIL_PREFIX_LENGTH
    ))
    
    headers = {
        "Content-Type": "application/json",
        "User-Agent": get_user_agent()
    }
    
    try:
        # 调用创建邮箱接口
        response = http_session.post(
            _worker_url("/api/new_address"),
            headers=headers,
            json={"name": prefix},
            timeout=HTTP_TIMEOUT
        )
        
        if response.status_code == 200:
            result = response.json()
            jwt_token = result.get('jwt')
            # 使用服务器返回的实际邮箱地址（包含 tmp 前缀）
            actual_email = result.get('address')
            
            if jwt_token and actual_email:
                print(f"✅ 邮箱创建成功: {actual_email}")
                return actual_email, jwt_token
            elif jwt_token:
                # 兼容：如果服务器没有返回 address，则自己拼接
                fallback_email = f"tmp{prefix}@{EMAIL_DOMAIN}"
                print(f"✅ 邮箱创建成功: {fallback_email}")
                return fallback_email, jwt_token
            else:
                print(f"⚠️ 响应中未包含 JWT: {result}")
        else:
            print(f"❌ API 错误: HTTP {response.status_code}")
            print(f"   响应内容: {response.text[:200]}")
            
    except Exception as e:
        print(f"❌ 创建邮箱失败: {e}")
    
    return None, None


def fetch_emails(jwt_token: str, debug: bool = False):
    """
    获取邮件列表
    
    参数:
        jwt_token: 创建邮箱时获得的 JWT 令牌
    
    返回:
        list: 邮件列表，失败返回 None
    """
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "User-Agent": get_user_agent()
    }
    
    try:
        if debug:
            print(f"  📡 请求邮箱接口: {_worker_url('/api/mails?limit=20&offset=0')}")
        # API 需要 limit 和 offset 参数
        response = http_session.get(
            _worker_url("/api/mails?limit=20&offset=0"),
            headers=headers,
            timeout=HTTP_TIMEOUT
        )
        
        if response.status_code == 200:
            result = response.json()
            
            # 处理不同的返回格式
            if isinstance(result, list):
                emails = result
            elif isinstance(result, dict):
                emails = result.get('results', result.get('mails', []))
            else:
                emails = []

            if debug:
                print(f"  ✅ 邮箱接口响应成功，邮件数量: {len(emails)}")
            return emails
        else:
            body_preview = (response.text or "")[:160].replace("\n", " ")
            print(f"  获取邮件错误: HTTP {response.status_code}, 响应: {body_preview}")
            
    except Exception as e:
        print(f"  获取邮件错误: {e}")
    
    return None


def get_email_detail(jwt_token: str, email_id: str):
    """
    获取邮件详情
    
    参数:
        jwt_token: JWT 令牌
        email_id: 邮件 ID
    
    返回:
        dict: 邮件详情，失败返回 None
    """
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "User-Agent": get_user_agent()
    }
    
    try:
        response = http_session.get(
            _worker_url(f"/api/mails/{email_id}"),
            headers=headers,
            timeout=HTTP_TIMEOUT
        )
        
        if response.status_code == 200:
            return response.json()
            
    except Exception as e:
        print(f"  获取邮件详情错误: {e}")
    
    return None


def parse_raw_email(raw_content: str):
    """
    解析原始邮件内容
    
    参数:
        raw_content: 原始邮件字符串
    
    返回:
        dict: 包含 subject, body, sender 的字典
    """
    result = {'subject': '', 'body': '', 'sender': ''}
    
    if not raw_content:
        return result
    
    try:
        msg = email.message_from_string(raw_content, policy=policy.default)
        
        result['subject'] = msg.get('Subject', '')
        result['sender'] = msg.get('From', '')
        
        # 获取正文
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type in ['text/plain', 'text/html']:
                    payload = part.get_payload(decode=True)
                    if payload:
                        result['body'] = payload.decode('utf-8', errors='ignore')
                        break
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                result['body'] = payload.decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"  解析邮件错误: {e}")
    
    return result


def wait_for_verification_email(jwt_token: str, timeout: int = None, exclude_email_ids=None):
    """
    等待并提取 OpenAI 验证码
    会持续轮询邮箱直到收到验证邮件或超时
    
    参数:
        jwt_token: JWT 令牌
        timeout: 超时时间（秒），默认使用配置文件中的值
        exclude_email_ids: 需要忽略的邮件 ID 集合（用于只匹配新验证码）
    
    返回:
        str: 验证码，未找到返回 None
    """
    if timeout is None:
        timeout = EMAIL_WAIT_TIMEOUT
    if not jwt_token:
        print("❌ 缺少邮箱 JWT，无法自动拉取验证码")
        return None

    excluded_ids = {str(x) for x in (exclude_email_ids or []) if x}
    
    print(f"⏳ 正在等待验证邮件（最长 {timeout} 秒）...")
    print(f"   已排除历史邮件数量: {len(excluded_ids)}")
    start_time = time.time()
    poll_round = 0
    
    while time.time() - start_time < timeout:
        poll_round += 1
        print(f"  🔄 第 {poll_round} 次轮询邮箱...")
        emails = fetch_emails(jwt_token, debug=True)
        
        if emails and len(emails) > 0:
            for email_item in emails:
                email_id = email_item.get('id')
                if email_id and str(email_id) in excluded_ids:
                    continue

                # 尝试解析 raw 字段（如果存在）
                raw_content = email_item.get('raw', '')
                if raw_content:
                    parsed = parse_raw_email(raw_content)
                    subject = parsed['subject']
                    sender = parsed['sender'].lower()
                    body = parsed['body']
                else:
                    # 回退到旧的字段
                    sender = str(email_item.get('from') or email_item.get('source', '')).lower()
                    subject = email_item.get('subject', '') or ''
                    body = ''

                # 不强依赖发件人字段，先直接尝试提取 6 位验证码
                code = extract_verification_code(subject)
                if code:
                    print(f"\n📧 收到验证码邮件（主题命中）: {subject}")
                    return code

                if body:
                    code = extract_verification_code(body)
                    if code:
                        print(f"\n📧 收到验证码邮件（正文命中）: {subject}")
                        return code

                # 如未匹配，再尝试读取详情做二次提取
                if email_id:
                    detail = get_email_detail(jwt_token, email_id)
                    if detail:
                        # 解析详情中的 raw
                        detail_raw = detail.get('raw', '')
                        if detail_raw:
                            parsed_detail = parse_raw_email(detail_raw)
                            code = extract_verification_code(parsed_detail['subject'])
                            if code:
                                print(f"\n📧 收到验证码邮件（详情主题命中）: {subject}")
                                return code
                            code = extract_verification_code(parsed_detail['body'])
                            if code:
                                print(f"\n📧 收到验证码邮件（详情正文命中）: {subject}")
                                return code
                        
                        # 尝试其他字段
                        content = (
                            detail.get('html') or 
                            detail.get('html_content') or 
                            detail.get('text') or 
                            detail.get('content', '')
                        )
                        if content:
                            code = extract_verification_code(content)
                            if code:
                                print(f"\n📧 收到验证码邮件（详情内容命中）: {subject}")
                                return code
        
        # 显示等待进度
        elapsed = int(time.time() - start_time)
        print(f"  等待中... ({elapsed}秒)", end='\r')
        time.sleep(EMAIL_POLL_INTERVAL)
    
    print("\n⏰ 等待验证邮件超时")
    return None

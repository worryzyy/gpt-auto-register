"""
sub2api 服务客户端
负责与 sub2api 后端 API 交互，实现注册账号自动绑定
"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import Optional, List


class Sub2ApiClient:
    """sub2api API 客户端"""

    def __init__(self, base_url: str, email: str, password: str):
        self.base_url = base_url.rstrip('/')
        self.email = email
        self.password = password
        self.token = None

        # 配置 requests session
        self.session = requests.Session()
        retry = Retry(
            total=3,
            connect=3,
            read=3,
            backoff_factor=1,
            status_forcelist=[429, 502, 503, 504],
            allowed_methods=None,
        )
        self.session.mount('http://', HTTPAdapter(max_retries=retry))
        self.session.mount('https://', HTTPAdapter(max_retries=retry))

    def _headers(self) -> dict:
        """构造带 JWT 认证的请求头"""
        headers = {'Content-Type': 'application/json'}
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'
        return headers

    def login(self):
        """
        登录 sub2api 获取 JWT token
        POST /api/v1/auth/login
        """
        url = f'{self.base_url}/api/v1/auth/login'
        payload = {
            'email': self.email,
            'password': self.password
        }

        print(f"🔑 正在登录 sub2api ({self.base_url})...")
        resp = self.session.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=30)
        resp.raise_for_status()

        data = resp.json()
        if data.get('code') != 0:
            raise Exception(f"sub2api 登录失败: {data.get('message', 'Unknown error')}")

        result = data.get('data', {})
        self.token = result.get('access_token')
        if not self.token:
            raise Exception("sub2api 登录响应中未找到 access_token")

        print(f"✅ sub2api 登录成功")
        return self.token

    def generate_openai_auth_url(self) -> tuple:
        """
        生成 OpenAI OAuth 授权 URL
        POST /api/v1/admin/openai/generate-auth-url

        返回: (auth_url, session_id)
        """
        if not self.token:
            raise Exception("未登录 sub2api，请先调用 login()")

        url = f'{self.base_url}/api/v1/admin/openai/generate-auth-url'

        print("🔗 正在生成 OpenAI OAuth 授权 URL...")
        resp = self.session.post(url, json={}, headers=self._headers(), timeout=30)
        resp.raise_for_status()

        data = resp.json()
        if data.get('code') != 0:
            raise Exception(f"生成 OAuth URL 失败: {data.get('message', 'Unknown error')}")

        result = data.get('data', {})
        auth_url = result.get('auth_url')
        session_id = result.get('session_id')

        if not auth_url or not session_id:
            raise Exception(f"OAuth URL 响应不完整: auth_url={auth_url}, session_id={session_id}")

        print(f"✅ OAuth URL 已生成 (session: {session_id[:8]}...)")
        return auth_url, session_id

    def create_account_from_oauth(
        self,
        session_id: str,
        code: str,
        state: str,
        name: str = None,
        concurrency: Optional[int] = None,
        priority: Optional[int] = None,
        group_ids: Optional[List[int]] = None
    ) -> dict:
        """
        使用 OAuth 授权码在 sub2api 中创建账号
        POST /api/v1/admin/openai/create-from-oauth

        参数:
            session_id: sub2api OAuth 会话 ID
            code: OAuth 授权码
            state: OAuth state 参数
            name: 账号名称（默认使用邮箱）

        返回: 创建的账号信息 dict
        """
        if not self.token:
            raise Exception("未登录 sub2api，请先调用 login()")

        url = f'{self.base_url}/api/v1/admin/openai/create-from-oauth'
        payload = {
            'session_id': session_id,
            'code': code,
            'state': state,
        }
        if name:
            payload['name'] = name
        if concurrency is not None:
            payload['concurrency'] = int(concurrency)
        if priority is not None:
            payload['priority'] = int(priority)
        if group_ids is not None:
            payload['group_ids'] = list(group_ids)

        print("📤 正在调用 sub2api 创建 OpenAI 账号...")
        resp = self.session.post(url, json=payload, headers=self._headers(), timeout=60)
        resp.raise_for_status()

        data = resp.json()
        if data.get('code') != 0:
            raise Exception(f"创建账号失败: {data.get('message', 'Unknown error')}")

        account = data.get('data', {})
        account_id = account.get('id', 'N/A')
        account_name = account.get('name', 'N/A')
        print(f"✅ sub2api 账号创建成功! ID: {account_id}, Name: {account_name}")
        return account

    def update_account(
        self,
        account_id: int,
        concurrency: Optional[int] = None,
        priority: Optional[int] = None,
        group_ids: Optional[List[int]] = None
    ) -> dict:
        """
        更新 sub2api 账号调度配置
        PUT /api/v1/admin/accounts/{id}
        """
        if not self.token:
            raise Exception("未登录 sub2api，请先调用 login()")

        url = f'{self.base_url}/api/v1/admin/accounts/{int(account_id)}'
        payload = {}
        if concurrency is not None:
            payload['concurrency'] = int(concurrency)
        if priority is not None:
            payload['priority'] = int(priority)
        if group_ids is not None:
            payload['group_ids'] = list(group_ids)

        if not payload:
            return {}

        print(f"📤 正在更新 sub2api 账号配置... (ID: {account_id})")
        resp = self.session.put(url, json=payload, headers=self._headers(), timeout=60)
        resp.raise_for_status()

        data = resp.json()
        if data.get('code') != 0:
            raise Exception(f"更新账号失败: {data.get('message', 'Unknown error')}")

        account = data.get('data', {})
        print(f"✅ sub2api 账号配置更新成功! ID: {account.get('id', account_id)}")
        return account

    def get_account(self, account_id: int) -> dict:
        """
        查询账号详情
        GET /api/v1/admin/accounts/{id}
        """
        if not self.token:
            raise Exception("未登录 sub2api，请先调用 login()")

        url = f'{self.base_url}/api/v1/admin/accounts/{int(account_id)}'
        resp = self.session.get(url, headers=self._headers(), timeout=30)
        resp.raise_for_status()

        data = resp.json()
        if data.get('code') != 0:
            raise Exception(f"查询账号详情失败: {data.get('message', 'Unknown error')}")

        return data.get('data', {})

    def update_account_full(self, account_id: int, payload: dict) -> dict:
        """
        使用完整 payload 更新账号（优先 POST，失败时回退 PUT）
        POST /api/v1/admin/accounts/{id}
        PUT  /api/v1/admin/accounts/{id}
        """
        if not self.token:
            raise Exception("未登录 sub2api，请先调用 login()")

        url = f'{self.base_url}/api/v1/admin/accounts/{int(account_id)}'
        print(f"📤 正在通过 POST 更新 sub2api 账号... (ID: {account_id})")
        resp = self.session.post(url, json=payload, headers=self._headers(), timeout=60)

        if resp.status_code in (404, 405):
            print("⚠️ POST 更新不可用，回退为 PUT 更新...")
            resp = self.session.put(url, json=payload, headers=self._headers(), timeout=60)

        resp.raise_for_status()
        data = resp.json()
        if data.get('code') != 0:
            raise Exception(f"完整更新账号失败: {data.get('message', 'Unknown error')}")

        account = data.get('data', {})
        print(f"✅ sub2api 账号完整更新成功! ID: {account.get('id', account_id)}")
        return account

    def refresh_openai_token(self, refresh_token: str) -> dict:
        """
        使用 refresh_token 刷新 OpenAI token（备用方案）
        POST /api/v1/admin/openai/refresh-token

        返回: token 信息 dict
        """
        if not self.token:
            raise Exception("未登录 sub2api，请先调用 login()")

        url = f'{self.base_url}/api/v1/admin/openai/refresh-token'
        payload = {'refresh_token': refresh_token}

        resp = self.session.post(url, json=payload, headers=self._headers(), timeout=30)
        resp.raise_for_status()

        data = resp.json()
        if data.get('code') != 0:
            raise Exception(f"刷新 token 失败: {data.get('message', 'Unknown error')}")

        return data.get('data', {})
